import { CalendarClock, History, Settings2, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";

import { protectionProviderPath } from "@/app/route-contract";
import { StatusBadge, type BadgeProps } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import type { CapabilityHealthState } from "@/lib/capabilities";
import type { ProtectionSetView } from "@/lib/protection-capabilities";
import { cn } from "@/lib/utils";

function healthTone(state: CapabilityHealthState): BadgeProps["tone"] {
  if (state === "healthy") return "success";
  if (state === "warning" || state === "unconfigured") return "warning";
  if (["error", "unavailable", "incompatible"].includes(state)) return "danger";
  return "neutral";
}

function formatMoment(value: string | null): string {
  if (!value) return "Not reported";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function ProtectionSetCard({ protectionSet }: { protectionSet: ProtectionSetView }) {
  const actionTone = protectionSet.health === "error" ? "danger" : "warning";
  return (
    <article
      className={cn(
        "overflow-hidden rounded-md border bg-card",
        protectionSet.requiredAction
          ? actionTone === "danger" ? "border-danger/45" : "border-warning/45"
          : "border-border",
      )}
      data-protection-set={protectionSet.name}
    >
      <div className="flex items-start justify-between gap-3 px-4 py-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <ShieldCheck aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <div className="min-w-0">
            <h2 className="truncate font-mono text-sm font-semibold">{protectionSet.name}</h2>
            <p className="mt-0.5 text-xs capitalize text-muted-foreground">{protectionSet.kind}</p>
          </div>
        </div>
        <StatusBadge className="shrink-0" label={protectionSet.health} tone={healthTone(protectionSet.health)} />
      </div>

      <dl className="grid grid-cols-3 border-y border-border">
        {[
          { label: "Protected", value: protectionSet.protectedTargets },
          { label: "Unprotected", value: protectionSet.unprotectedTargets },
          { label: "Parity / copies", value: protectionSet.parityTargets },
        ].map((item) => (
          <div className="min-w-0 border-r border-border px-3 py-2.5 last:border-r-0" key={item.label}>
            <dt className="font-mono text-[9px] uppercase text-dim">{item.label}</dt>
            <dd className="mt-1 text-sm font-semibold tabular-nums">{item.value ?? "—"}</dd>
          </div>
        ))}
      </dl>

      <div className="space-y-2 px-4 py-3 text-xs text-muted-foreground">
        <p className="flex items-start gap-2"><History aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span><span className="text-dim">Last run</span><br />{formatMoment(protectionSet.lastRunAt)}</span></p>
        <p className="flex items-start gap-2"><CalendarClock aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span><span className="text-dim">Next run</span><br />{protectionSet.nextRunAt ? formatMoment(protectionSet.nextRunAt) : protectionSet.schedule ?? "Not scheduled"}</span></p>
      </div>

      {protectionSet.requiredAction ? (
        <div className={cn("border-t px-4 py-2.5 text-xs font-medium", actionTone === "danger" ? "border-danger/30 bg-danger/10 text-danger" : "border-warning/30 bg-warning/10 text-warning")} data-protection-action>
          {protectionSet.requiredAction}
        </div>
      ) : null}

      <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-3">
        <div className="min-w-0"><p className="font-mono text-[9px] uppercase text-dim">Provider</p><p className="truncate text-xs text-muted-foreground">{protectionSet.providerName}</p></div>
        <Link aria-label={`Manage ${protectionSet.name}`} className={cn(buttonVariants({ size: "sm", variant: "outline" }), "shrink-0 gap-1.5")} to={protectionProviderPath(protectionSet.providerId)}><Settings2 aria-hidden="true" className="h-3.5 w-3.5" />Manage</Link>
      </div>
    </article>
  );
}
