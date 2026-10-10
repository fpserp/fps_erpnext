/**
 * Vite config for the FPS Command Center.
 *
 * `vite` (dev): the harness at http://localhost:5199 (index.html ->
 * dev/main.dev.tsx), which fakes the desk around a real shadow-root mount.
 *
 * `vite build`: library mode, ONE self-contained ES module,
 * fps_erpnext/public/dashboard/fps-command-center.js:
 *  - the theme CSS is imported "?inline" and adopted by the dashboard's own
 *    shadow roots at mount time, so no .css file is emitted (a <link> in
 *    document.head could not style a shadow root anyway);
 *  - no code splitting: the block loader imports one URL with a ?v=<hash>
 *    cache-buster (sync-block.mjs), and /assets is served immutable for a year,
 *    so a lazily loaded chunk without that hash could be stale or missing;
 *  - the folder is NOT public/dist (gitignored, and cleaned by bench build) and
 *    the name has no ".bundle." (Frappe's esbuild would try to rebuild it).
 * A guard plugin fails the build if anything other than that one file appears,
 * if a single @property rule survives, or if the shadow-root defaults are
 * missing (see tailwindShadowDom below).
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { transform } from "esbuild";
import type { AtRule, Plugin as PostcssPlugin, Rule } from "postcss";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(here, "../fps_erpnext/public/dashboard");
const BUNDLE_FILE = "fps-command-center.js";
/** The block's own HTML/CSS/loader (read-only here; the harness renders the real files). */
const BLOCK_SOURCES = path.resolve(here, "../docs/design_handoff_fps_workspace/custom_blocks");

const pkg = JSON.parse(readFileSync(path.join(here, "package.json"), "utf8")) as { version?: string };

/* ------------------------------------------------------------------------ */
/* Tailwind v4 inside a shadow root: @property                                */
/* ------------------------------------------------------------------------ */

/** Canonical zero per typed syntax: an unregistered "0" would break calc(2px + var(...)). */
const TYPED_ZERO: Readonly<Record<string, string>> = {
  "<length>": "0px",
  "<length-percentage>": "0px",
  "<percentage>": "0%",
  "<angle>": "0deg",
  "<time>": "0s",
};

/**
 * Tailwind v4 keeps the DEFAULTS of its --tw-* variables (shadow, ring,
 * border-style, transforms, gradients, tw-animate-css enter/exit …) in
 * `@property` rules, and browsers ignore `@property` inside shadow trees, so
 * `border`, `shadow-*`, `ring-*` and the slide-in animations silently paint
 * nothing in the dashboard's shadow roots. Tailwind does ship plain fallbacks,
 * `@layer properties { @supports (<old Safari/Firefox only>) { *, ::before,
 * ::after, ::backdrop { --tw-…: … } } }`, but the @supports guard never matches
 * Chrome or Edge.
 *
 * This PostCSS step (dev and build, after Tailwind has compiled the file):
 *  1. unwraps that @supports, so the fallbacks always apply;
 *  2. adds `:host` to the fallback rule, so the shadow host gets them too;
 *  3. appends a default for any registered property the fallback block does
 *     not cover (none today; derived from the rule's initial-value, inherits
 *     false on every element, inherits true on :host only);
 *  4. drops every `@property` rule.
 * The defaults stay INSIDE `@layer properties` — the lowest layer Tailwind
 * declares — so every utility still overrides them; unlayered, they would beat
 * `@layer utilities` and `shadow-lg` would resolve to `0 0 #0000`.
 *
 * Nothing is registered on the document: the old runtime fix (a <style> of
 * @property rules in document.head) changed --tw-* desk-wide, which the
 * presentation-only rule does not allow. The only thing lost is animating the
 * --tw-* variables themselves, which nothing here does.
 */
