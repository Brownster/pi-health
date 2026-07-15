import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { type LiveRefreshInterval, useLiveRefresh } from "@/lib/live-refresh";
import { cn } from "@/lib/utils";

export function RefreshControls({
  isRefreshing,
  onRefresh,
}: {
  isRefreshing: boolean;
  onRefresh: () => void;
}) {
  const { preference, setEnabled, setIntervalSeconds } = useLiveRefresh(onRefresh);

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <div className="flex min-h-9 items-center gap-2 rounded-md border border-border bg-card px-2">
        <span className="font-mono text-[11px] text-muted-foreground">auto</span>
        <button
          aria-checked={preference.enabled}
          aria-label="Auto refresh"
          className={cn(
            "relative h-5 w-9 cursor-pointer rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            preference.enabled ? "border-primary/50 bg-primary/25" : "border-[#303a47] bg-muted",
          )}
          onClick={() => setEnabled(!preference.enabled)}
          role="switch"
          type="button"
        >
          <span
            aria-hidden="true"
            className={cn(
              "absolute top-0.5 h-3.5 w-3.5 rounded-full transition-transform",
              preference.enabled ? "translate-x-[17px] bg-primary" : "translate-x-0.5 bg-muted-foreground",
            )}
          />
        </button>
      </div>

      <div aria-label="Auto refresh interval" className="flex rounded-md border border-border bg-card p-0.5" role="group">
        {([30, 60] as LiveRefreshInterval[]).map((seconds) => (
          <button
            aria-pressed={preference.intervalSeconds === seconds}
            className={cn(
              "min-h-8 min-w-11 cursor-pointer rounded px-2 font-mono text-[11px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-40",
              preference.intervalSeconds === seconds
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
            disabled={!preference.enabled}
            key={seconds}
            onClick={() => setIntervalSeconds(seconds)}
            type="button"
          >
            {seconds}s
          </button>
        ))}
      </div>

      <Button
        aria-label="Refresh now"
        className="min-h-9 w-10 px-0"
        disabled={isRefreshing}
        onClick={onRefresh}
        size="sm"
        title="Refresh now"
        variant="secondary"
      >
        <RefreshCw aria-hidden="true" className={cn("h-4 w-4", isRefreshing && "animate-spin")} />
      </Button>
    </div>
  );
}
