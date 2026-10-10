/**
 * Data hooks (implemented by the core module — signatures are fixed).
 *
 * useDashboard(period): loads get_dashboard, polls every 60 s while the host
 * is visible and the tab is visible, refetches when the desk route returns to
 * the FPS workspace, and KEEPS THE PREVIOUS PAYLOAD while refetching
 * (refreshing=true) so the UI can dim instead of flashing a skeleton.
 * error is only set when there is no payload at all.
 *
 * Implementation notes:
 *  - Both hooks only ever GET the two whitelisted read methods (lib/frappe).
 *  - Responses are matched to requests by a sequence id, so a slow answer for
 *    an old period or metric can never overwrite a newer one, and nothing is
 *    applied after unmount (frappe.call cannot be aborted, so we ignore).
 *  - Payloads are cached per page (stale-while-revalidate). Frappe re-runs the
 *    block script on every edit toggle, Save and Discard, which remounts the
 *    whole app; the cache lets the new mount paint the last numbers at once.
 *  - A failing poll backs off (60 s, 2 min, 4 min … 15 min max): frappe.call
 *    opens a desk error dialog for 5xx answers, and a broken endpoint must not
 *    open one every minute.
 *  - Triggers that arrive together (route back to FPS + host visible again)
 *    are coalesced into one request.
 *  - Identical requests in flight are shared (keyed by method + arguments):
 *    React StrictMode's dev double-run of effects, two hooks asking for the
 *    same period, or a manual refresh during a poll all ride ONE frappe.call.
 *    Production renders without StrictMode, so a mount fetches once.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { DashboardPayload, KpiKey, MetricDetail, Period } from "@/types/dashboard";
import { call, getRoute, onRouteChange, type ReadMethod } from "@/lib/frappe";
import { useHostVisible, useShadowContext } from "@/lib/shadow";

export interface DashboardState {
  data: DashboardPayload | null;
  error: string | null;
  loading: boolean;
  refreshing: boolean;
  lastUpdated: Date | null;
  refresh: () => void;
}

export interface MetricDetailState {
  data: MetricDetail | null;
  error: string | null;
  loading: boolean;
  refreshing: boolean;
}

const GET_DASHBOARD = "fps_erpnext.api.command_center.get_dashboard";
const GET_METRIC_DETAIL = "fps_erpnext.api.command_center.get_metric_detail";

/** Poll cadence while the dashboard is on screen. */
export const POLL_INTERVAL_MS = 60_000;
const MAX_BACKOFF_MS = 15 * 60_000;
/** Automatic triggers closer together than this share one request. */
const COALESCE_MS = 1_500;
const DETAIL_CACHE_SIZE = 24;

interface CacheEntry<T> {
  data: T;
  at: number;
}

// Page-lifetime caches. One desk session = one user, so no keying by user.
const dashboardCache = new Map<Period, CacheEntry<DashboardPayload>>();
const detailCache = new Map<string, CacheEntry<MetricDetail>>();

/** Requests in flight, by method + arguments; an entry lives until it settles. */
const inFlightRequests = new Map<string, Promise<unknown>>();

/** call(), but an identical request already in flight is joined instead of repeated. */
function sharedCall<T>(method: ReadMethod, args: Record<string, unknown>): Promise<T> {
  const key = `${method}?${JSON.stringify(Object.entries(args).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))}`;
  const running = inFlightRequests.get(key);
  if (running) return running as Promise<T>;
  const request = call<T>(method, args).finally(() => {
    if (inFlightRequests.get(key) === request) inFlightRequests.delete(key);
  });
  inFlightRequests.set(key, request);
  return request;
}

function rememberDetail(cacheKey: string, data: MetricDetail): void {
  detailCache.delete(cacheKey); // re-insert = most recently used
  detailCache.set(cacheKey, { data, at: Date.now() });
  while (detailCache.size > DETAIL_CACHE_SIZE) {
    const oldest = detailCache.keys().next().value;
    if (oldest === undefined) break;
    detailCache.delete(oldest);
  }
}

function isFpsHome(route: string[]): boolean {
  return route[0] === "Workspaces" && route[1] === "FPS";
}

function errorText(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === "string" && err) return err;
  return fallback;
}

function isPayload(v: unknown): v is DashboardPayload {
  return typeof v === "object" && v !== null && Array.isArray((v as DashboardPayload).kpis);
}

function isDetail(v: unknown): v is MetricDetail {
  return typeof v === "object" && v !== null && typeof (v as MetricDetail).key === "string";
}

type DashboardSnapshot = Omit<DashboardState, "refresh">;

function initialDashboard(period: Period): DashboardSnapshot {
  const cached = dashboardCache.get(period);
  if (cached) {
    return { data: cached.data, error: null, loading: false, refreshing: true, lastUpdated: new Date(cached.at) };
  }
  return { data: null, error: null, loading: true, refreshing: false, lastUpdated: null };
}

