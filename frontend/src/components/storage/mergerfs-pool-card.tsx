import { FolderTree, Settings2 } from "lucide-react";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { MetricBar } from "@/components/ui/metric-bar";
import { formatBytes } from "@/lib/format";
import { type MergerfsPoolView } from "@/lib/pools";
import { type StoragePlugin } from "@/lib/storage-plugins";
import { cn } from "@/lib/utils";

export function MergerfsPoolCard({
  plugin,
  pool,
  onDetails,
}: {
  plugin: StoragePlugin;
  pool: MergerfsPoolView;
  onDetails: (plugin: StoragePlugin) => void;
}) {
  const capacityTone = pool.usedPercent != null && pool.usedPercent >= 90 ? "danger" : "primary";
  const used = formatBytes(pool.totalBytes != null && pool.freeBytes != null ? pool.totalBytes - pool.freeBytes : null);
  const total = formatBytes(pool.totalBytes);

  return (
    <Card
      className={cn(
        "transition-colors duration-200 hover:border-primary/25",
        pool.mounted ? "" : "border-warning/30 bg-warning/5",
      )}
      data-pool-card={pool.name}
      data-pool-plugin="mergerfs"
    >
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <FolderTree aria-hidden="true" className="h-4 w-4 shrink-0 text-primary" />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{pool.name}</p>
              {pool.mountPoint ? (
                <p className="truncate text-xs text-muted-foreground">{pool.mountPoint}</p>
              ) : null}
            </div>
          </div>
          <StatusBadge
            className="shrink-0"
            label={pool.mounted ? "mounted" : "unmounted"}
            tone={pool.mounted ? "success" : "warning"}
          />
        </div>

        <p className="text-xs text-muted-foreground">
          {pool.branchCount} branch{pool.branchCount === 1 ? "" : "es"}
        </p>

        {pool.mounted && pool.usedPercent != null ? (
          <div className="space-y-1">
            <MetricBar label={`${pool.name} capacity`} tone={capacityTone} value={pool.usedPercent} />
            <p className="text-[0.7rem] text-muted-foreground tabular-nums">
              {used && total ? `${used} / ${total}` : `${Math.round(pool.usedPercent)}% used`}
            </p>
          </div>
        ) : null}

        <div className="flex justify-end pt-1">
          <Button
            data-pool-action="details"
            data-plugin="mergerfs"
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

export function MergerfsSetupCard({
  plugin,
  onSetup,
  onDetails,
}: {
  plugin: StoragePlugin;
  onSetup: (plugin: StoragePlugin) => void;
  onDetails: (plugin: StoragePlugin) => void;
}) {
  return (
    <Card data-pool-plugin="mergerfs" data-pool-card="__setup__">
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <FolderTree aria-hidden="true" className="h-4 w-4 shrink-0 text-primary" />
            <p className="truncate text-sm font-semibold">{plugin.name}</p>
          </div>
          <StatusBadge className="shrink-0" label="not set up" tone="neutral" />
        </div>
        <p className="text-xs text-muted-foreground">
          Combine multiple disks into one pool. Add a pool to get started.
        </p>
        <div className="flex justify-between pt-1">
          <Button
            className="gap-2"
            data-pool-action="setup"
            data-plugin="mergerfs"
            onClick={() => onSetup(plugin)}
            size="sm"
          >
            <Settings2 aria-hidden="true" className="h-4 w-4" />
            Set up
          </Button>
          <Button
            data-pool-action="details"
            data-plugin="mergerfs"
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
