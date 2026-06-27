import { requestApi } from "@/lib/api";

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
  const payload = await requestApi<{ status?: string; error?: string }>("/api/catalog/install", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: itemId, values }),
    signal,
  });
  if (payload.error) {
    throw new Error(payload.error);
  }
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
