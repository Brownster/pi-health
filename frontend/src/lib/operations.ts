import { requestApi } from "@/lib/api";

export interface OperationEvent {
  line?: string;
  done?: boolean;
  returncode?: number;
  error?: string;
  // Self-update operations add step labels and a pending-restart signal.
  step?: string;
  restarting?: boolean;
  new_commit?: string;
  installed?: string[];
  skipped?: string[];
  summary?: unknown;
  operation_id?: string;
  authorization_url?: string;
  requires_auth?: boolean;
  requires_setup?: boolean;
  expired?: boolean;
}

export interface OperationCreated {
  operation_id: string;
  stream_url: string;
}

export async function createOperation(
  path: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<OperationCreated> {
  const auth = await requestApi<{ csrf_token?: string }>("/api/auth/check", {
    method: "GET",
    signal,
  });
  if (!auth.csrf_token) {
    throw new Error("CSRF token unavailable");
  }
  const payload = await requestApi<Partial<OperationCreated> & { error?: string }>(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": auth.csrf_token,
    },
    body: JSON.stringify(body),
    signal,
  });
  if (payload.error || !payload.operation_id || !payload.stream_url) {
    throw new Error(payload.error || "Operation was not created");
  }
  return {
    operation_id: payload.operation_id,
    stream_url: payload.stream_url,
  };
}

export async function streamOperation(
  streamUrl: string,
  onEvent: (event: OperationEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(streamUrl, {
    method: "GET",
    credentials: "same-origin",
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`Operation stream failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminalEvent = false;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    let separator = buffer.indexOf("\n\n");
    while (separator !== -1) {
      const frame = buffer.slice(0, separator);
      buffer = buffer.slice(separator + 2);
      const dataLine = frame.split("\n").find((line) => line.startsWith("data:"));
      if (dataLine) {
        try {
          const event = JSON.parse(dataLine.slice(5).trim()) as OperationEvent;
          terminalEvent = terminalEvent || Boolean(event.done || event.error);
          onEvent(event);
        } catch (error) {
          if (error instanceof SyntaxError) {
            // Ignore malformed frames; a terminal event still controls completion.
          } else {
            throw error;
          }
        }
      }
      separator = buffer.indexOf("\n\n");
    }
  }
  if (!terminalEvent) {
    throw new Error("Operation stream ended before completion");
  }
}
