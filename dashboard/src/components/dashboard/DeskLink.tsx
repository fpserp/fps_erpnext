/**
 * A real <a href> for every desk route the dashboard links to.
 *
 * Why an anchor and not a button with onClick → navigate(): executives open
 * lists in new tabs. The href (deskHref, canonical /desk path with the query
 * kept) makes middle-click, Ctrl/Cmd-click and "copy link" work natively,
 * while a plain left click stays inside the SPA through navigate(), which
 * carries the list filters in frappe.route_options (see lib/frappe.ts).
 *
 * Inside the dashboard's shadow roots (the block's <fps-command-center>, the
 * body-level portal host) the desk's own delegated <a> handler never sees this
 * anchor (the click is retargeted to the shadow host), so there is no double
 * navigation.
 *
 * Navigation only: this component never writes anything.
 */
import * as React from "react";
import { deskHref, navigate } from "@/lib/frappe";
import type { DeskRoute } from "@/types/dashboard";

export interface DeskLinkProps extends Omit<React.ComponentProps<"a">, "href"> {
  route: DeskRoute;
  /** Runs before an in-app navigation (e.g. close the drawer). Not on new-tab clicks. */
  onNavigate?: () => void;
}

export function DeskLink({ route, onNavigate, onClick, children, ...rest }: DeskLinkProps): React.JSX.Element {
  const handleClick = (event: React.MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented) return;
    // Let the browser handle new-tab / new-window / download gestures.
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onNavigate?.();
    navigate(route);
  };
  return (
    <a href={deskHref(route)} onClick={handleClick} {...rest}>
      {children}
    </a>
  );
}
