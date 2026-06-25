import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Layers, RefreshCw, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { type StackSummary, fetchStacks, getStackServicesPercent } from "@/lib/stacks";
import { formatClockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 10_000;

function getStatusTone(status: string): string {
  switch (status) {
    case "running":
      return "bg-emerald-500/15 text-emerald-300 border-emerald-500/40";
    case "stopped":
    case "exited":
      return "bg-rose-500/15 text-rose-300 border-rose-500/40";
    case "partial":
      return "bg-amber-500/15 text-amber-300 border-amber-500/40";
    default:
      return "bg-slate-500/15 text-slate-300 border-slate-500/40";
  }
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Unable to load stacks";
}

function StackCard({ stack }: { stack: StackSummary }) {
  const percent = getStackServicesPercent(stack);
  const running = stack.running_count ?? "—";
  const total = stack.container_count ?? "—";

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{stack.name}</p>
            {stack.compose_file ? (
              <p className="truncate text-xs text-muted-foreground">{stack.compose_file}</p>
            ) : null}
          </div>
          <span
            className={cn(
              "shrink-0 rounded-full border px-2 py-1 text-xs font-medium capitalize",
              getStatusTone(stack.status),
            )}
          >
            {stack.status}
          </span>
        </div>

        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">
            {running} / {total} services up
          </p>
          <div className="h-1.5 rounded-full bg-muted">
            <div
              className="h-1.5 rounded-full bg-emerald-500 transition-[width] duration-300"
              style={{ width: `${percent ?? 0}%` }}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function StacksPage() {
  const [stacks, setStacks] = useState<StackSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const isMountedRef = useRef(true);

  const loadStacks = useCallback(async (reason: "initial" | "manual" | "poll") => {
    if (reason === "initial") {
      setIsLoading(true);
    }
    if (reason === "manual") {
      setIsRefreshing(true);
    }

    try {
      const next = await fetchStacks({ includeStatus: true });
      if (!isMountedRef.current) {
        return;
      }
      setStacks(next);
      setError(null);
      setLastUpdated(formatClockTime(new Date()));
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }
      setError(getErrorMessage(caughtError));
    } finally {
      if (isMountedRef.current) {
        if (reason === "initial") {
          setIsLoading(false);
        }
        if (reason === "manual") {
          setIsRefreshing(false);
        }
      }
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    void loadStacks("initial");

    const intervalId = window.setInterval(() => {
      void loadStacks("poll");
    }, POLL_INTERVAL_MS);

    return () => {
      isMountedRef.current = false;
      window.clearInterval(intervalId);
    };
  }, [loadStacks]);

  return (
    <section className="space-y-4 sm:space-y-6">
      <Card>
        <CardHeader className="space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 space-y-1">
              <CardTitle className="flex items-center gap-2 text-lg sm:text-xl">
                <Layers aria-hidden="true" className="h-5 w-5 text-primary" />
                Docker Stacks
              </CardTitle>
              <CardDescription>Compose stacks discovered on the host.</CardDescription>
            </div>
            <span className="inline-flex min-h-11 items-center rounded-md border border-border bg-muted/70 px-3 text-xs text-muted-foreground">
              Last updated: {lastUpdated}
            </span>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              className="gap-2"
              disabled={isRefreshing}
              onClick={() => void loadStacks("manual")}
              variant="outline"
            >
              <RefreshCw aria-hidden="true" className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")} />
              {isRefreshing ? "Refreshing" : "Refresh"}
            </Button>
          </div>
        </CardHeader>
      </Card>

      {error && !stacks.length ? (
        <Card className="border-rose-500/40">
          <CardContent className="flex flex-col items-start gap-3 p-4 sm:p-6">
            <div className="flex items-center gap-2 text-rose-300">
              <TriangleAlert aria-hidden="true" className="h-4 w-4" />
              <p className="text-sm font-medium">Unable to load stacks</p>
            </div>
            <p className="text-sm text-muted-foreground">{error}</p>
            <Button onClick={() => void loadStacks("manual")} variant="outline">
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {error && stacks.length ? (
        <Card aria-live="polite" className="border-amber-500/40" role="status">
          <CardContent className="flex items-center gap-2 p-4 text-sm text-amber-300">
            <TriangleAlert aria-hidden="true" className="h-4 w-4" />
            Refresh failed: {error}
          </CardContent>
        </Card>
      ) : null}

      {isLoading ? (
        <Card aria-live="polite" role="status">
          <CardContent className="flex min-h-[14rem] items-center justify-center gap-2 p-6 text-sm text-muted-foreground">
            <Activity aria-hidden="true" className="h-4 w-4 animate-pulse text-primary" />
            Loading stacks...
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && !error && !stacks.length ? (
        <Card>
          <CardContent className="flex min-h-[10rem] items-center justify-center p-6 text-sm text-muted-foreground">
            No stacks found.
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && stacks.length ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {stacks.map((stack) => (
            <StackCard key={stack.name} stack={stack} />
          ))}
        </div>
      ) : null}
    </section>
  );
}
