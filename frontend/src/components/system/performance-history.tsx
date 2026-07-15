import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Activity, Database, Thermometer, TriangleAlert } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import {
  type HistoricalMetric,
  type MetricHistoryRange,
  type MetricHistoryResponse,
  type MetricHistorySummary,
  fetchMetricHistory,
} from "@/lib/metric-history";
import { cn } from "@/lib/utils";

const ranges: Array<{ value: MetricHistoryRange; label: string }> = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
];

const metricLabels: Record<HistoricalMetric, string> = {
  cpu_percent: "CPU",
  memory_percent: "Memory",
  temperature_celsius: "Temperature",
  disk_percent: "Storage",
};

function getErrorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "Unable to load metric history";
}

function formatValue(value: number | null, unit: "%" | "°C"): string {
  return value === null || !Number.isFinite(value) ? "—" : `${value.toFixed(1)}${unit}`;
}

function formatAxisTime(value: string, range: MetricHistoryRange): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  if (range === "24h") {
    return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(date);
  }
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" }).format(date);
}

function formatTooltipTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
  }).format(date);
}

function SummaryRow({
  label,
  summary,
  unit,
  tone,
}: {
  label: string;
  summary: MetricHistorySummary;
  unit: "%" | "°C";
  tone: string;
}) {
  return (
    <div className="grid grid-cols-[minmax(4rem,1fr)_repeat(4,minmax(2.75rem,auto))] items-center gap-x-2 border-t border-divider py-2 text-right first:border-t-0 sm:grid-cols-[minmax(5rem,1fr)_repeat(4,minmax(3.5rem,auto))] sm:gap-x-3">
      <span className={cn("truncate text-left text-xs font-medium", tone)}>{label}</span>
      {(["current", "min", "average", "max"] as const).map((key) => (
        <span className="font-mono text-[11px] text-muted-foreground" key={key}>
          {formatValue(summary[key], unit)}
        </span>
      ))}
    </div>
  );
}

function SummaryHeader() {
  return (
    <div className="grid grid-cols-[minmax(4rem,1fr)_repeat(4,minmax(2.75rem,auto))] gap-x-2 border-b border-divider pb-2 text-right font-mono text-[9px] uppercase text-dim sm:grid-cols-[minmax(5rem,1fr)_repeat(4,minmax(3.5rem,auto))] sm:gap-x-3">
      <span className="text-left">metric</span>
      <span>now</span>
      <span>min</span>
      <span>avg</span>
      <span>max</span>
    </div>
  );
}

