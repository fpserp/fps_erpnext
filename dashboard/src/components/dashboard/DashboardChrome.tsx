/**
 * The frame both dashboards share (FPS OPS — CommandCenter.tsx, FPS ACC —
 * AccDashboard.tsx), so the two pages are one material:
 *
 *  - AmbientGlow      two decorative radial glows behind the bento (DESIGN.md §1);
 *  - DashboardHeader  title · company · as-of date · live status · refresh ·
 *                     appearance (Frappe's own Toggle Theme dialog);
 *  - ErrorState       "could not load" with Retry, when there is nothing to show;
 *  - DashboardFrame   the rounded plane both roots render on.
 *
 * Moved out of CommandCenter.tsx unchanged (14 Oct 2026); only the title became
 * a prop. PRESENTATION ONLY: nothing here reads or writes ERPNext.
 */
import * as React from "react";
import { ArrowUpRight, CircleAlert, Moon, RefreshCw, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatLongDate, formatTime } from "@/lib/format";
import { openThemeSwitcher } from "@/lib/frappe";
import { usePalette } from "@/lib/palette";
import { useHostVisible } from "@/lib/shadow";
import { POLL_INTERVAL_MS } from "@/hooks/useDashboard";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { DeskRoute } from "@/types/dashboard";
import { DeskLink } from "./DeskLink";

/** Three missed polls and the live dot turns amber "Stale". */
export const STALE_AFTER_MS = 3 * POLL_INTERVAL_MS;

/**
 * Two fixed, very low-alpha radial glows (Electric Blue top-left, Soft Violet
 * top-right) so the glass has something to blur. Decoration only — no data —
 * and removed under reduced transparency and forced colours (DESIGN.md §1).
 */
export function AmbientGlow(): React.JSX.Element {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden rounded-[inherit] forced-colors:hidden [@media(prefers-reduced-transparency:reduce)]:hidden"
    >
      {/* Strength is a palette token: 10% / 8% on Pearl, 4% / 3% on Matte Black. */}
      <div
        className="absolute -top-48 -left-40 size-[640px] rounded-full"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in oklab, var(--fps-electric) var(--fps-glow-electric, 10%), transparent), transparent)",
        }}
      />
      <div
        className="absolute -top-48 -right-40 size-[560px] rounded-full"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in oklab, var(--fps-violet) var(--fps-glow-violet, 8%), transparent), transparent)",
        }}
      />
    </div>
  );
}

/**
 * Sun / moon: opens Frappe's own Toggle Theme dialog. Light = Pearl, Dark =
 * Matte Black, Automatic = follows the computer. The choice is Frappe's to
 * save (on the user's own profile, as from the avatar menu); this button only
 * opens the dialog. Hidden where the desk has no theme dialog (dev harness
 * without a mock).
 */
