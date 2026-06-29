import { Loader2 } from "lucide-react";

import { Badge, StatusBadge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { type StoragePlugin } from "@/lib/storage-plugins";
import { cn } from "@/lib/utils";

function getStatusTone(plugin: StoragePlugin): BadgeProps["tone"] {
  if (!plugin.enabled) return "neutral";
  if (plugin.status === "active" || plugin.status === "ok") return "success";
  if (plugin.status === "missing" || plugin.status === "error") return "danger";
  return "warning";
}

export function PluginCard({
  plugin,
  pending,
  confirmingRemove,
  onToggle,
  onDetails,
  onRemoveRequest,
  onRemoveConfirm,
  onRemoveCancel,
}: {
  plugin: StoragePlugin;
  pending: boolean;
  confirmingRemove: boolean;
  onToggle: (plugin: StoragePlugin) => void;
  onDetails: (plugin: StoragePlugin) => void;
  onRemoveRequest: (id: string) => void;
  onRemoveConfirm: (plugin: StoragePlugin) => void;
  onRemoveCancel: () => void;
}) {
  return (
    <Card className="transition-colors duration-200 hover:border-primary/25">
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{plugin.name}</p>
            <p className="line-clamp-2 text-xs text-muted-foreground">
              {plugin.description || plugin.id}
            </p>
          </div>
          <StatusBadge
            className="shrink-0"
            label={plugin.enabled ? plugin.status : "disabled"}
            tone={getStatusTone(plugin)}
          />
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge tone={plugin.installed ? "success" : "neutral"}>
            {plugin.installed ? "installed" : "not installed"}
          </Badge>
          {plugin.status_message ? (
            <span className="text-muted-foreground">
              {plugin.status_message}
            </span>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            aria-label={`${plugin.enabled ? "Disable" : "Enable"} ${plugin.name}`}
            className={cn(
              "gap-1.5 text-xs sm:text-sm",
              plugin.enabled
                ? "border-warning/30 bg-warning/10 text-warning hover:bg-warning/15"
                : "border-success/30 bg-success/10 text-success hover:bg-success/15",
            )}
            data-plugin={plugin.id}
            data-plugin-action={plugin.enabled ? "disable" : "enable"}
            disabled={pending}
            onClick={() => onToggle(plugin)}
            size="sm"
            variant="outline"
          >
            {pending ? (
              <Loader2
                aria-hidden="true"
                className="h-3.5 w-3.5 animate-spin"
              />
            ) : null}
            {plugin.enabled ? "Disable" : "Enable"}
          </Button>
          <Button
            aria-label={`Details ${plugin.name}`}
            className="gap-1.5 text-xs sm:text-sm"
            data-plugin={plugin.id}
            data-plugin-action="details"
            disabled={pending}
            onClick={() => onDetails(plugin)}
            size="sm"
            variant="outline"
          >
            Details
          </Button>
          {plugin.type !== "builtin" ? (
            confirmingRemove ? (
              <span className="flex items-center gap-1.5">
                <Button
                  className="border-danger/30 bg-danger/10 text-danger hover:bg-danger/15 text-xs sm:text-sm"
                  data-confirm-remove={plugin.id}
                  onClick={() => onRemoveConfirm(plugin)}
                  size="sm"
                  variant="outline"
                >
                  Confirm remove
                </Button>
                <Button onClick={onRemoveCancel} size="sm" variant="outline">
                  Cancel
                </Button>
              </span>
            ) : (
              <Button
                aria-label={`Remove ${plugin.name}`}
                className="text-xs sm:text-sm"
                data-plugin={plugin.id}
                data-plugin-action="remove"
                disabled={pending}
                onClick={() => onRemoveRequest(plugin.id)}
                size="sm"
                variant="outline"
              >
                Remove
              </Button>
            )
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