function tailwindShadowDom(): PostcssPlugin {
  return {
    postcssPlugin: "fps-tailwind-shadow-dom",
    OnceExit(root, { atRule, rule, decl }) {
      const registered = new Map<string, { inherits: boolean; value: string }>();
      root.walkAtRules("property", (property) => {
        let syntax = "";
        let inherits = false;
        let initial: string | null = null;
        property.walkDecls((d) => {
          if (d.prop === "syntax") syntax = d.value.replace(/^["']|["']$/g, "").trim();
          else if (d.prop === "inherits") inherits = d.value.trim().toLowerCase() === "true";
          else if (d.prop === "initial-value") initial = d.value.trim();
        });
        let value: string = initial ?? "initial";
        if (initial !== null && /^[+-]?0*\.?0+$/.test(initial) && TYPED_ZERO[syntax]) value = TYPED_ZERO[syntax];
        registered.set(property.params.trim(), { inherits, value });
        property.remove();
      });
      if (registered.size === 0) return;

      let layer: AtRule | null = null;
      let defaults: Rule | null = null;
      root.walkAtRules("layer", (candidate) => {
        // `@layer properties;` (the order statement) has no body; skip it.
        if (candidate.params.trim() !== "properties" || !candidate.nodes) return;
        layer ??= candidate;
        candidate.walkAtRules("supports", (supports) => {
          supports.replaceWith(supports.nodes ?? []);
        });
        candidate.walkRules((r) => {
          if (!r.selectors.includes("*")) return;
          if (!r.selectors.includes(":host")) r.selectors = [":host", ...r.selectors];
          defaults ??= r;
        });
      });

      const covered = new Set<string>();
      (defaults as Rule | null)?.walkDecls((d) => {
        covered.add(d.prop);
      });
      const missing = Array.from(registered).filter(([name]) => !covered.has(name));
      if (missing.length === 0) return;
      if (!layer) {
        layer = atRule({ name: "layer", params: "properties" });
        root.prepend(layer);
      }
      const target: AtRule = layer;
      if (!defaults && missing.some(([, r]) => !r.inherits)) {
        defaults = rule({ selectors: [":host", "*", "::before", "::after", "::backdrop"] });
        target.append(defaults);
      }
      let hostOnly: Rule | null = null;
      for (const [name, r] of missing) {
        if (!r.inherits) {
          (defaults as Rule | null)?.append(decl({ prop: name, value: r.value }));
          continue;
        }
        if (!hostOnly) {
          hostOnly = rule({ selector: ":host" });
          target.append(hostOnly);
        }
        hostOnly.append(decl({ prop: name, value: r.value }));
      }
    },
  };
}

/* ------------------------------------------------------------------------ */
/* Bundle finalisation + guard                                                */
/* ------------------------------------------------------------------------ */

/**
 * Vite deliberately skips whitespace minification for "es" library output (it
 * would strip the PURE annotations a downstream bundler could use). Nothing
 * bundles this file again — the browser imports it as is — so finish the job
 * here with the esbuild Vite already ships (full minify, ES2020, no legal
 * comments; export names are part of the module interface and are kept), and
 * enforce the single-file shape and the shadow-DOM CSS invariants.
 */
function finalizeBundle(): Plugin {
  return {
    name: "fps-cc-finalize-bundle",
    apply: "build",
    enforce: "post",
    async generateBundle(_options, bundle) {
      const files = Object.keys(bundle);
      const unexpected = files.filter((name) => name !== BUNDLE_FILE);
      if (unexpected.length > 0) {
        this.error(
          `Expected only ${BUNDLE_FILE} in the output, got: ${files.join(", ")}. ` +
            "CSS must be imported with ?inline and nothing may be code-split.",
        );
      }
      const chunk = bundle[BUNDLE_FILE];
      if (!chunk || chunk.type !== "chunk") {
        this.error(`${BUNDLE_FILE} was not produced as a JS chunk.`);
        return;
      }
      const minified = await transform(chunk.code, {
        loader: "js",
        format: "esm",
        target: "es2020",
        minify: true,
        legalComments: "none",
        sourcemap: false,
      });
      chunk.code = minified.code;

      // Shadow-DOM invariants of the inlined CSS (see tailwindShadowDom).
      const propertyRules = (chunk.code.match(/@property\s+--/g) ?? []).length;
      if (propertyRules > 0) {
        this.error(`${propertyRules} @property rule(s) reached the bundle; they are ignored in shadow roots.`);
      }
      if (!chunk.code.includes("@layer properties{:host,*")) {
        this.error('The "@layer properties{:host,*" defaults are missing from the bundle CSS.');
      }
      for (const name of ["mount", "unmountAll", "version"]) {
        if (!chunk.exports.includes(name)) this.error(`The bundle no longer exports "${name}".`);
      }
    },
  };
}

export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss(), finalizeBundle()],
  resolve: { alias: { "@": path.resolve(here, "src") } },
  css: {
    postcss: { plugins: [tailwindShadowDom()] },
  },
  define: {
    __FPS_CC_VERSION__: JSON.stringify(command === "build" ? (pkg.version ?? "0.0.0") : `${pkg.version ?? "0.0.0"}-dev`),
    // Library mode leaves process.env.NODE_ENV for a downstream bundler; there
    // is none, so pin it (React's production build, dead dev code removed).
    // Dev keeps Vite's own handling so React's warnings stay on.
    ...(command === "build" ? { "process.env.NODE_ENV": JSON.stringify("production") } : {}),
  },
  // dashboard/public does not exist; never copy anything next to the bundle.
  publicDir: false,
  server: {
    port: 5199,
    strictPort: true,
    // The harness loads the host-page CSS the app ships (fps_erpnext/public/css)
    // and the FPS Overview block's own HTML/CSS when they exist; allow reading
    // them (read-only).
    fs: { allow: [here, path.resolve(here, "../fps_erpnext/public"), BLOCK_SOURCES] },
  },
  build: {
    outDir: OUT_DIR,
    // The folder holds only our bundle, but never wipe a folder outside the
    // project; the guard plugin keeps the output to one file instead.
    emptyOutDir: false,
    copyPublicDir: false,
    sourcemap: false,
    minify: "esbuild",
    cssCodeSplit: false,
    reportCompressedSize: true,
    lib: {
      entry: path.resolve(here, "src/main.tsx"),
      formats: ["es"],
      fileName: () => BUNDLE_FILE,
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
  },
}));
