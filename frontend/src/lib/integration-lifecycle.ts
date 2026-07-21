import {
  lifecycleMutationRoute,
  type IntegrationLifecycleAction,
  type IntegrationLifecycleId,
} from "@/lib/integration-lifecycle-contract";
import { createOperation, streamOperation, type OperationEvent } from "@/lib/operations";

export async function runIntegrationLifecycleOperation(
  integration: IntegrationLifecycleId,
  action: IntegrationLifecycleAction,
  values: Record<string, unknown>,
  onEvent: (event: OperationEvent) => void,
  options: {
    cleanupAction?: IntegrationLifecycleAction | null;
    onCreated?: () => void;
    signal?: AbortSignal;
  } = {},
): Promise<void> {
  const route = lifecycleMutationRoute(integration, action, options.cleanupAction);
  if (!route) throw new Error("Lifecycle action is unavailable");
  const operation = await createOperation(route, values, options.signal);
  options.onCreated?.();
  await streamOperation(
    operation.stream_url,
    (event) => {
      onEvent(event);
      if (event.error) throw new Error(event.error);
    },
    options.signal,
  );
}
