"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { useDismissSignal, usePortalContainer } from "@/lib/shadow"
import { Tooltip as TooltipPrimitive } from "radix-ui"

function TooltipProvider({
  delayDuration = 0,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
  return (
    <TooltipPrimitive.Provider
      data-slot="tooltip-provider"
      delayDuration={delayDuration}
      {...props}
    />
  )
}

/**
 * FPS: the tooltip content renders in the body-level portal host, outside the
 * page container the desk hides on navigation, so an open tooltip is closed
 * when the route leaves the dashboard's workspace (useDismissSignal). The Root
 * stays uncontrolled for callers; `open` / `onOpenChange` still work.
 */
function Tooltip({
  open: openProp,
  defaultOpen,
  onOpenChange,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen ?? false)
  const isControlled = openProp !== undefined
  const dismissSignal = useDismissSignal()
  const [seenSignal, setSeenSignal] = React.useState(dismissSignal)
  if (seenSignal !== dismissSignal) {
    setSeenSignal(dismissSignal)
    if (uncontrolledOpen) setUncontrolledOpen(false)
  }
  const handleOpenChange = React.useCallback(
    (next: boolean) => {
      if (!isControlled) setUncontrolledOpen(next)
      onOpenChange?.(next)
    },
    [isControlled, onOpenChange]
  )
  return (
    <TooltipPrimitive.Root
      data-slot="tooltip"
      open={isControlled ? openProp : uncontrolledOpen}
      onOpenChange={handleOpenChange}
      {...props}
    />
  )
}

function TooltipTrigger({
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />
}

function TooltipContent({
  className,
  sideOffset = 0,
  children,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  // FPS: the dashboard lives in its own shadow root. Radix portals to
  // document.body by default, outside every shadow root and its styles, so the
  // tooltip would render unstyled. Portal into the body-level <fps-cc-portal>
  // host's container instead (its own shadow root with the dashboard CSS,
  // z-index 1030, above the desk navbar and sidebar).
  // FPS: raised glass (DESIGN.md §1: drawer, tooltip, popover), like the chart
  // tooltip, instead of shadcn's inverted light bubble. No arrow: a rotated
  // square under translucent glass shows through as a darker diamond.
  // FPS: the zoom/slide entry and exit stop under prefers-reduced-motion
  // (DESIGN.md §7 / CommandCenter.meta "all motion stops"). Radix tooltips
  // open as data-state="delayed-open" | "instant-open" (never "open"), so the
  // plain motion-reduce:animate-none covers the entry; the closed variant
  // covers the exit.
  const portalContainer = usePortalContainer()
  return (
    <TooltipPrimitive.Portal container={portalContainer ?? undefined}>
      <TooltipPrimitive.Content
        data-slot="tooltip-content"
        sideOffset={sideOffset}
        className={cn(
          "glass-raised z-50 w-fit origin-(--radix-tooltip-content-transform-origin) animate-in rounded-lg px-3 py-1.5 text-xs leading-4 text-balance text-ink fade-in-0 zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 motion-reduce:animate-none motion-reduce:data-[state=closed]:animate-none",
          className
        )}
        {...props}
      >
        {children}
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  )
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider }
