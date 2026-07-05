import { HardDrive, Settings2, ShieldCheck } from "lucide-react";

import { StatusBadge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { relativeAge, snapraidView, type SnapraidState } from "@/lib/pools";
import { type PluginDetail, type StoragePlugin } from "@/lib/storage-plugins";

const STATE_BADGE: Record<SnapraidState, { label: string; tone: BadgeProps["tone"] }> = {
  healthy: { label: "protected", tone: "success" },
  sync_required: { label: "sync required", tone: "warning" },
  error: { label: "error", tone: "danger" },
  unconfigured: { label: "not set up", tone: "neutral" },
};

const SUMMARY_ORDER = ["added", "removed", "updated", "moved", "copied", "restored"];

export function SnapraidCard({
  plugin,
  detail,
  loading,
  onDetails,
  onSetup,
}: {
  plugin: StoragePlugin;
  detail: PluginDetail | null;
  loading: boolean;
  onDetails: (plugin: StoragePlugin) => void;
  onSetup: (plugin: StoragePlugin) => void;
}) {
  const view = snapraidView(detail);
  const badge = STATE_BADGE[view.state];
  const lastAge = relativeAge(view.lastRunAt);
  const summaryEntries = view.lastSummary
    ? SUMMARY_ORDER.filter((key) => key in view.lastSummary!).map(
        (key) => [key, view.lastSummary![key]] as const,
      )
    : [];

  return (
    <Card className="transition-colors duration-200 hover:border-primary/25" data-pool-plugin="snapraid">
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <ShieldCheck aria-hidden="true" className="h-4 w-4 shrink-0 text-primary" />
            <p className="truncate text-sm font-semibold">{plugin.name}</p>
          </div>
          <StatusBadge className="shrink-0" label={loading ? "loading" : badge.label} tone={badge.tone} />
        </div>

        {view.state === "unconfigured" ? (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              Assign data and parity drives to start protecting your files.
            </p>
            <Button
              className="gap-2"
              data-pool-action="setup"
              data-plugin="snapraid"
              onClick={() => onSetup(plugin)}
              size="sm"
            >
              <Settings2 aria-hidden="true" className="h-4 w-4" />
              Set up
            </Button>
          </div>
        ) : (
          <>
            <dl className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <dt className="text-muted-foreground">Data drives</dt>
                <dd className="font-medium tabular-nums">{view.dataDrives ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Parity drives</dt>
                <dd className="font-medium tabular-nums">{view.parityDrives ?? "—"}</dd>
              </div>
            </dl>

            {view.lastCommand || lastAge ? (
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <HardDrive aria-hidden="true" className="h-3.5 w-3.5" />
                Last {view.lastCommand ?? "run"}
                {lastAge ? ` · ${lastAge}` : ""}
              </p>
            ) : null}

            {summaryEntries.length ? (
              <ul className="flex flex-wrap gap-1.5" data-pool-summary="snapraid">
                {summaryEntries.map(([key, value]) => (
                  <li
                    className="rounded-full bg-muted px-2 py-0.5 text-[0.7rem] text-muted-foreground"
                    key={key}
                  >
                    {value} {key}
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        )}

        <div className="flex justify-end pt-1">
          <Button
            data-pool-action="details"
            data-plugin="snapraid"
            onClick={() => onDetails(plugin)}
            size="sm"
            variant="outline"
          >
            Details
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
