import { requestApi, toNullableNumber, toNullableString } from "@/lib/api";

export interface ActivityStream {
  source: string;
  label: string;
  title: string;
  subtitle: string;
  user: string;
  client: string;
  device: string;
  play_method: string | null;
  is_paused: boolean;
  is_transcoding: boolean;
  transcode_reason: string | null;
  bitrate: number | null;
  progress_percent: number | null;
  position_seconds: number | null;
  duration_seconds: number | null;
}

export interface ActivityDownload {
  source: string;
  label: string;
  name: string;
  state: string;
  progress_percent: number | null;
  size_bytes: number | null;
  remaining_bytes: number | null;
  speed_bytes: number | null;
  eta: string | null;
}

export interface ActivityQueueItem {
  title: string;
  state: string;
  status: string;
}

export interface ActivityQueue {
  source: string;
  label: string;
  total: number;
  problems: number;
  items: ActivityQueueItem[];
}

export interface ActivityServiceStatus {
  id: string;
  name: string;
  label: string;
  family: string;
  reachable: boolean;
  detail: string | null;
}

export interface ActivityTotals {
  streams: number;
  transcodes: number;
  downloads: number;
  download_speed: number;
  queued: number;
  queue_problems: number;
}

export interface ActivitySnapshot {
  collected_at: string;
  streams: ActivityStream[];
  downloads: ActivityDownload[];
  queues: ActivityQueue[];
  services: ActivityServiceStatus[];
  totals: ActivityTotals;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function asArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map((item) => asRecord(item)) : [];
}

function normalizeStream(value: Record<string, unknown>): ActivityStream {
  return {
    source: String(value.source ?? ""),
    label: String(value.label ?? ""),
    title: String(value.title ?? "Unknown title"),
    subtitle: String(value.subtitle ?? ""),
    user: String(value.user ?? ""),
    client: String(value.client ?? ""),
    device: String(value.device ?? ""),
    play_method: toNullableString(value.play_method),
    is_paused: Boolean(value.is_paused),
    is_transcoding: Boolean(value.is_transcoding),
    transcode_reason: toNullableString(value.transcode_reason),
    bitrate: toNullableNumber(value.bitrate),
    progress_percent: toNullableNumber(value.progress_percent),
    position_seconds: toNullableNumber(value.position_seconds),
    duration_seconds: toNullableNumber(value.duration_seconds),
  };
}

function normalizeDownload(value: Record<string, unknown>): ActivityDownload {
  return {
    source: String(value.source ?? ""),
    label: String(value.label ?? ""),
    name: String(value.name ?? "Unknown item"),
    state: String(value.state ?? "queued"),
    progress_percent: toNullableNumber(value.progress_percent),
    size_bytes: toNullableNumber(value.size_bytes),
    remaining_bytes: toNullableNumber(value.remaining_bytes),
    speed_bytes: toNullableNumber(value.speed_bytes),
    eta: toNullableString(value.eta),
  };
}

function normalizeQueue(value: Record<string, unknown>): ActivityQueue {
  return {
    source: String(value.source ?? ""),
    label: String(value.label ?? ""),
    total: toNullableNumber(value.total) ?? 0,
    problems: toNullableNumber(value.problems) ?? 0,
    items: asArray(value.items).map((item) => ({
      title: String(item.title ?? "Unknown item"),
      state: String(item.state ?? "queued"),
      status: String(item.status ?? "unknown"),
    })),
  };
}

function normalizeService(value: Record<string, unknown>): ActivityServiceStatus {
  return {
    id: String(value.id ?? ""),
    name: String(value.name ?? "unknown"),
    label: String(value.label ?? ""),
    family: String(value.family ?? ""),
    reachable: Boolean(value.reachable),
    detail: toNullableString(value.detail),
  };
}

export async function fetchActivity(signal?: AbortSignal): Promise<ActivitySnapshot> {
  const payload = await requestApi<Record<string, unknown>>("/api/activity", {
    method: "GET",
    signal,
  });
  const totals = asRecord(payload.totals);
  return {
    collected_at: String(payload.collected_at ?? ""),
    streams: asArray(payload.streams).map(normalizeStream),
    downloads: asArray(payload.downloads).map(normalizeDownload),
    queues: asArray(payload.queues).map(normalizeQueue),
    services: asArray(payload.services).map(normalizeService),
    totals: {
      streams: toNullableNumber(totals.streams) ?? 0,
      transcodes: toNullableNumber(totals.transcodes) ?? 0,
      downloads: toNullableNumber(totals.downloads) ?? 0,
      download_speed: toNullableNumber(totals.download_speed) ?? 0,
      queued: toNullableNumber(totals.queued) ?? 0,
      queue_problems: toNullableNumber(totals.queue_problems) ?? 0,
    },
  };
}

/** True when nothing is streaming, downloading, or waiting in a queue. */
export function isActivityIdle(snapshot: ActivitySnapshot | null): boolean {
  if (!snapshot) {
    return false;
  }
  const { streams, downloads, queued } = snapshot.totals;
  return streams === 0 && downloads === 0 && queued === 0;
}
