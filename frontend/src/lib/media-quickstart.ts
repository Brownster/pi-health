import { createOperation, streamOperation, type OperationEvent } from "@/lib/operations";

export interface MediaQuickstartOptions {
  stack: string;
  values?: Record<string, string>;
  signal?: AbortSignal;
  onEvent: (event: OperationEvent) => void;
}

export async function runMediaQuickstart({
  stack,
  values = {},
  signal,
  onEvent,
}: MediaQuickstartOptions): Promise<void> {
  const operation = await createOperation(
    "/api/media/quickstart",
    {
      stack,
      values,
    },
    signal,
  );
  await streamOperation(operation.stream_url, onEvent, signal);
}
