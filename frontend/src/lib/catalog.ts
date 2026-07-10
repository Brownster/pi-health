import { requestApi } from "@/lib/api";
import { createOperation, streamOperation } from "@/lib/operations";
import { fetchStacks } from "@/lib/stacks";

export interface CatalogItem {
  id: string;
  name: string;
  description: string;
  requires: string[];
  installedStacks: string[];
  managedBy: string | null;
}

export interface CatalogSnapshot {
  items: CatalogItem[];
  availableStacks: string[];
}

export interface CatalogField {
  key: string;
  label: string;
  default: string;
  required: boolean;
}

function normalizeStackNames(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return [...new Set(value.map((stack) => String(stack).trim()).filter(Boolean))].sort();
}

function normalizeItem(
  raw: Record<string, unknown> | undefined,
  serviceStacks: Record<string, unknown>,
): CatalogItem {
  const id = String(raw?.id ?? "");
  return {
    id,
    name: String(raw?.name ?? id),
    description: String(raw?.description ?? ""),
    requires: Array.isArray(raw?.requires) ? raw.requires.map((r) => String(r)) : [],
    installedStacks: normalizeStackNames(serviceStacks[id]),
    managedBy: raw?.managed_by ? String(raw.managed_by) : null,
  };
}

/** Fetch catalog items, stack-specific install status, and valid target stacks. */
export async function fetchCatalog(signal?: AbortSignal): Promise<CatalogSnapshot> {
  const [catalog, status, stacks] = await Promise.all([
    requestApi<{ items?: Record<string, unknown>[] }>("/api/catalog", { method: "GET", signal }),
    requestApi<{ service_stacks?: Record<string, unknown> }>("/api/catalog/status", {
      method: "GET",
      signal,
    }),
    fetchStacks({ includeStatus: false, signal }),
  ]);
  const serviceStacks = status.service_stacks ?? {};
  return {
    items: Array.isArray(catalog.items)
      ? catalog.items.map((item) => normalizeItem(item, serviceStacks))
      : [],
    availableStacks: [...new Set(stacks.map((stack) => stack.name).filter(Boolean))].sort(),
  };
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
  targetStack: string,
  stackName: string,
  signal?: AbortSignal,
): Promise<void> {
  const operation = await createOperation(
    "/api/catalog/install",
    {
      id: itemId,
      values,
      start_service: true,
      target_stack: targetStack,
      stack_name: stackName,
    },
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

export async function removeCatalogItem(
  itemId: string,
  targetStack: string,
  signal?: AbortSignal,
): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>("/api/catalog/remove", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: itemId, stop_service: true, target_stack: targetStack }),
    signal,
  });
  if (payload.error) {
    throw new Error(payload.error);
  }
}
