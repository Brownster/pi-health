import { requestApi } from "@/lib/api";

export interface SetupAction {
  id: string;
  title: string;
  body: string;
  action_label: string;
  href: string;
}

export function getPendingSetupActions(
  signal?: AbortSignal,
): Promise<{ actions: SetupAction[] }> {
  return requestApi<{ actions: SetupAction[] }>("/api/setup/pending", {
    method: "GET",
    signal,
  });
}
