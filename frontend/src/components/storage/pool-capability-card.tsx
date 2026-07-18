import { FolderTree, Settings2 } from "lucide-react";
import { Link } from "react-router-dom";

import { poolProviderPath } from "@/app/route-contract";
import { StatusBadge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { MetricBar } from "@/components/ui/metric-bar";
import { formatBytes } from "@/lib/format";
import type { PoolView } from "@/lib/pool-capabilities";
import { cn } from "@/lib/utils";

export function PoolCapabilityCard({ pool }: { pool: PoolView }) {
  const usedBytes = pool.totalBytes !== null && pool.freeBytes !== null
    ? pool.totalBytes - pool.freeBytes
    : null;
  const usageTone = pool.usedPercent !== null && pool.usedPercent >= 90
    ? "danger"
    : "primary";

  return (
    <Card
      className={cn(
        "transition-colors hover:border-primary/25",
        !pool.mounted && "border-warning/30 bg-warning/5",
      )}
      data-pool-card={pool.name}
      data-pool-provider={pool.providerId}
    >
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <FolderTree aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <div className="min-w-0">
              <h2 className="truncate text-sm font-semibold">{pool.name}</h2>
              <p className="mt-0.5 truncate font-mono text-[11px] text-dim">
                {pool.mountPoint ?? "Mount point not reported"}
              </p>
            </div>
          </div>
          <StatusBadge
            label={pool.mounted ? "mounted" : "unmounted"}
            tone={pool.mounted ? "success" : "warning"}
          />
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-y border-border py-3 text-xs">
          <div>
            <dt className="font-mono text-[10px] uppercase text-dim">Branches</dt>
            <dd className="mt-1 text-foreground">{pool.branchCount ?? "Not reported"}</dd>
          </div>
          <div>
            <dt className="font-mono text-[10px] uppercase text-dim">Policy</dt>
            <dd className="mt-1 truncate text-foreground">{pool.policy ?? "Provider default"}</dd>
          </div>
        </dl>

        {pool.usedPercent !== null ? (
          <div className="space-y-1.5">
            <MetricBar label={`${pool.name} capacity`} tone={usageTone} value={pool.usedPercent} />
            <p className="font-mono text-[11px] tabular-nums text-dim">
              {usedBytes !== null && pool.totalBytes !== null
                ? `${formatBytes(usedBytes)} / ${formatBytes(pool.totalBytes)}`
                : `${Math.round(pool.usedPercent)}% used`}
            </p>
          </div>
        ) : null}

        <div className="flex items-end justify-between gap-3 pt-1">
          <div className="min-w-0">
            <p className="font-mono text-[10px] uppercase text-dim">Provider</p>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">{pool.providerName}</p>
          </div>
          <Link
            aria-label={`Manage ${pool.name}`}
            className={cn(buttonVariants({ size: "sm", variant: "outline" }), "gap-2")}
            to={poolProviderPath(pool.providerId)}
          >
            <Settings2 aria-hidden="true" className="h-3.5 w-3.5" />
            Manage
          </Link>
        </div>
        {pool.recentAction ? (
          <p className="truncate border-t border-border pt-3 text-xs text-dim" title={pool.recentAction}>
            {pool.recentAction}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
