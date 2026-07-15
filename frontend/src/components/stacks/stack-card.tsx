import {
  Archive,
  Download,
  FileText,
  Loader2,
  Pencil,
  Play,
  RotateCw,
  Square,
  Trash2,
} from "lucide-react";

import { ActionMenu } from "@/components/ui/action-menu";
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

function getLifecycleActions(stack: StackSummary) {
  return stack.status === "running"
    ? (["down", "restart"] as const)
    : (["up"] as const);
}

export interface StackContainerRef {
  id: string;
  name: string;
  status: string;
}

export function StackCard({
  stack,
  pendingAction,
  containers,
  onAction,
  onLogs,
  onEdit,
  onBackups,
  onDelete,
  onOpenContainer,
}: {
  stack: StackSummary;
  pendingAction?: StackAction;
  containers?: StackContainerRef[];
  onAction: (stack: StackSummary, action: StackAction) => void;
  onLogs: (stack: StackSummary) => void;
  onEdit: (stack: StackSummary) => void;
  onBackups: (stack: StackSummary) => void;
  onDelete: (stack: StackSummary) => void;
  onOpenContainer?: (container: StackContainerRef) => void;
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
        {containers && containers.length ? (
          <ul className="space-y-1 rounded-md border border-border/70 bg-muted/20 p-2" data-stack-containers>
            {containers.map((container) => (
              <li className="flex items-center gap-2 text-xs" key={container.id}>
                <span
                  aria-hidden="true"
                  className={cn(
                    "h-2 w-2 shrink-0 rounded-full",
                    container.status === "running" ? "bg-success" : "bg-muted-foreground/50",
                  )}
                />
                <button
                  className="truncate text-left text-primary hover:underline"
                  data-stack-container={container.name}
                  onClick={() => onOpenContainer?.(container)}
                  type="button"
                >
                  {container.name}
                </button>
                <span className="ml-auto shrink-0 text-muted-foreground">{container.status}</span>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="flex items-center gap-1.5">
          {getLifecycleActions(stack).map((action) => {
            const meta = STACK_ACTION_META[action];
            const Icon = meta.Icon;
            return (
              <Button
                aria-label={`${meta.label} ${stack.name}`}
                className={cn("h-9 min-h-9 w-9 px-0", meta.className)}
                data-action={action}
                data-stack={stack.name}
                disabled={busy}
                key={action}
                onClick={() => onAction(stack, action)}
                size="sm"
                title={`${meta.label} ${stack.name}`}
                variant="outline"
              >
                {pendingAction === action ? (
                  <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                ) : (
                  <Icon aria-hidden="true" className="h-4 w-4" />
                )}
              </Button>
            );
          })}
          <Button
            aria-label={`Logs ${stack.name}`}
            className="h-9 min-h-9 w-9 px-0"
            data-stack-action="logs"
            data-stack={stack.name}
            disabled={busy}
            onClick={() => onLogs(stack)}
            size="sm"
            title={`Logs ${stack.name}`}
            variant="outline"
          >
            <FileText aria-hidden="true" className="h-4 w-4" />
          </Button>
          <ActionMenu
            disabled={busy}
            items={[
              {
                id: "pull",
                label: "Pull images",
                Icon: Download,
                onSelect: () => onAction(stack, "pull"),
                tone: "info",
                data: {
                  "data-action": "pull",
                  "data-stack": stack.name,
                },
              },
              {
                id: "edit",
                label: "Edit compose",
                Icon: Pencil,
                onSelect: () => onEdit(stack),
                data: {
                  "data-stack-action": "edit",
                  "data-stack": stack.name,
                },
              },
              {
                id: "backups",
                label: "Backups",
                Icon: Archive,
                onSelect: () => onBackups(stack),
                data: {
                  "data-stack-action": "backups",
                  "data-stack": stack.name,
                },
              },
              {
                id: "delete",
                label: "Delete stack",
                Icon: Trash2,
                onSelect: () => onDelete(stack),
                separatorBefore: true,
                tone: "danger",
                data: {
                  "data-stack-action": "delete",
                  "data-stack": stack.name,
                },
              },
            ]}
            label={`More actions for ${stack.name}`}
            menuData={{ "data-stack-actions-menu": stack.name }}
            pending={pendingAction === "pull"}
            triggerData={{ "data-stack-menu": stack.name }}
          />
        </div>
      </CardContent>
    </Card>
  );
}
