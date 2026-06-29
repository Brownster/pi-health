import {
  Archive,
  Download,
  FileText,
  Loader2,
  Pencil,
  Play,
  RotateCw,
  Square,
} from "lucide-react";

import { StatusBadge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { MetricBar } from "@/components/ui/metric-bar";
import {
  type StackAction,
  type StackSummary,
  getStackServicesPercent,
} from "@/lib/stacks";
import { cn } from "@/lib/utils";

export const STACK_ACTION_ORDER: StackAction[] = [
  "up",
  "down",
  "restart",
  "pull",
];
export const STACK_ACTION_META: Record<
  StackAction,
  { label: string; pendingLabel: string; className: string; Icon: typeof Play }
> = {
  up: {
    label: "Start",
    pendingLabel: "Starting...",
    className:
      "border-success/30 bg-success/10 text-success hover:bg-success/15",
    Icon: Play,
  },
  down: {
    label: "Stop",
    pendingLabel: "Stopping...",
    className: "border-danger/30 bg-danger/10 text-danger hover:bg-danger/15",
    Icon: Square,
  },
  restart: {
    label: "Restart",
    pendingLabel: "Restarting...",
    className:
      "border-warning/30 bg-warning/10 text-warning hover:bg-warning/15",
    Icon: RotateCw,
  },
  pull: {
    label: "Pull",
    pendingLabel: "Pulling...",
    className: "border-info/30 bg-info/10 text-info hover:bg-info/15",
    Icon: Download,
  },
};

function getStatusTone(status: string): BadgeProps["tone"] {
  if (status === "running") return "success";
  if (status === "stopped" || status === "exited") return "danger";
  if (status === "partial") return "warning";
  return "neutral";
}

export function StackCard({
  stack,
  pendingAction,
  onAction,
  onLogs,
  onEdit,
  onBackups,
}: {
  stack: StackSummary;
  pendingAction?: StackAction;
  onAction: (stack: StackSummary, action: StackAction) => void;
  onLogs: (stack: StackSummary) => void;
  onEdit: (stack: StackSummary) => void;
  onBackups: (stack: StackSummary) => void;
}) {
  const percent = getStackServicesPercent(stack);
  const barWidth = percent === null ? 0 : Math.max(0, Math.min(percent, 100));
  const busy = Boolean(pendingAction);
  return (
    <Card className="transition-colors duration-200 hover:border-primary/25">
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{stack.name}</p>
            {stack.compose_file ? (
              <p className="truncate text-xs text-muted-foreground">
                {stack.compose_file}
              </p>
            ) : null}
          </div>
          <StatusBadge
            className="shrink-0"
            label={stack.status}
            tone={getStatusTone(stack.status)}
          />
        </div>
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">
            {stack.running_count ?? "—"} / {stack.container_count ?? "—"}{" "}
            services up
          </p>
          <MetricBar
            label={`${stack.name} services ${barWidth}%`}
            tone="success"
            value={barWidth}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          {STACK_ACTION_ORDER.map((action) => {
            const meta = STACK_ACTION_META[action];
            const Icon = meta.Icon;
            return (
              <Button
                aria-label={`${meta.label} ${stack.name}`}
                className={cn(
                  "gap-1.5 px-2.5 text-xs sm:text-sm",
                  meta.className,
                )}
                data-action={action}
                data-stack={stack.name}
                disabled={busy}
                key={action}
                onClick={() => onAction(stack, action)}
                size="sm"
                variant="outline"
              >
                {pendingAction === action ? (
                  <Loader2
                    aria-hidden="true"
                    className="h-3.5 w-3.5 animate-spin"
                  />
                ) : (
                  <Icon aria-hidden="true" className="h-3.5 w-3.5" />
                )}
                {pendingAction === action ? meta.pendingLabel : meta.label}
              </Button>
            );
          })}
          <Button
            aria-label={`Logs ${stack.name}`}
            className="gap-1.5 text-xs sm:text-sm"
            data-stack-action="logs"
            data-stack={stack.name}
            disabled={busy}
            onClick={() => onLogs(stack)}
            size="sm"
            variant="outline"
          >
            <FileText aria-hidden="true" className="h-3.5 w-3.5" />
            Logs
          </Button>
          <Button
            aria-label={`Edit ${stack.name}`}
            className="gap-1.5 text-xs sm:text-sm"
            data-stack-action="edit"
            data-stack={stack.name}
            disabled={busy}
            onClick={() => onEdit(stack)}
            size="sm"
            variant="outline"
          >
            <Pencil aria-hidden="true" className="h-3.5 w-3.5" />
            Edit
          </Button>
          <Button
            aria-label={`Backups ${stack.name}`}
            className="gap-1.5 text-xs sm:text-sm"
            data-stack-action="backups"
            data-stack={stack.name}
            disabled={busy}
            onClick={() => onBackups(stack)}
            size="sm"
            variant="outline"
          >
            <Archive aria-hidden="true" className="h-3.5 w-3.5" />
            Backups
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
