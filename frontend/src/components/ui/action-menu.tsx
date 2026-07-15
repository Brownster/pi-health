import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { EllipsisVertical, Loader2, type LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type DataAttributes = Record<`data-${string}`, string>;

export interface ActionMenuItem {
  id: string;
  label: string;
  Icon: LucideIcon;
  onSelect: () => void;
  data?: DataAttributes;
  disabled?: boolean;
  separatorBefore?: boolean;
  tone?: "default" | "info" | "danger";
}

export function ActionMenu({
  label,
  items,
  disabled = false,
  pending = false,
  triggerData,
  menuData,
}: {
  label: string;
  items: ActionMenuItem[];
  disabled?: boolean;
  pending?: boolean;
  triggerData?: DataAttributes;
  menuData?: DataAttributes;
}) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const positionMenu = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const menuWidth = 192;
    const menuHeight = menuRef.current?.offsetHeight ?? 142;
    const below = rect.bottom + 8;
    setPosition({
      left: Math.min(
        window.innerWidth - menuWidth - 8,
        Math.max(8, rect.right - menuWidth),
      ),
      top:
        below + menuHeight <= window.innerHeight - 8
          ? below
          : Math.max(8, rect.top - menuHeight - 8),
    });
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    positionMenu();
    menuRef.current?.querySelector<HTMLButtonElement>("[role='menuitem']")?.focus();
  }, [open, positionMenu]);

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        !rootRef.current?.contains(target) &&
        !menuRef.current?.contains(target)
      ) {
        setOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", positionMenu);
    window.addEventListener("scroll", positionMenu, true);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", positionMenu);
      window.removeEventListener("scroll", positionMenu, true);
    };
  }, [open, positionMenu]);

  return (
    <div className="relative" ref={rootRef}>
      <Button
        {...triggerData}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={label}
        className="h-9 min-h-9 w-9 px-0"
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key !== "ArrowDown") return;
          event.preventDefault();
          setOpen(true);
        }}
        ref={triggerRef}
        size="sm"
        title={label}
        variant="outline"
      >
        {pending ? (
          <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
        ) : (
          <EllipsisVertical aria-hidden="true" className="h-4 w-4" />
        )}
      </Button>
      {open
        ? createPortal(
            <div
              {...menuData}
              aria-label={label}
              className="fixed z-50 w-48 overflow-hidden rounded-md border border-border bg-card p-1 shadow-xl shadow-black/30"
              onBlur={(event) => {
                const next = event.relatedTarget as Node | null;
                if (
                  next &&
                  (menuRef.current?.contains(next) ||
                    triggerRef.current?.contains(next))
                ) {
                  return;
                }
                setOpen(false);
              }}
              onKeyDown={(event) => {
                if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
                event.preventDefault();
                const menuItems = Array.from(
                  menuRef.current?.querySelectorAll<HTMLButtonElement>(
                    "[role='menuitem']:not(:disabled)",
                  ) ?? [],
                );
                const current = menuItems.indexOf(
                  document.activeElement as HTMLButtonElement,
                );
                const offset = event.key === "ArrowDown" ? 1 : -1;
                menuItems[
                  (current + offset + menuItems.length) % menuItems.length
                ]?.focus();
              }}
              ref={menuRef}
              role="menu"
              style={{ left: position.left, top: position.top }}
            >
              {items.map((item) => (
                <div key={item.id}>
                  {item.separatorBefore ? (
                    <div
                      className="my-1 border-t border-divider"
                      role="separator"
                    />
                  ) : null}
                  <button
                    {...item.data}
                    className={cn(
                      "flex min-h-10 w-full items-center gap-2 rounded-sm px-3 text-left text-sm hover:bg-muted focus-visible:bg-muted focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
                      item.tone === "info"
                        ? "text-info"
                        : item.tone === "danger"
                          ? "text-danger"
                          : "text-foreground",
                    )}
                    disabled={item.disabled}
                    onClick={() => {
                      setOpen(false);
                      item.onSelect();
                    }}
                    role="menuitem"
                    type="button"
                  >
                    <item.Icon
                      aria-hidden="true"
                      className={cn(
                        "h-4 w-4",
                        item.tone ? "" : "text-muted-foreground",
                      )}
                    />
                    {item.label}
                  </button>
                </div>
              ))}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
