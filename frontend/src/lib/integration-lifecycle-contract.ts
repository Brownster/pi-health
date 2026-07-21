export const LIFECYCLE_ACTION_ORDER = [
  "setup",
  "enable",
  "repair",
  "authenticate",
  "disable",
  "uninstall",
  "retry_cleanup",
  "purge",
] as const;

export type IntegrationLifecycleAction = (typeof LIFECYCLE_ACTION_ORDER)[number];
export type IntegrationLifecycleId = "agents" | "mattermost";

export interface IntegrationLifecycleWarning {
  code: "agent_bot_cleanup_failed";
  message: string;
}

export interface IntegrationCleanupOperation {
  id: string;
  action: IntegrationLifecycleAction;
  state: "running" | "failed" | "interrupted";
  started_at: string;
  updated_at: string;
  retryable: boolean;
}

export interface IntegrationBlockedAction {
  action: "disable" | "uninstall";
  dependency_code: "agents_must_be_disabled" | "agents_must_be_uninstalled";
  message: string;
  required_action: "disable" | "uninstall";
  route: "/integrations#ai-agents";
}

export interface IntegrationLifecycleStatus {
  retained_data: boolean;
  cleanup_required: boolean;
  allowed_actions: IntegrationLifecycleAction[];
  blocked_actions: IntegrationBlockedAction[];
  cleanup_operation: IntegrationCleanupOperation | null;
  warnings: IntegrationLifecycleWarning[];
}

const SUPPORTED_ACTIONS: Record<IntegrationLifecycleId, ReadonlySet<IntegrationLifecycleAction>> = {
  agents: new Set([
    "setup",
    "enable",
    "repair",
    "authenticate",
    "disable",
    "uninstall",
    "retry_cleanup",
  ]),
  mattermost: new Set([
    "setup",
    "enable",
    "repair",
    "disable",
    "uninstall",
    "retry_cleanup",
    "purge",
  ]),
};

const MUTATION_ROUTES = {
  agents: {
    disable: "/api/integrations/agents/disable",
    uninstall: "/api/integrations/agents/uninstall",
  },
  mattermost: {
    disable: "/api/integrations/mattermost/disable",
    enable: "/api/integrations/mattermost/enable",
    uninstall: "/api/integrations/mattermost/uninstall",
    purge: "/api/integrations/mattermost/purge",
  },
} as const;

const BLOCKED_ACTIONS = {
  agents_must_be_disabled: {
    action: "disable",
    required_action: "disable",
  },
  agents_must_be_uninstalled: {
    action: "uninstall",
    required_action: "uninstall",
  },
} as const;

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function boundedText(value: unknown): value is string {
  return typeof value === "string"
    && value.length > 0
    && value.length <= 240
    && !Array.from(value).some((character) => character.charCodeAt(0) < 32);
}

export function lifecycleActions(
  integration: IntegrationLifecycleId,
  value: unknown,
): IntegrationLifecycleAction[] {
  if (!Array.isArray(value)) return [];
  const declared = new Set(value.filter((item): item is IntegrationLifecycleAction => (
    typeof item === "string"
    && LIFECYCLE_ACTION_ORDER.includes(item as IntegrationLifecycleAction)
    && SUPPORTED_ACTIONS[integration].has(item as IntegrationLifecycleAction)
  )));
  return LIFECYCLE_ACTION_ORDER.filter((action) => declared.has(action));
}

export function lifecycleBlockedActions(value: unknown): IntegrationBlockedAction[] {
  if (!Array.isArray(value)) return [];
  const accepted: IntegrationBlockedAction[] = [];
  const seen = new Set<string>();
  for (const candidate of value) {
    const item = record(candidate);
    if (!item || typeof item.dependency_code !== "string") continue;
    const contract = BLOCKED_ACTIONS[item.dependency_code as keyof typeof BLOCKED_ACTIONS];
    if (
      !contract
      || item.action !== contract.action
      || item.required_action !== contract.required_action
      || item.route !== "/integrations#ai-agents"
      || !boundedText(item.message)
      || seen.has(item.dependency_code)
    ) continue;
    seen.add(item.dependency_code);
    accepted.push({
      action: contract.action,
      dependency_code: item.dependency_code as IntegrationBlockedAction["dependency_code"],
      message: item.message,
      required_action: contract.required_action,
      route: "/integrations#ai-agents",
    });
  }
  return accepted;
}

export function lifecycleWarnings(value: unknown): IntegrationLifecycleWarning[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((candidate) => {
    const item = record(candidate);
    return item?.code === "agent_bot_cleanup_failed" && boundedText(item.message)
      ? [{ code: "agent_bot_cleanup_failed" as const, message: item.message }]
      : [];
  }).slice(0, 8);
}

export function lifecycleContractFields(
  integration: IntegrationLifecycleId,
  value: {
    allowed_actions?: unknown;
    blocked_actions?: unknown;
    warnings?: unknown;
  },
): Pick<IntegrationLifecycleStatus, "allowed_actions" | "blocked_actions" | "warnings"> {
  return {
    allowed_actions: lifecycleActions(integration, value.allowed_actions),
    blocked_actions: lifecycleBlockedActions(value.blocked_actions),
    warnings: lifecycleWarnings(value.warnings),
  };
}

export function lifecycleNavigationTarget(value: unknown): {
  path: "/integrations";
  anchor: "ai-agents";
} | null {
  const item = record(value);
  return item?.route === "/integrations#ai-agents"
    ? { path: "/integrations", anchor: "ai-agents" }
    : null;
}

export function lifecycleMutationRoute(
  integration: IntegrationLifecycleId,
  action: IntegrationLifecycleAction,
  cleanupAction?: IntegrationLifecycleAction | null,
): string | null {
  const selected = action === "retry_cleanup" ? cleanupAction : action;
  if (!selected) return null;
  const routes = MUTATION_ROUTES[integration] as Partial<Record<IntegrationLifecycleAction, string>>;
  return routes[selected] ?? null;
}