function HistoryChart({
  title,
  icon: Icon,
  history,
  metrics,
  unit,
  domain,
}: {
  title: string;
  icon: typeof Activity;
  history: MetricHistoryResponse;
  metrics: Array<{ key: HistoricalMetric; color: string }>;
  unit: "%" | "°C";
  domain: [number, number];
}) {
  return (
    <Card className="min-w-0">
      <CardContent className="p-4 sm:p-5">
        <div className="flex items-center gap-2">
          <Icon aria-hidden="true" className="h-4 w-4 text-primary" />
          <h3 className="font-mono text-sm font-semibold text-foreground">{title}</h3>
        </div>
        <div className="mt-4 h-[240px] min-w-0" data-testid={`history-chart-${metrics[0].key}`}>
          <ResponsiveContainer height="100%" minWidth={0} width="100%">
            <LineChart data={history.points} margin={{ bottom: 0, left: -20, right: 8, top: 4 }}>
              <CartesianGrid stroke="var(--divider)" strokeDasharray="3 3" vertical={false} />
              <XAxis
                axisLine={false}
                dataKey="at"
                minTickGap={36}
                padding={{ left: 8, right: 8 }}
                tick={{ fill: "var(--dim)", fontFamily: "var(--font-mono)", fontSize: 10 }}
                tickFormatter={(value) => formatAxisTime(String(value), history.range)}
                tickLine={false}
              />
              <YAxis
                axisLine={false}
                domain={domain}
                tick={{ fill: "var(--dim)", fontFamily: "var(--font-mono)", fontSize: 10 }}
                tickFormatter={(value) => `${value}${unit}`}
                tickLine={false}
                width={50}
              />
              <Tooltip
                contentStyle={{
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                  borderRadius: "6px",
                  color: "var(--foreground)",
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                }}
                cursor={{ stroke: "var(--dim)", strokeDasharray: "3 3" }}
                formatter={(value, name) => [
                  formatValue(typeof value === "number" ? value : Number(value), unit),
                  metricLabels[String(name) as HistoricalMetric] ?? String(name),
                ]}
                isAnimationActive={false}
                labelFormatter={(value) => formatTooltipTime(String(value))}
              />
              {metrics.map((metric) => (
                <Line
                  activeDot={{ r: 3, strokeWidth: 0 }}
                  connectNulls={false}
                  dataKey={metric.key}
                  dot={false}
                  isAnimationActive={false}
                  key={metric.key}
                  name={metric.key}
                  stroke={metric.color}
                  strokeWidth={2}
                  type="monotone"
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-3 min-w-0" data-testid={`history-summary-${metrics[0].key}`}>
          <div>
            <SummaryHeader />
            {metrics.map((metric) => (
              <SummaryRow
                key={metric.key}
                label={metricLabels[metric.key]}
                summary={history.summary[metric.key]}
                tone={metric.color === "var(--info)" ? "text-info" : metric.color === "var(--success)" ? "text-success" : "text-warning"}
                unit={unit}
              />
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function PerformanceHistory({ refreshKey }: { refreshKey: number }) {
  const [range, setRange] = useState<MetricHistoryRange>("24h");
  const [history, setHistory] = useState<MetricHistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    void fetchMetricHistory(range, controller.signal)
      .then((next) => {
        setHistory(next);
        setError(null);
      })
      .catch((caughtError) => {
        if (!controller.signal.aborted) {
          setError(getErrorMessage(caughtError));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      });
    return () => controller.abort();
  }, [range, refreshKey]);

  return (
    <section aria-labelledby="performance-history-title" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-divider pb-3">
        <div>
          <h2 className="font-mono text-sm font-semibold text-foreground" id="performance-history-title">
            performance_history
          </h2>
          <p className="mt-1 font-mono text-[11px] text-dim">
            {history ? `${history.bucket_seconds / 60} minute samples` : "loading samples"}
          </p>
        </div>
        <div aria-label="History range" className="flex rounded-md border border-border bg-card p-0.5" role="group">
          {ranges.map((item) => (
            <button
              aria-pressed={range === item.value}
              className={cn(
                "min-h-9 min-w-12 cursor-pointer rounded px-3 font-mono text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                range === item.value ? "bg-muted text-primary" : "text-muted-foreground hover:text-foreground",
              )}
              key={item.value}
              onClick={() => setRange(item.value)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <div aria-live="polite" className="flex items-start gap-3 border-l-2 border-danger bg-danger/[0.06] p-4 text-sm text-danger" role="status">
          <TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </div>
      ) : null}

      {isLoading && !history ? (
        <Card>
          <CardContent className="flex h-[240px] items-center justify-center p-5 text-sm text-muted-foreground">
            Loading metric history...
          </CardContent>
        </Card>
      ) : history?.points.length ? (
        <div className="grid gap-3 xl:grid-cols-2">
          <HistoryChart
            domain={[0, 100]}
            history={history}
            icon={Activity}
            metrics={[
              { key: "cpu_percent", color: "var(--info)" },
              { key: "memory_percent", color: "var(--success)" },
            ]}
            title="CPU and memory"
            unit="%"
          />
          <HistoryChart
            domain={[0, 100]}
            history={history}
            icon={Thermometer}
            metrics={[{ key: "temperature_celsius", color: "var(--warning)" }]}
            title="Temperature"
            unit="°C"
          />
          <div className="xl:col-span-2">
            <HistoryChart
              domain={[0, 100]}
              history={history}
              icon={Database}
              metrics={[{ key: "disk_percent", color: "var(--success)" }]}
              title="Primary storage"
              unit="%"
            />
          </div>
        </div>
      ) : !isLoading ? (
        <Card>
          <CardContent className="flex min-h-36 flex-col items-center justify-center gap-2 p-5 text-center">
            <Database aria-hidden="true" className="h-5 w-5 text-dim" />
            <p className="text-sm text-muted-foreground">History will appear after the first metric collection.</p>
          </CardContent>
        </Card>
      ) : null}
    </section>
  );
}
