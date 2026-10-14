/**
 * Which dashboard a mount shows. One bundle, two pages:
 *
 *   "ops"  FPS OPS Dashboard — Workspace "FPS" (FPS Home), block "FPS Overview",
 *          open to every desk user, no money. Reads fps_erpnext.api.command_center.
 *   "acc"  FPS ACC Dashboard — Workspace "FPS ACC", block "FPS ACC Overview",
 *          Accounts Manager only (the API checks the role before it reads
 *          anything). Reads fps_erpnext.api.acc_dashboard.
 *
 * The block loader picks the variant (mount(root, { variant })); main.tsx
 * records it on the element (data-variant) and puts it in this context, so the
 * data hooks (hooks/useDashboard.ts) and the shared drawer call the right
 * read-only methods and keep separate caches.
 *
 * Presentation only: nothing here reads or writes ERPNext.
 */
import * as React from "react";
import type { ReadMethod } from "@/lib/frappe";

export type DashboardVariant = "ops" | "acc";

export interface VariantSpec {
  /** Page title (the dashboard's h2). */
  title: string;
  /** Workspace the block lives on: getRoute() reports ["Workspaces", <this>]. */
  workspace: string;
  /** get_dashboard(period) for this page. */
  dashboardMethod: ReadMethod;
  /** get_metric_detail(key, period, dimension) for this page's drawer. */
  detailMethod: ReadMethod;
}

export const VARIANTS: Readonly<Record<DashboardVariant, VariantSpec>> = {
  ops: {
    title: "FPS OPS Dashboard",
    workspace: "FPS",
    dashboardMethod: "fps_erpnext.api.command_center.get_dashboard",
    detailMethod: "fps_erpnext.api.command_center.get_metric_detail",
  },
  acc: {
    title: "FPS ACC Dashboard",
    // Workspace name "FPS ACC" (slug fps-acc). Frappe v16 router.js
    // convert_to_standard_route maps /desk/fps-acc to ["Workspaces", "FPS ACC"]
    // (frappe.workspaces is keyed by slug(page.name)).
    workspace: "FPS ACC",
    dashboardMethod: "fps_erpnext.api.acc_dashboard.get_dashboard",
    detailMethod: "fps_erpnext.api.acc_dashboard.get_metric_detail",
  },
};

export function isVariant(value: unknown): value is DashboardVariant {
  return value === "ops" || value === "acc";
}

const VariantContext = React.createContext<DashboardVariant>("ops");
VariantContext.displayName = "FpsDashboardVariant";

export function VariantProvider({ value, children }: { value: DashboardVariant; children: React.ReactNode }): React.JSX.Element {
  return <VariantContext value={value}>{children}</VariantContext>;
}

/** The variant of the dashboard this component renders in ("ops" outside a provider). */
export function useDashboardVariant(): DashboardVariant {
  return React.useContext(VariantContext);
}
