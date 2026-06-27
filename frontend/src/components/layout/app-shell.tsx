import { useEffect, useState, type ComponentType, type PropsWithChildren } from "react";
import {
  Boxes,
  Container,
  Database,
  FolderTree,
  Gauge,
  HardDrive,
  LogOut,
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

const routeIcons: Record<string, ComponentType<LucideProps>> = {
  "/": Gauge,
  "/containers": Container,
  "/stacks": Boxes,
  "/disks": HardDrive,
  "/plugins": PackageOpen,
  "/pools": Database,
  "/mounts": FolderTree,
  "/shares": Share2,
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

  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!drawerOpen) {
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDrawerOpen(false);
      }
    };

    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [drawerOpen]);

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
          type="button"
        >
          <Menu aria-hidden="true" className="h-5 w-5" />
        </button>
      </header>

      {drawerOpen && (
        <div className="fixed inset-0 z-50 min-[980px]:hidden">
          <button
            aria-label="Close navigation"
            className="absolute inset-0 cursor-default bg-black/70"
            onClick={() => setDrawerOpen(false)}
            type="button"
          />
          <aside
            className="absolute inset-y-0 left-0 w-[min(86vw,300px)] border-r border-divider shadow-2xl"
            id="lime-os-mobile-navigation"
          >
            {sidebar}
            <button
              aria-label="Close navigation"
              className="absolute right-3 top-3 flex h-11 w-11 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => setDrawerOpen(false)}
              type="button"
            >
              <X aria-hidden="true" className="h-5 w-5" />
            </button>
          </aside>
        </div>
      )}

      <main className="w-full px-4 py-5 sm:px-6 sm:py-7 min-[980px]:ml-[248px] min-[980px]:w-[calc(100%-248px)] min-[980px]:px-8 min-[980px]:py-8 xl:px-10">
        <div className="mx-auto w-full max-w-[1440px]">{children}</div>
      </main>
    </div>
  );
}
