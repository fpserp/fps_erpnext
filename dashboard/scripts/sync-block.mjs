#!/usr/bin/env node
/**
 * After `vite build`: stamp the bundle's content hash into the FPS Overview
 * block loader, then regenerate the Frappe fixtures from the block sources.
 *
 * Why: Frappe Cloud serves /assets with "Cache-Control: max-age=31536000,
 * immutable". The bundle keeps one stable filename, so the block loader must
 * import it as fps-command-center.js?v=<hash>; a new build that kept the old
 * ?v= would never reach a browser that has the old file cached.
 *
 * Steps:
 *  1. sha256(fps_erpnext/public/dashboard/fps-command-center.js), first 12 hex.
 *  2. Rewrite the line `var FPS_CC_VERSION = "<anything>";` in
 *     docs/design_handoff_fps_workspace/custom_blocks/fps_overview.js.
 *     If that file or that marker is missing: print a warning and exit 0
 *     (the loader is maintained separately and may not exist yet).
 *  3. Run `python docs/design_handoff_fps_workspace/build_workspaces.py` from
 *     the repo root, which writes fps_erpnext/fixtures/custom_html_block.json
 *     (and the workspace fixtures). Its output is printed; a failure exits
 *     non-zero.
 *
 * This only edits files in the repo. It never talks to the live site; the
 * fixtures reach ERPNext through a normal deploy (`bench migrate`). No STAMP
 * bump is needed for the block: fixtures are imported with force=True on
 * every migrate (Frappe v16 frappe/utils/fixtures.py -> import_doc). STAMP in
 * build_workspaces.py only gates the workspace module JSON under
 * fps_erpnext/fps/.
 *
 * Options:
 *   --dry-run      compute and report, write nothing, do not run python
 *   --no-python    stamp the loader but skip the fixture regeneration
 *   --block=<path> use another loader file (testing)
 * Env: PYTHON=<interpreter> to choose the Python executable.
 */
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const dashboardDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(dashboardDir, "..");

const BUNDLE = path.join(repoRoot, "fps_erpnext", "public", "dashboard", "fps-command-center.js");
const DEFAULT_BLOCK = path.join(repoRoot, "docs", "design_handoff_fps_workspace", "custom_blocks", "fps_overview.js");
const GENERATOR = path.join("docs", "design_handoff_fps_workspace", "build_workspaces.py");
const MARKER = /var FPS_CC_VERSION = "[^"]*";/g;

const argv = process.argv.slice(2);
const dryRun = argv.includes("--dry-run");
const skipPython = argv.includes("--no-python");
const blockArg = argv.find((a) => a.startsWith("--block="));
const blockFile = blockArg ? path.resolve(blockArg.slice("--block=".length)) : DEFAULT_BLOCK;

const rel = (p) => path.relative(repoRoot, p).split(path.sep).join("/");
const kb = (n) => `${(n / 1024).toFixed(1)} KiB`;

function warn(message) {
  console.warn(`\n[sync-block] WARNING: ${message}\n`);
}

// 1. Hash the bundle -----------------------------------------------------------
if (!existsSync(BUNDLE)) {
  console.error(`[sync-block] ${rel(BUNDLE)} does not exist. Run "npm run build:bundle" first.`);
  process.exit(1);
}
const bytes = readFileSync(BUNDLE);
const hash = createHash("sha256").update(bytes).digest("hex").slice(0, 12);
console.log(`[sync-block] ${rel(BUNDLE)}: ${kb(bytes.length)} raw, ${kb(gzipSync(bytes, { level: 9 }).length)} gzip, v=${hash}`);

// 2. Stamp the loader ----------------------------------------------------------
if (!existsSync(blockFile)) {
  warn(`${rel(blockFile)} not found, so no loader was stamped and the fixtures were not regenerated.`);
  process.exit(0);
}
const source = readFileSync(blockFile, "utf8");
const matches = source.match(MARKER) ?? [];
if (matches.length === 0) {
  warn(
    `${rel(blockFile)} has no line matching  var FPS_CC_VERSION = "...";\n` +
      "  Add it to the loader (it must build the import URL from it), then rebuild.\n" +
      "  Nothing was stamped and the fixtures were not regenerated.",
  );
  process.exit(0);
}
if (matches.length > 1) {
  warn(`${rel(blockFile)} has ${matches.length} FPS_CC_VERSION lines; all of them are stamped.`);
}
const stamped = source.replace(MARKER, `var FPS_CC_VERSION = "${hash}";`);
if (stamped === source) {
  console.log(`[sync-block] ${rel(blockFile)} already at v=${hash}.`);
} else if (dryRun) {
  console.log(`[sync-block] (dry run) would stamp ${rel(blockFile)} with v=${hash}.`);
} else {
  writeFileSync(blockFile, stamped, "utf8");
  console.log(`[sync-block] stamped ${rel(blockFile)} with v=${hash}.`);
}

// 3. Regenerate the fixtures ---------------------------------------------------
if (dryRun || skipPython) {
  console.log(`[sync-block] skipped ${GENERATOR.split(path.sep).join("/")} (${dryRun ? "--dry-run" : "--no-python"}).`);
  process.exit(0);
}

const candidates = process.env.PYTHON
  ? [[process.env.PYTHON]]
  : process.platform === "win32"
    ? [["python"], ["py", "-3"], ["python3"]]
    : [["python3"], ["python"]];

for (const [exe, ...pre] of candidates) {
  const run = spawnSync(exe, [...pre, GENERATOR], { cwd: repoRoot, stdio: "inherit" });
  if (run.error && run.error.code === "ENOENT") continue; // try the next interpreter
  if (run.error) {
    console.error(`[sync-block] could not run ${exe}: ${run.error.message}`);
    process.exit(1);
  }
  if (run.status !== 0) {
    console.error(`[sync-block] ${exe} ${GENERATOR} exited with ${run.status ?? run.signal}.`);
    process.exit(run.status || 1);
  }
  console.log(`[sync-block] fixtures regenerated with ${[exe, ...pre].join(" ")}.`);
  process.exit(0);
}
const tried = candidates.map((c) => c.join(" ")).join(", ");
console.error(`[sync-block] no Python interpreter found (tried ${tried}). Set PYTHON=<interpreter> and retry.`);
process.exit(1);
