import { useState } from "react";
import { Boxes, Cpu, Gauge, Timer } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatBytes, formatDuration, formatPercent } from "@/lib/format";
import type { OverviewConsumer, OverviewPressure } from "@/lib/overview";
import { cn } from "@/lib/utils";

type Basis = "cpu" | "memory";

const BASES: Array<{ key: Basis; label: string }> = [
  { key: "cpu", label: "cpu" },
  { key: "memory", label: "memory" },
];

function getLoadTone(perCore: number | null): "success" | "warning" | "danger" | "neutral" {
  if (perCore === null) return "neutral";
  if (perCore >= 3) return "danger";
  if (perCore >= 1.5) return "warning";
  return "success";
}

/** Scale each row's bar against the busiest entry so small differences stay visible. */
function getShare(value: number | null, peak: number): number {
  if (value === null || peak <= 0) return 0;
  return Math.max(2, Math.min(100, (value / peak) * 100));
}

function ConsumerRow({
  consumer,
  basis,
  peak,
}: {
  consumer: OverviewConsumer;
  basis: Basis;
  peak: number;
}) {
  const value = basis === "cpu" ? consumer.cpu_percent : consumer.memory_bytes;
  const display =
    basis === "cpu" ? formatPercent(consumer.cpu_percent) : formatBytes(consumer.memory_bytes);
  return (
    <li className="min-w-0 py-2 first:pt-0 last:pb-0">
      <div className="flex min-w-0 items-baseline justify-between gap-3">
        <span className="min-w-0 truncate text-sm text-foreground" title={consumer.name}>
          {consumer.name}
        </span>
        <span className="shrink-0 font-mono text-xs text-muted-foreground">{display}</span>
      </div>
      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-border">
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-300",
            basis === "cpu" ? "bg-primary" : "bg-info",
          )}
          style={{ width: `${getShare(value, peak)}%` }}
        />
      </div>
    </li>
  );
}

function ConsumerList({
  consumers,
  basis,
  emptyLabel,
}: {
  consumers: OverviewConsumer[];
  basis: Basis;
  emptyLabel: string;
}) {
  if (!consumers.length) {
    return (
      <p className="py-3 text-sm text-muted-foreground">{emptyLabel}</p>
    );
  }
  const peak = consumers.reduce((highest, consumer) => {
    const value = basis === "cpu" ? consumer.cpu_percent : consumer.memory_bytes;
    return value !== null && value > highest ? value : highest;
  }, 0);
  return (
    <ul className="divide-y divide-divider">
      {consumers.map((consumer) => (
        <ConsumerRow basis={basis} consumer={consumer} key={consumer.id} peak={peak} />
      ))}
    </ul>
  );
}

export function PressurePanel({ pressure }: { pressure: OverviewPressure }) {
  const [basis, setBasis] = useState<Basis>("cpu");

  const containers =
    basis === "cpu" ? pressure.containers.by_cpu : pressure.containers.by_memory;
  const processes = basis === "cpu" ? pressure.processes.by_cpu : pressure.processes.by_memory;
  const load = pressure.load_average;
  const memoryAccounted = pressure.containers.capabilities.memory !== false;

  return (
    <Card>
      <CardContent className="p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Gauge aria-hidden="true" className="h-4 w-4 text-primary" />
            <h2 className="font-mono text-sm font-semibold">top consumers</h2>
          </div>
          <div className="flex items-center gap-1 rounded-md border border-border p-0.5">
            {BASES.map((option) => (
              <button
                aria-pressed={basis === option.key}
                className={cn(
                  "min-h-7 rounded px-2.5 font-mono text-[11px] transition-colors",
                  basis === option.key
                    ? "bg-primary/15 text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
                key={option.key}
                onClick={() => setBasis(option.key)}
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {load ? (
            <Badge tone={getLoadTone(load.per_core)}>
              load {load.one?.toFixed(2) ?? "—"}
              {load.cpu_count ? ` / ${load.cpu_count} cores` : ""}
            </Badge>
          ) : null}
          {pressure.uptime_seconds !== null ? (
            <Badge tone="neutral">
              <Timer aria-hidden="true" className="h-3 w-3" />
              up {formatDuration(pressure.uptime_seconds)}
            </Badge>
          ) : null}
          {pressure.processes.total !== null ? (
            <Badge tone="neutral">{pressure.processes.total} processes</Badge>
          ) : null}
        </div>

        <div className="mt-4 grid gap-4 divide-divider sm:grid-cols-2 sm:gap-5 sm:divide-x">
          <div className="min-w-0">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 font-mono text-[11px] uppercase text-dim">
                <Boxes aria-hidden="true" className="h-3.5 w-3.5" /> containers
              </span>
              <Link className="font-mono text-[10px] text-muted-foreground hover:text-primary" to="/containers">
                all
              </Link>
            </div>
            <ConsumerList
              basis={basis}
              consumers={containers}
              emptyLabel={
                basis === "memory" && !memoryAccounted
                  ? "Container memory is not accounted for on this host."
                  : "No container is using measurable resources."
              }
            />
          </div>
          <div className="min-w-0 sm:pl-5">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 font-mono text-[11px] uppercase text-dim">
                <Cpu aria-hidden="true" className="h-3.5 w-3.5" /> host processes
              </span>
              <Link className="font-mono text-[10px] text-muted-foreground hover:text-primary" to="/system">
                system
              </Link>
            </div>
            <ConsumerList
              basis={basis}
              consumers={processes}
              emptyLabel="No process is using measurable resources."
            />
          </div>
        </div>

        {basis === "cpu" ? (
          <p className="mt-3 font-mono text-[10px] text-dim">
            cpu % is per core, as reported by docker stats and top
            {load?.cpu_count ? ` — ${load.cpu_count * 100}% uses the whole machine` : ""}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
