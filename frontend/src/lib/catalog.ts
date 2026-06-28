import { requestApi } from "@/lib/api";
import { createOperation, streamOperation } from "@/lib/operations";

export interface CatalogItem {
  id: string;
  name: string;
  description: string;
  requires: string[];
  installed: boolean;
}

export interface CatalogField {
  key: string;
  label: string;
  default: string;
  required: boolean;
}

function normalizeItem(raw: Record<string, unknown> | undefined, installedSet: Set<string>): CatalogItem {
  const id = String(raw?.id ?? "");
  return {
    id,
    name: String(raw?.name ?? id),
    description: String(raw?.description ?? ""),
    requires: Array.isArray(raw?.requires) ? raw.requires.map((r) => String(r)) : [],
    installed: installedSet.has(id),
  };
}

/** Fetch catalog items + installed status in one call, merged into CatalogItem[]. */
export async function fetchCatalog(signal?: AbortSignal): Promise<CatalogItem[]> {
  const [catalog, status] = await Promise.all([
    requestApi<{ items?: Record<string, unknown>[] }>("/api/catalog", { method: "GET", signal }),
    requestApi<{ services?: unknown[] }>("/api/catalog/status", { method: "GET", signal }).catch(() => ({
      services: [],
    })),
  ]);
  const installedSet = new Set(
    Array.isArray(status.services) ? status.services.map((s) => String(s)) : [],
  );
  return Array.isArray(catalog.items) ? catalog.items.map((item) => normalizeItem(item, installedSet)) : [];
}

export async function fetchCatalogItemFields(itemId: string, signal?: AbortSignal): Promise<CatalogField[]> {
  const payload = await requestApi<{ item?: { fields?: Record<string, unknown>[] }; error?: string }>(
    `/api/catalog/${encodeURIComponent(itemId)}?apply_media_paths=true`,
    { method: "GET", signal },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
  const fields = payload.item?.fields;
  return Array.isArray(fields)
    ? fields.map((field) => ({
        key: String(field.key ?? ""),
        label: String(field.label ?? field.key ?? ""),
        default: field.default === undefined || field.default === null ? "" : String(field.default),
        required: field.required === undefined ? true : Boolean(field.required),
      }))
    : [];
}

export async function installCatalogItem(
  itemId: string,
  values: Record<string, string>,
  signal?: AbortSignal,
): Promise<void> {
  const operation = await createOperation(
    "/api/catalog/install",
    { id: itemId, values, start_service: true },
    signal,
  );
  await streamOperation(
    operation.stream_url,
    (event) => {
      if (event.error) {
        throw new Error(event.error);
      }
      if (event.done && event.returncode !== 0) {
        throw new Error(`App startup failed (${event.returncode ?? "unknown status"})`);
      }
    },
    signal,
  );
}

export async function removeCatalogItem(itemId: string, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>("/api/catalog/remove", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: itemId }),
    signal,
  });
  if (payload.error) {
    throw new Error(payload.error);
  }
}
