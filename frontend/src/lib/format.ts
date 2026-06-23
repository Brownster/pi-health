const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

export function formatBytes(value: number | null | undefined, precision = 1): string {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) {
    return "—";
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

export function formatClockTime(value: Date): string {
  const hours = String(value.getHours()).padStart(2, "0");
  const minutes = String(value.getMinutes()).padStart(2, "0");
  const seconds = String(value.getSeconds()).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

export function formatPercent(value: number | null | undefined): string {
  const percent = Number(value);
  if (!Number.isFinite(percent)) {
    return "—";
  }
  return `${percent.toFixed(1)}%`;
}
