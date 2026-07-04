/**
 * Shared HTTP + normalization helpers for v2 API clients.
 *
 * Centralized in Phase 3 (PH3-001) so per-domain clients (containers, stacks,
 * disks, ...) do not each re-declare the same request/normalize primitives.
 */

const MAX_ERROR_BODY_BYTES = 64 * 1024;
const MAX_ERROR_MESSAGE_CHARS = 2_000;

interface BoundedBody {
  text: string;
  truncated: boolean;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly path: string;
  readonly details: unknown;
  readonly bodyTruncated: boolean;

  constructor({
    status,
    code,
    path,
    message,
    details,
    bodyTruncated,
  }: {
    status: number;
    code: string;
    path: string;
    message: string;
    details?: unknown;
    bodyTruncated: boolean;
  }) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.path = path;
    this.details = details;
    this.bodyTruncated = bodyTruncated;
  }
}

async function readBoundedBody(response: Response): Promise<BoundedBody> {
  if (!response.body) {
    return { text: "", truncated: false };
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let text = "";
  let bytesRead = 0;
  let truncated = false;

  for (;;) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    const remaining = MAX_ERROR_BODY_BYTES - bytesRead;
    if (remaining <= 0) {
      truncated = true;
      await reader.cancel().catch(() => undefined);
      break;
    }
    const chunk = value.byteLength > remaining ? value.subarray(0, remaining) : value;
    bytesRead += chunk.byteLength;
    text += decoder.decode(chunk, { stream: true });
    if (chunk.byteLength < value.byteLength || bytesRead === MAX_ERROR_BODY_BYTES) {
      truncated = true;
      await reader.cancel().catch(() => undefined);
      break;
    }
  }
  text += decoder.decode();
  return { text, truncated };
}

function boundedString(value: unknown, maxLength = MAX_ERROR_MESSAGE_CHARS): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return null;
  }
  return normalized.slice(0, maxLength);
}

function formatDetails(details: unknown): string | null {
  if (Array.isArray(details)) {
    const messages = details
      .map((detail) => boundedString(detail, 500))
      .filter((detail): detail is string => detail !== null);
    return messages.length ? messages.join("; ").slice(0, MAX_ERROR_MESSAGE_CHARS) : null;
  }
  return boundedString(details);
}

async function createApiError(response: Response, path: string): Promise<ApiError> {
  let body: BoundedBody = { text: "", truncated: false };
  try {
    body = await readBoundedBody(response);
  } catch {
    // The HTTP status remains useful even when the response stream fails.
  }
  const { text, truncated } = body;
  const contentType = response.headers.get("Content-Type")?.toLowerCase() ?? "";
  const expectsJson = contentType.includes("json");
  const isHtml = contentType.includes("text/html");
  let payload: Record<string, unknown> | null = null;
  try {
    const parsed = JSON.parse(text) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      payload = parsed as Record<string, unknown>;
    }
  } catch {
    payload = null;
  }

  const backendCode = boundedString(payload?.code ?? payload?.error_code, 128);
  const primary = boundedString(payload?.error) ?? boundedString(payload?.message);
  const guidance = primary ? boundedString(payload?.message) : null;
  const detailText = formatDetails(payload?.details);
  const messageParts = [primary];
  if (guidance && guidance !== primary) {
    messageParts.push(guidance);
  }
  let message = messageParts.filter((part): part is string => part !== null).join(": ");
  if (detailText) {
    message = message ? `${message} (${detailText})` : detailText;
  }
  if (!message && !payload && !expectsJson && !isHtml) {
    message = boundedString(text) ?? "";
  }
  if (!message) {
    message = `Request failed (${response.status}) for ${path}`;
  }

  return new ApiError({
    status: response.status,
    code: backendCode ?? `http_${response.status}`,
    path,
    message: message.slice(0, MAX_ERROR_MESSAGE_CHARS),
    details: payload?.details,
    bodyTruncated: truncated,
  });
}

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

let cachedCsrfToken: string | null = null;

/** Prime the CSRF token cache (e.g. from an auth-check response). */
export function setCsrfToken(token: string | null): void {
  cachedCsrfToken = token;
}

async function ensureCsrfToken(): Promise<string | null> {
  if (cachedCsrfToken) {
    return cachedCsrfToken;
  }
  try {
    const response = await fetch("/api/auth/check", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (response.ok) {
      const data = (await response.json()) as { csrf_token?: string };
      cachedCsrfToken = data.csrf_token ?? null;
    }
  } catch {
    // Leave the cache empty; the caller proceeds without a token.
  }
  return cachedCsrfToken;
}

/** Headers required to authorize a mutating request (empty for safe methods). */
export async function csrfHeaders(method: string | undefined): Promise<Record<string, string>> {
  if (!MUTATING_METHODS.has((method ?? "GET").toUpperCase())) {
    return {};
  }
  const token = await ensureCsrfToken();
  return token ? { "X-CSRF-Token": token } : {};
}

export async function requestApi<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers = {
    Accept: "application/json",
    ...(init?.headers ?? {}),
    ...(await csrfHeaders(method)),
  };

  let response = await fetch(path, { ...init, credentials: "same-origin", headers });

  if (response.status === 403 && MUTATING_METHODS.has(method)) {
    // The session token may have rotated; refresh once and retry.
    cachedCsrfToken = null;
    const retryHeaders = { ...headers, ...(await csrfHeaders(method)) };
    response = await fetch(path, { ...init, credentials: "same-origin", headers: retryHeaders });
  }

  if (!response.ok) {
    throw await createApiError(response, path);
  }

  return (await response.json()) as T;
}

export function toNullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function toNullableString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}
