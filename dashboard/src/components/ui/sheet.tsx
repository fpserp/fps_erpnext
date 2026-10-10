import * as React from "react"
import { cn } from "@/lib/utils"
import { getDeepActiveElement, useDismissSignal, usePortalContainer } from "@/lib/shadow"
import { XIcon } from "lucide-react"
import { Dialog as SheetPrimitive } from "radix-ui"

/*
 * FPS patch: shadcn's Sheet, made to work across TWO shadow roots.
 *
 * 1. Portal. Content portals into the container of the body-level
 *    <fps-cc-portal> host (usePortalContainer; its own shadow root, z-index
 *    1030), not document.body, where the dashboard's styles do not reach, and
 *    not the block, where EditorJS's stacking context would keep the drawer
 *    under the desk navbar and sidebar.
 *
 * 2. "shadowSafe" mode (the default whenever a portal container exists and
 *    the caller does not pass `modal`). Radix 1.6.7's MODAL dialog relies on
 *    document-level focus bookkeeping that shadow DOM defeats, because the
 *    browser retargets everything to the outermost shadow host:
 *      - FocusScope reads document.activeElement, which is a HOST, not the
 *        focused button, so its Tab loop never sees "last element" and Tab
 *        walks straight out of the drawer;
 *      - its focusin/focusout trap compares event.target (a host again) and
 *        never records a last-focused element, so it cannot pull focus back;
 *      - auto-focus on open tries every candidate, then lands on the container;
 *        focus-return on close calls host.focus(), which does nothing.
 *    Escape still works (Radix listens on document in the capture phase) and
 *    so does outside-click (the pointer event's React-tree check is unaffected).
 *    So in shadowSafe mode the Root runs with modal={false} — no body
 *    pointer-events lock, no aria-hidden walk, no scroll lock that misreads
 *    retargeted wheel events — and this file supplies the modal behaviour:
 *      - our own overlay: dims the page (desk chrome included), closes on
 *        click, swallows wheel and touch scrolling so the desk does not scroll;
 *      - focus trap: Tab / Shift+Tab wrap inside the drawer, judged with the
 *        active element of the PORTAL's shadow root;
 *      - initial focus on the close button (else the first tabbable, else the
 *        drawer itself);
 *      - focus returns to the opener — typically a card's button in the
 *        dashboard's OTHER shadow root — when focus is lost (the drawer's
 *        nodes were removed) or still inside either of our shadow roots; if
 *        the user has moved on to something else on the desk (e.g. a Frappe
 *        dialog opened from the drawer), focus is never stolen back;
 *      - Escape and overlay click close (Radix's DismissableLayer, kept).
 *    The content gets aria-modal="true" because, to the user, it is modal.
 *    Pass `modal` (true or false) or `shadowSafe={false}` to opt out; with a
 *    real modal (Radix scroll lock active) the content stops wheel/touchmove
 *    propagation, so react-remove-scroll's document listener cannot block
 *    scrolling inside the drawer.
 *
 * 3. Route leave. The portal host lives outside the page container the desk
 *    hides on navigation, so an open sheet closes — without its exit
 *    animation — as soon as the route leaves the dashboard's workspace
 *    (useDismissSignal).
 */

interface SheetMode {
  shadowSafe: boolean
  /** A Radix modal is open, so react-remove-scroll is blocking wheel/touch. */
  scrollLocked: boolean
  /** Closed by a route change: skip the exit animation. */
  instantClose: boolean
  open: boolean
  setOpen: (open: boolean) => void
}

const SheetModeContext = React.createContext<SheetMode>({
  shadowSafe: false,
  scrollLocked: false,
  instantClose: false,
  open: false,
  setOpen: () => {},
})

