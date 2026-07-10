import { useEffect, useRef, useState, type ComponentType, type PropsWithChildren } from "react";
import {
  Boxes,
  Container,
  Database,
  FolderTree,
  Gauge,
  HardDrive,
  LogOut,
  PlugZap,
  Menu,
  PackageOpen,
  Settings,
  Share2,
  X,
  type LucideProps,
} from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";

import { navRoutes } from "@/app/routes";
import { useAuth } from "@/components/auth/auth-provider";
import { logoutToLogin } from "@/lib/auth";
import { cn } from "@/lib/utils";

const groupOrder = ["Main", "My Apps", "Storage", "System"] as const;
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

const routeIcons: Record<string, ComponentType<LucideProps>> = {
  "/": Gauge,
  "/containers": Container,
  "/stacks": Boxes,
  "/disks": HardDrive,
  "/plugins": PackageOpen,
  "/pools": Database,
  "/mounts": FolderTree,
  "/shares": Share2,
  "/integrations": PlugZap,
  "/settings": Settings,
};

function Brand() {
  return (
    <div className="flex min-w-0 items-center gap-3" data-testid="lime-os-brand">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary font-mono text-sm font-bold text-primary-foreground">
        L
      </span>
      <span className="truncate font-mono text-[15px] font-semibold text-foreground">
        lime<span className="text-primary">os</span>
      </span>
    </div>
  );
}

