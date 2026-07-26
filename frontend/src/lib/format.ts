const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

export const UNKNOWN = "—";

// Number(null) and Number("") are both 0, so an unknown reading would otherwise
// render as a convincing "0 B" or "0.0%". Only real numbers get formatted.
function toNumber(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function formatBytes(value: number | null | undefined, precision = 1): string {
  const bytes = toNumber(value);
  if (bytes === null || bytes < 0) {
    return UNKNOWN;
  }

  if (bytes === 0) {
    return "0 B";
  }

  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    BYTE_UNITS.length - 1,
  );
  const amount = bytes / 1024 ** exponent;
  return `${amount.toFixed(precision)} ${BYTE_UNITS[exponent]}`;
}

export function formatRate(value: number | null | undefined): string {
  const bytes = toNumber(value);
  return bytes === null ? UNKNOWN : `${formatBytes(bytes)}/s`;
}

export function formatClockTime(value: Date): string {
  const hours = String(value.getHours()).padStart(2, "0");
  const minutes = String(value.getMinutes()).padStart(2, "0");
  const seconds = String(value.getSeconds()).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

export function formatPercent(value: number | null | undefined, precision = 1): string {
  const percent = toNumber(value);
  return percent === null ? UNKNOWN : `${percent.toFixed(precision)}%`;
}

/** Compact wall-clock duration: 3d 4h, 4h 12m, 12m, 45s. */
export function formatDuration(seconds: number | null | undefined): string {
  const total = toNumber(seconds);
  if (total === null || total < 0) {
    return UNKNOWN;
  }
  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3_600);
  const minutes = Math.floor((total % 3_600) / 60);
  if (days) {
    return `${days}d ${hours}h`;
  }
  if (hours) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes) {
    return `${minutes}m`;
  }
  return `${Math.floor(total)}s`;
}