export function useDashboard(period: Period): DashboardState {
  const visible = useHostVisible();
  const { host } = useShadowContext();
  const [snapshot, setSnapshot] = useState<DashboardSnapshot>(() => initialDashboard(period));

  const live = useRef(true);
  const seq = useRef(0);
  const inFlight = useRef<{ period: Period; promise: Promise<void> } | null>(null);
  const lastStartedAt = useRef(0);
  const failures = useRef(0);

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  /** force=false: an automatic trigger that may be coalesced or skipped. */
  const load = useCallback(
    (force: boolean): Promise<void> => {
      const now = Date.now();
      const running = inFlight.current;
      if (!force) {
        if (running && running.period === period) return running.promise;
        if (now - lastStartedAt.current < COALESCE_MS) return Promise.resolve();
      }
      lastStartedAt.current = now;
      const id = ++seq.current;
      setSnapshot((s) => (s.data ? { ...s, refreshing: true } : { ...s, loading: true, error: null }));

      const promise = sharedCall<DashboardPayload>(GET_DASHBOARD, { period })
        .then((payload) => {
          if (!isPayload(payload)) throw new Error("The dashboard returned no data.");
          return payload;
        })
        .then(
          (payload) => {
            if (!live.current || id !== seq.current) return;
            failures.current = 0;
            const at = new Date();
            dashboardCache.set(period, { data: payload, at: at.getTime() });
            setSnapshot({ data: payload, error: null, loading: false, refreshing: false, lastUpdated: at });
          },
          (err: unknown) => {
            if (!live.current || id !== seq.current) return;
            failures.current += 1;
            const message = errorText(err, "Could not load the dashboard.");
            // Keep the last good numbers on screen; only an empty dashboard shows the error.
            setSnapshot((s) => ({ ...s, loading: false, refreshing: false, error: s.data ? null : message }));
          },
        )
        .finally(() => {
          if (inFlight.current?.promise === promise) inFlight.current = null;
        });
      inFlight.current = { period, promise };
      return promise;
    },
    [period],
  );

  // First load, and every period change. A cached payload for the new period
  // paints immediately; otherwise the previous period's frame stays (dimmed).
  useEffect(() => {
    const cached = dashboardCache.get(period);
    if (cached) {
      setSnapshot((s) =>
        s.data === cached.data ? s : { ...s, data: cached.data, error: null, lastUpdated: new Date(cached.at) },
      );
    }
    failures.current = 0;
    void load(true);
  }, [period, load]);

  // Poll while visible; a timeout chain (not setInterval) so backoff can stretch it.
  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    let timer = 0;
    const schedule = () => {
      const delay = Math.min(POLL_INTERVAL_MS * 2 ** failures.current, MAX_BACKOFF_MS);
      timer = window.setTimeout(() => {
        if (cancelled) return;
        void load(false).finally(() => {
          if (!cancelled) schedule();
        });
      }, delay);
    };
    schedule();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [visible, load]);

  // Visible again after being hidden (back from a list, tab back in front).
  const wasVisible = useRef(visible);
  useEffect(() => {
    if (visible && !wasVisible.current) void load(false);
    wasVisible.current = visible;
  }, [visible, load]);

  // Route came back to the FPS workspace. A root whose host Frappe already
  // discarded still hears the router until it is swept; it must stay quiet.
  useEffect(() => {
    let previous = getRoute();
    return onRouteChange((route) => {
      const returning = isFpsHome(route) && !isFpsHome(previous);
      previous = route;
      if (!returning) return;
      if (host && !host.isConnected) return;
      void load(false);
    });
  }, [load, host]);

  const refresh = useCallback(() => {
    failures.current = 0;
    void load(true);
  }, [load]);

  return { ...snapshot, refresh };
}

const IDLE: MetricDetailState = { data: null, error: null, loading: false, refreshing: false };

function matches(detail: MetricDetail, key: KpiKey, period: Period, dimension: string | null): boolean {
  return detail.key === key && detail.period === period && (detail.dimension ?? null) === dimension;
}

/** Loads get_metric_detail for the open drawer; key=null means closed (no request). */
export function useMetricDetail(
  key: KpiKey | null,
  period: Period,
  dimension: string | null,
): MetricDetailState {
  const [state, setState] = useState<MetricDetailState>(IDLE);
  const live = useRef(true);
  const seq = useRef(0);

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  useEffect(() => {
    const id = ++seq.current; // also invalidates any request still in flight
    if (key === null) {
      setState(IDLE);
      return;
    }

    const cacheKey = `${key}|${period}|${dimension ?? ""}`;
    const cached = detailCache.get(cacheKey);
    setState((s) => {
      if (cached) return { data: cached.data, error: null, loading: false, refreshing: true };
      // Same metric, new period or dimension chip: keep the frame and dim it.
      if (s.data && s.data.key === key) return { ...s, error: null, loading: false, refreshing: true };
      // A different metric must never show the previous metric's numbers.
      return { data: null, error: null, loading: true, refreshing: false };
    });

    const args: Record<string, unknown> = { key, period };
    if (dimension !== null) args.dimension = dimension; // omitted, not "", for "All"

    sharedCall<MetricDetail>(GET_METRIC_DETAIL, args)
      .then((detail) => {
        if (!isDetail(detail)) throw new Error("The detail view returned no data.");
        return detail;
      })
      .then(
        (detail) => {
          if (!live.current || id !== seq.current) return;
          rememberDetail(cacheKey, detail);
          setState({ data: detail, error: null, loading: false, refreshing: false });
        },
        (err: unknown) => {
          if (!live.current || id !== seq.current) return;
          const message = errorText(err, "Could not load the details.");
          setState((s) => {
            // A failed revalidation of the same selection keeps its numbers;
            // numbers for a different selection are dropped and the error shown.
            if (s.data && matches(s.data, key, period, dimension)) {
              return { ...s, error: null, loading: false, refreshing: false };
            }
            return { data: null, error: message, loading: false, refreshing: false };
          });
        },
      );
  }, [key, period, dimension]);

  return state;
}