function Sheet({
  modal,
  shadowSafe: shadowSafeProp,
  open: openProp,
  defaultOpen,
  onOpenChange,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Root> & {
  /** Default: on whenever a portal container exists, unless `modal` is given. */
  shadowSafe?: boolean
}) {
  const portalContainer = usePortalContainer()
  const shadowSafe = shadowSafeProp ?? (portalContainer !== null && modal === undefined)
  const radixModal = shadowSafe ? false : (modal ?? true)

  // The overlay and the focus trap need to know the open state, so the Root is
  // always controlled from here; callers may still use it uncontrolled.
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen ?? false)
  const isControlled = openProp !== undefined
  const open = isControlled ? openProp : uncontrolledOpen
  const setOpen = React.useCallback(
    (next: boolean) => {
      if (!isControlled) setUncontrolledOpen(next)
      onOpenChange?.(next)
    },
    [isControlled, onOpenChange]
  )

  // Close when the route leaves the workspace (see 3. above), with no exit
  // animation; the next open (however it is opened) animates normally again.
  const [instantClose, setInstantClose] = React.useState(false)
  if (open && instantClose) setInstantClose(false)
  const dismissSignal = useDismissSignal()
  const seenSignal = React.useRef(dismissSignal)
  React.useEffect(() => {
    if (dismissSignal === seenSignal.current) return
    seenSignal.current = dismissSignal
    if (!open) return
    setInstantClose(true)
    setOpen(false)
  }, [dismissSignal, open, setOpen])

  const mode = React.useMemo<SheetMode>(
    () => ({ shadowSafe, scrollLocked: radixModal && open, instantClose, open, setOpen }),
    [shadowSafe, radixModal, instantClose, open, setOpen]
  )

  return (
    <SheetModeContext value={mode}>
      <SheetPrimitive.Root
        data-slot="sheet"
        modal={radixModal}
        open={open}
        onOpenChange={setOpen}
        {...props}
      />
    </SheetModeContext>
  )
}

