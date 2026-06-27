import { useEffect, useRef, type ReactNode } from "react";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

/**
 * Accessible modal backdrop: moves focus into the dialog, traps Tab/Shift+Tab,
 * closes on Escape or backdrop click, locks body scroll, and restores focus to
 * the triggering control on close (StrictMode-safe).
 */
export function ModalOverlay({
  onClose,
  children,
}: {
  onClose: () => void;
  children: ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const node = containerRef.current;
    // Capture the control to restore focus to on close. Only treat focus that is
    // currently *outside* the dialog as the trigger, which guards against React 18
    // StrictMode's mount->unmount->mount double-invoke.
    const active = document.activeElement as HTMLElement | null;
    const triggerEl = node && active && !node.contains(active) ? active : null;

    const focusables = node
      ? Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
      : [];
    (focusables[0] ?? node)?.focus();

    // Lock body scroll while the dialog is open (prevents scroll-behind on mobile).
    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !node) {
        return;
      }
      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (!items.length) {
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const current = document.activeElement;
      if (event.shiftKey && current === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && current === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = previousBodyOverflow;
      triggerEl?.focus?.();
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/75 p-3 sm:p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onCloseRef.current();
        }
      }}
      ref={containerRef}
      tabIndex={-1}
    >
      {children}
    </div>
  );
}
