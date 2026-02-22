import type { PropsWithChildren } from "react";
import { NavLink } from "react-router-dom";

import { navRoutes } from "@/app/routes";
import { useAuth } from "@/components/auth/auth-provider";
import { ThemeModeToggle } from "@/components/theme/theme-mode-toggle";
import { cn } from "@/lib/utils";

export function AppShell({ children }: PropsWithChildren) {
  const { state, username } = useAuth();

  return (
    <div className="relative min-h-screen overflow-x-hidden bg-background text-foreground">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(circle_at_top,#17a6d41a_0%,transparent_40%),linear-gradient(180deg,transparent,#0f172a08)]"
      />

      <header className="sticky top-0 z-50 border-b border-border/70 bg-background/90 backdrop-blur-md">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-3 py-3 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                Pi-Health
              </p>
              <h1 className="truncate text-lg font-semibold tracking-tight sm:text-xl">
                Pi-Health v2 Shell
              </h1>
            </div>
            <span className="rounded-full border border-border bg-muted/60 px-2 py-1 text-xs text-muted-foreground">
              /v2
            </span>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <nav aria-label="Primary" className="flex flex-wrap items-center gap-2">
              {navRoutes.map((route) => (
                <NavLink
                  key={route.path}
                  className={({ isActive }) =>
                    cn(
                      "inline-flex min-h-11 items-center rounded-md border border-border/70 px-3 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-primary text-primary-foreground"
                        : "bg-background hover:bg-muted",
                    )
                  }
                  to={route.path}
                >
                  {route.label}
                </NavLink>
              ))}
            </nav>
            {state === "authenticated" && (
              <span className="inline-flex min-h-11 items-center rounded-md border border-border/70 bg-muted/70 px-3 text-sm text-muted-foreground">
                Signed in as {username || "unknown"}
              </span>
            )}
            <ThemeModeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl p-3 pb-8 sm:p-6">{children}</main>
    </div>
  );
}