function SheetTrigger({
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Trigger>) {
  return <SheetPrimitive.Trigger data-slot="sheet-trigger" {...props} />
}

function SheetClose({
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Close>) {
  return <SheetPrimitive.Close data-slot="sheet-close" {...props} />
}

function SheetPortal({
  container,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Portal>) {
  const portalContainer = usePortalContainer()
  return (
    <SheetPrimitive.Portal
      data-slot="sheet-portal"
      container={container ?? portalContainer ?? undefined}
      {...props}
    />
  )
}

/** Exit animation off when the sheet was closed by a route change. */
const NO_EXIT_ANIMATION = "data-[state=closed]:animate-none"

function SheetOverlay({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Overlay>) {
  const { instantClose } = React.useContext(SheetModeContext)
  return (
    <SheetPrimitive.Overlay
      data-slot="sheet-overlay"
      className={cn(
        "fixed inset-0 z-50 bg-black/50 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0",
        instantClose && NO_EXIT_ANIMATION,
        className
      )}
      {...props}
    />
  )
}

/** Assign a ref of any shape; returns a callback ref's cleanup, if it gave one. */
function assignRef<T>(ref: React.Ref<T> | undefined, value: T | null): (() => void) | void {
  if (typeof ref === "function") return ref(value)
  if (ref) ref.current = value
}

function preventDefault(event: Event) {
  event.preventDefault()
}

/**
 * The shadowSafe overlay. Radix renders no overlay for a non-modal dialog, so
 * this stands in for it. It sits inside the Portal like Radix's own, which
 * gives it the same Presence-driven exit animation (via the forwarded ref).
 */
function ShadowSafeOverlay({
  ref,
  open,
  instantClose,
  onDismiss,
}: {
  ref?: React.Ref<HTMLDivElement>
  open: boolean
  instantClose: boolean
  onDismiss: () => void
}) {
  const setNode = React.useCallback(
    (node: HTMLDivElement | null) => {
      if (!node) return
      const externalCleanup = assignRef(ref, node)
      // Non-passive, so preventDefault really stops the desk from scrolling.
      node.addEventListener("wheel", preventDefault, { passive: false })
      node.addEventListener("touchmove", preventDefault, { passive: false })
      return () => {
        node.removeEventListener("wheel", preventDefault)
        node.removeEventListener("touchmove", preventDefault)
        if (typeof externalCleanup === "function") externalCleanup()
        else assignRef(ref, null)
      }
    },
    [ref]
  )
  return (
    <div
      ref={setNode}
      data-slot="sheet-overlay"
      data-state={open ? "open" : "closed"}
      aria-hidden="true"
      onClick={onDismiss}
      className={cn(
        "fixed inset-0 z-50 bg-black/50 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0",
        instantClose && NO_EXIT_ANIMATION
      )}
    />
  )
}

const TABBABLE =
  'a[href],area[href],button,input,select,textarea,iframe,summary,audio[controls],video[controls],[contenteditable]:not([contenteditable="false"]),[tabindex]'

/** Keyboard-reachable elements inside `container`, in DOM order. */
function tabbables(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(TABBABLE)).filter((el) => {
    if (el.tabIndex < 0 || el.hidden || el.closest("[inert]")) return false
    if ("disabled" in el && (el as HTMLButtonElement).disabled) return false
    if (el instanceof HTMLInputElement && el.type === "hidden") return false
    return typeof el.checkVisibility === "function"
      ? el.checkVisibility({ checkVisibilityCSS: true })
      : el.getClientRects().length > 0
  })
}

/**
 * The focused element as seen from `node`'s own root: the portal's shadow root
 * for the drawer (ShadowRoot.activeElement is not retargeted to a host when
 * focus is inside that root), the document otherwise.
 */
function activeElementFor(node: Node): Element | null {
  const root = node.getRootNode()
  return root instanceof ShadowRoot || root instanceof Document ? getDeepActiveElement(root) : getDeepActiveElement()
}

function focusElement(el: HTMLElement | null | undefined): boolean {
  if (!el) return false
  el.focus({ preventScroll: true })
  return activeElementFor(el) === el
}

/** True when `active` is (inside) `root`, or is the host of `root`. */
function withinRoot(root: Node | null, active: Element | null): boolean {
  if (!root || !active) return false
  if (root instanceof ShadowRoot && active === root.host) return true
  return root.contains(active)
}

function SheetContent({
  className,
  children,
  side = "right",
  showCloseButton = true,
  onOpenAutoFocus,
  onCloseAutoFocus,
  onKeyDown,
  onWheel,
  onTouchMove,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Content> & {
  side?: "top" | "right" | "bottom" | "left"
  showCloseButton?: boolean
}) {
  const { shadowSafe, scrollLocked, instantClose, open, setOpen } = React.useContext(SheetModeContext)
  const closeButtonRef = React.useRef<HTMLButtonElement>(null)
  const returnFocusRef = React.useRef<HTMLElement | null>(null)
  /** The shadow root (or document) the drawer content renders in. */
  const contentRootRef = React.useRef<Node | null>(null)

  const handleOpenAutoFocus = (event: Event) => {
    // Runs before focus moves, so the deep active element is the opener (a
    // button in the dashboard's shadow root, two shadow levels below the
    // document; getDeepActiveElement follows every level).
    const opener = getDeepActiveElement()
    returnFocusRef.current = opener instanceof HTMLElement ? opener : null
    const content = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
    contentRootRef.current = content ? content.getRootNode() : null
    onOpenAutoFocus?.(event)
    if (event.defaultPrevented) return
    event.preventDefault()
    if (focusElement(closeButtonRef.current)) return
    if (content && focusElement(tabbables(content)[0])) return
    focusElement(content)
  }

  const handleCloseAutoFocus = (event: Event) => {
    onCloseAutoFocus?.(event)
    if (event.defaultPrevented) return
    event.preventDefault()
    const target = returnFocusRef.current
    const contentRoot = contentRootRef.current
    returnFocusRef.current = null
    contentRootRef.current = null
    if (!target || !target.isConnected) return
    const active = getDeepActiveElement()
    const focusLost = !active || active === document.body || active === document.documentElement
    // Still on one of our own surfaces (the drawer's root or the opener's)?
    const onOurs = withinRoot(contentRoot, active) || withinRoot(target.getRootNode(), active)
    if (focusLost || onOurs) target.focus({ preventScroll: true })
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    onKeyDown?.(event)
    if (event.defaultPrevented) return
    if (event.key !== "Tab" || event.altKey || event.ctrlKey || event.metaKey) return
    const container = event.currentTarget
    const items = tabbables(container)
    if (items.length === 0) {
      event.preventDefault() // nothing to move to: keep focus on the drawer
      return
    }
    const first = items[0]
    const last = items[items.length - 1]
    const active = activeElementFor(container)
    const inside = active instanceof Node && container.contains(active)
    if (event.shiftKey && (active === first || active === container || !inside)) {
      event.preventDefault()
      focusElement(last)
    } else if (!event.shiftKey && (active === last || !inside)) {
      event.preventDefault()
      focusElement(first)
    }
  }

  // Only while a real Radix modal holds the scroll lock (not in shadowSafe
  // mode, which has none): keep wheel/touch inside the drawer's React tree so
  // react-remove-scroll's document listener cannot cancel them.
  const handleWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    onWheel?.(event)
    if (scrollLocked) event.stopPropagation()
  }
  const handleTouchMove = (event: React.TouchEvent<HTMLDivElement>) => {
    onTouchMove?.(event)
    if (scrollLocked) event.stopPropagation()
  }

  return (
    <SheetPortal>
      {shadowSafe ? (
        <ShadowSafeOverlay open={open} instantClose={instantClose} onDismiss={() => setOpen(false)} />
      ) : (
        <SheetOverlay />
      )}
      <SheetPrimitive.Content
        data-slot="sheet-content"
        aria-modal={shadowSafe ? true : undefined}
        onOpenAutoFocus={shadowSafe ? handleOpenAutoFocus : onOpenAutoFocus}
        onCloseAutoFocus={shadowSafe ? handleCloseAutoFocus : onCloseAutoFocus}
        onKeyDown={shadowSafe ? handleKeyDown : onKeyDown}
        onWheel={scrollLocked || onWheel ? handleWheel : undefined}
        onTouchMove={scrollLocked || onTouchMove ? handleTouchMove : undefined}
        className={cn(
          "fixed z-50 flex flex-col gap-4 bg-background shadow-lg transition ease-in-out data-[state=closed]:animate-out data-[state=closed]:duration-300 data-[state=open]:animate-in data-[state=open]:duration-500",
          shadowSafe && "overscroll-contain",
          side === "right" &&
            "inset-y-0 right-0 h-full w-3/4 border-l data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right sm:max-w-sm",
          side === "left" &&
            "inset-y-0 left-0 h-full w-3/4 border-r data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left sm:max-w-sm",
          side === "top" &&
            "inset-x-0 top-0 h-auto border-b data-[state=closed]:slide-out-to-top data-[state=open]:slide-in-from-top",
          side === "bottom" &&
            "inset-x-0 bottom-0 h-auto border-t data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom",
          className,
          // Last, so it beats any exit animation the caller adds.
          instantClose && NO_EXIT_ANIMATION
        )}
        {...props}
      >
        {children}
        {showCloseButton && (
          <SheetPrimitive.Close
            ref={closeButtonRef}
            className="absolute top-4 right-4 rounded-xs opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:outline-hidden disabled:pointer-events-none data-[state=open]:bg-secondary"
          >
            <XIcon className="size-4" />
            <span className="sr-only">Close</span>
          </SheetPrimitive.Close>
        )}
      </SheetPrimitive.Content>
    </SheetPortal>
  )
}

function SheetHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sheet-header"
      className={cn("flex flex-col gap-1.5 p-4", className)}
      {...props}
    />
  )
}

function SheetFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sheet-footer"
      className={cn("mt-auto flex flex-col gap-2 p-4", className)}
      {...props}
    />
  )
}

function SheetTitle({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Title>) {
  return (
    <SheetPrimitive.Title
      data-slot="sheet-title"
      className={cn("font-semibold text-foreground", className)}
      {...props}
    />
  )
}

function SheetDescription({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Description>) {
  return (
    <SheetPrimitive.Description
      data-slot="sheet-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

export {
  Sheet,
  SheetTrigger,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetFooter,
  SheetTitle,
  SheetDescription,
}
