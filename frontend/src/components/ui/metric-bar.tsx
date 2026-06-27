import { cn } from "@/lib/utils";

const toneClasses = {
  primary: "bg-primary",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
} as const;

export function MetricBar({
  value,
  tone = "primary",
  className,
  label,
}: {
  value: number | null | undefined;
  tone?: keyof typeof toneClasses;
  className?: string;
  label: string;
}) {
  const hasValue = value !== null && value !== undefined && Number.isFinite(Number(value));
  const normalizedValue = hasValue
    ? Math.min(100, Math.max(0, Number(value)))
    : 0;

  return (
    <div
      aria-label={label}
      aria-valuemax={100}
      aria-valuemin={0}
      aria-valuenow={hasValue ? Math.round(normalizedValue) : undefined}
      className={cn("h-1 overflow-hidden rounded-full bg-border", className)}
      role="progressbar"
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-300", toneClasses[tone])}
        style={{ width: `${normalizedValue}%` }}
      />
    </div>
  );
}