export function AppShell({ children }: PropsWithChildren) {
  const { state, username } = useAuth();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const backgroundRef = useRef<HTMLDivElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const drawerCloseRef = useRef<HTMLButtonElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    backgroundRef.current?.toggleAttribute("inert", drawerOpen);
  }, [drawerOpen]);

  useEffect(() => {
    if (!drawerOpen) {
      return undefined;
    }

    const drawer = drawerRef.current;
    const trigger = menuButtonRef.current;
    const previousOverflow = document.body.style.overflow;
    const previousBodyOverscroll = document.body.style.overscrollBehavior;
    const previousRootOverscroll = document.documentElement.style.overscrollBehavior;
    const focusFrame = window.requestAnimationFrame(() => {
      (drawerCloseRef.current ?? drawer)?.focus();
    });
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setDrawerOpen(false);
        return;
      }
      if (event.key !== "Tab" || !drawer) {
        return;
      }

      const focusables = Array.from(drawer.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (!focusables.length) {
        event.preventDefault();
        drawer.focus();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !drawer.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !drawer.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };

    document.body.style.overflow = "hidden";
    document.body.style.overscrollBehavior = "none";
    document.documentElement.style.overscrollBehavior = "none";
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      document.body.style.overscrollBehavior = previousBodyOverscroll;
      document.documentElement.style.overscrollBehavior = previousRootOverscroll;
      document.removeEventListener("keydown", onKeyDown, true);
      window.requestAnimationFrame(() => {
        if (trigger?.isConnected) {
          trigger.focus();
        }
      });
    };
  }, [drawerOpen]);

  useEffect(() => {
    const desktopQuery = window.matchMedia("(min-width: 980px)");
    const closeDrawerOnDesktop = (event: MediaQueryListEvent) => {
      if (event.matches) {
        setDrawerOpen(false);
      }
    };
    desktopQuery.addEventListener("change", closeDrawerOnDesktop);
    return () => desktopQuery.removeEventListener("change", closeDrawerOnDesktop);
  }, []);

  const sidebar = (
    <div className="flex h-full flex-col bg-sidebar">
      <div className="flex h-[72px] items-center border-b border-divider px-5">
        <Brand />
      </div>

      <nav aria-label="Primary" className="flex-1 overflow-y-auto px-3 py-4">
        {groupOrder.map((group) => {
          const routes = navRoutes.filter((route) => route.navGroup === group);
          if (!routes.length) {
            return null;
          }

          return (
            <div className="mb-4 last:mb-0" key={group}>
              <p className="px-3 pb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-dim">
                {group}
              </p>
              <div className="space-y-1">
                {routes.map((route) => {
                  const Icon = routeIcons[route.path] ?? Gauge;
                  return (
                    <NavLink
                      className={({ isActive }) =>
                        cn(
                          "flex min-h-11 cursor-pointer items-center gap-3 rounded-md border border-transparent px-3 font-mono text-[13px] text-muted-foreground transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          isActive
                            ? "border-primary/15 bg-primary/10 text-primary"
                            : "hover:bg-muted/70 hover:text-foreground",
                        )
                      }
                      end={route.path === "/"}
                      key={route.path}
                      to={route.path}
                    >
                      <Icon aria-hidden="true" className="h-[18px] w-[18px] shrink-0" strokeWidth={1.7} />
                      <span>{route.label}</span>
                    </NavLink>
                  );
                })}
              </div>
            </div>
          );
        })}
      </nav>

      <div className="border-t border-divider p-3">
        {state === "authenticated" ? (
          <div className="flex min-h-14 items-center gap-3 rounded-md px-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border bg-muted font-mono text-sm font-semibold text-primary">
              {(username || "U").charAt(0).toUpperCase()}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-foreground">{username || "unknown"}</p>
              <p className="font-mono text-[11px] text-dim">admin</p>
            </div>
            <button
              aria-label="Sign out"
              className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => void logoutToLogin()}
              title="Sign out"
              type="button"
            >
              <LogOut aria-hidden="true" className="h-[18px] w-[18px]" />
            </button>
          </div>
        ) : (
          <p className="px-3 py-4 font-mono text-xs text-dim">session: {state}</p>
        )}
      </div>
    </div>
  );

  return (
    <div className="min-h-screen overflow-x-hidden bg-background text-foreground">
      <div
        aria-hidden={drawerOpen ? "true" : undefined}
        id="lime-os-app-background"
        ref={backgroundRef}
      >
        <a
          className="sr-only fixed left-3 top-3 z-[80] rounded-md bg-primary px-4 py-3 font-mono text-sm font-semibold text-primary-foreground focus:not-sr-only focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background"
          href="#lime-os-main-content"
        >
          Skip to main content
        </a>

        <aside className="fixed inset-y-0 left-0 z-40 hidden w-[248px] border-r border-divider min-[980px]:block">
          {sidebar}
        </aside>

        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-divider bg-sidebar px-4 min-[980px]:hidden">
          <Brand />
          <button
            aria-controls="lime-os-mobile-navigation"
            aria-expanded={drawerOpen}
            aria-label="Open navigation"
            className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => setDrawerOpen(true)}
            ref={menuButtonRef}
            type="button"
          >
            <Menu aria-hidden="true" className="h-5 w-5" />
          </button>
        </header>

        <main
          className="w-full px-4 py-5 focus:outline-none sm:px-6 sm:py-7 min-[980px]:ml-[248px] min-[980px]:w-[calc(100%-248px)] min-[980px]:px-8 min-[980px]:py-8 xl:px-10"
          id="lime-os-main-content"
          tabIndex={-1}
        >
          <div className="mx-auto w-full max-w-[1440px]">{children}</div>
        </main>
      </div>

      {drawerOpen && (
        <div className="fixed inset-0 z-50 overscroll-none min-[980px]:hidden">
          <div
            aria-hidden="true"
            className="absolute inset-0 bg-black/70"
            onClick={() => setDrawerOpen(false)}
          />
          <aside
            aria-label="Navigation"
            aria-modal="true"
            className="absolute inset-y-0 left-0 w-[min(86vw,300px)] overscroll-contain border-r border-divider shadow-2xl"
            id="lime-os-mobile-navigation"
            ref={drawerRef}
            role="dialog"
            tabIndex={-1}
          >
            <button
              aria-label="Close navigation"
              className="absolute right-3 top-3 flex h-11 w-11 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => setDrawerOpen(false)}
              ref={drawerCloseRef}
              type="button"
            >
              <X aria-hidden="true" className="h-5 w-5" />
            </button>
            {sidebar}
          </aside>
        </div>
      )}
    </div>
  );
}