export function AppearanceButton(): React.JSX.Element | null {
  const palette = usePalette();
  const [available] = React.useState(() => typeof window.frappe?.ui?.ThemeSwitcher === "function");
  if (!available) return null;
  const name = palette === "black" ? "Matte Black" : "Pearl";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Appearance: ${name}. Change theme`}
          onClick={() => openThemeSwitcher()}
          className="text-ink-secondary hover:text-ink focus-visible:ring-2 focus-visible:ring-electric"
        >
          {palette === "black" ? <Moon aria-hidden="true" /> : <Sun aria-hidden="true" />}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">
        {name} · Light = Pearl, Dark = Matte Black
      </TooltipContent>
    </Tooltip>
  );
}

/** Wall-clock ms, ticking while the dashboard is on screen (drives "Stale"). */
export function useNow(intervalMs: number): number {
  const visible = useHostVisible();
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (!visible) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [visible, intervalMs]);
  return now;
}

/** "09:30" from the server's "yyyy-mm-dd HH:mm:ss" when no client fetch time exists yet. */
function serverTime(generatedAt: string | undefined): string | null {
  const match = generatedAt ? /\d{4}-\d{2}-\d{2}[ T](\d{2}):(\d{2})/.exec(generatedAt) : null;
  return match ? `${match[1]}:${match[2]}` : null;
}

/** A link from one dashboard to the other, under the header subtitle. */
export interface HeaderLink {
  label: string;
  route: DeskRoute;
}

export interface DashboardHeaderProps {
  /** "FPS OPS Dashboard" / "FPS ACC Dashboard" (lib/variant.tsx). */
  title: string;
  /**
   * Optional link to the other dashboard (CommandCenter passes the FPS ACC
   * link to Accounts Manager holders only; the ACC API gate still guards the
   * numbers). Navigation only.
   */
  link?: HeaderLink | null;
  asOf: string | null;
  generatedAt?: string;
  lastUpdated: Date | null;
  busy: boolean;
  onRefresh: () => void;
}

export function DashboardHeader({ title, link, asOf, generatedAt, lastUpdated, busy, onRefresh }: DashboardHeaderProps): React.JSX.Element {
  const now = useNow(30_000);
  const stale = lastUpdated !== null && now - lastUpdated.getTime() > STALE_AFTER_MS;
  const time = lastUpdated ? formatTime(lastUpdated) : serverTime(generatedAt);

  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h2 className="text-xl leading-7 font-semibold tracking-tight text-ink">{title}</h2>
        <p className="text-[13px] leading-5 text-ink-muted">
          Fast Planet Shipping{asOf ? ` · ${formatLongDate(asOf)}` : ""}
        </p>
        {link ? (
          <DeskLink
            route={link.route}
            className="-mx-1 mt-1 inline-flex items-center gap-1 rounded-md px-1 text-[13px] leading-5 font-medium text-electric-ui decoration-1 underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-electric"
          >
            {link.label}
            <ArrowUpRight aria-hidden="true" className="size-3.5 shrink-0" />
          </DeskLink>
        ) : null}
      </div>
      <div className="flex items-center gap-2">
        {time ? (
          <span className="flex items-center gap-2 text-xs leading-4 text-ink-muted">
            <span aria-hidden="true" className="relative flex size-2">
              {!stale ? (
                <span className="absolute inset-0 animate-ping rounded-full bg-mint/50 [animation-duration:2.4s] motion-reduce:hidden" />
              ) : null}
              <span className={cn("relative size-2 rounded-full", stale ? "bg-amber" : "bg-mint")} />
            </span>
            <span>
              <span className={cn("font-medium", stale ? "text-amber" : "text-ink-secondary")}>{stale ? "Stale" : "Live"}</span>
              {` · Updated ${time}`}
            </span>
          </span>
        ) : null}
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Refresh dashboard"
          aria-busy={busy}
          onClick={onRefresh}
          className="text-ink-secondary hover:text-ink focus-visible:ring-2 focus-visible:ring-electric"
        >
          <RefreshCw aria-hidden="true" className={cn(busy && "animate-spin motion-reduce:animate-none")} />
        </Button>
        <AppearanceButton />
      </div>
    </header>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }): React.JSX.Element {
  return (
    <div role="alert" className="glass flex flex-col items-start gap-4 rounded-2xl p-6">
      <p className="flex items-center gap-2 text-base leading-6 font-semibold text-ink">
        <CircleAlert aria-hidden="true" className="size-5 shrink-0 text-rose" />
        Could not load the dashboard
      </p>
      <p className="max-w-[72ch] text-sm leading-5 text-ink-secondary">{message}</p>
      <Button variant="outline" size="sm" onClick={onRetry} className="gap-2 px-4 has-[>svg]:px-4">
        <RefreshCw aria-hidden="true" />
        Retry
      </Button>
    </div>
  );
}

/**
 * The plane both dashboards render on. No overflow-hidden: it would clip the
 * charts' in-chart tooltips. The ambient glow clips itself (its own
 * overflow-hidden + inherited radius).
 */
export function DashboardFrame({ slot, children }: { slot: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div
      data-slot={slot}
      className="@container/cc relative isolate min-w-0 rounded-2xl bg-plane font-sans text-ink antialiased"
    >
      <AmbientGlow />
      {children}
    </div>
  );
}
