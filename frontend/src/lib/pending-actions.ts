import { requestApi } from "@/lib/api";

export type PendingActionSeverity = "info" | "attention" | "critical";

export interface PendingAction {
  id: string;
  title: string;
  detail: string;
  severity: PendingActionSeverity;
  source: string;
  command: string;
  created_at: string;
}

const SEVERITIES: PendingActionSeverity[] = ["info", "attention", "critical"];

function normalize(value: unknown): PendingAction {
  const record = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const severity = String(record.severity ?? "attention") as PendingActionSeverity;
  return {
    id: String(record.id ?? "unknown"),
    title: String(record.title ?? "Manual action required"),
    detail: String(record.detail ?? ""),
    severity: SEVERITIES.includes(severity) ? severity : "attention",
    source: String(record.source ?? "system"),
    command: String(record.command ?? ""),
    created_at: String(record.created_at ?? ""),
  };
}

export async function fetchPendingActions(signal?: AbortSignal): Promise<PendingAction[]> {
  const payload = await requestApi<{ actions?: unknown[] }>("/api/pending-actions", {
    method: "GET",
    signal,
  });
  return Array.isArray(payload.actions) ? payload.actions.map(normalize) : [];
}

export async function dismissPendingAction(actionId: string): Promise<void> {
  await requestApi(`/api/pending-actions/${encodeURIComponent(actionId)}/dismiss`, {
    method: "POST",
  });
}
