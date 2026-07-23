import type {
  AgentAction,
  AgentFinding,
  AgentFindingContent,
  AgentSchedule,
  AgentScheduleInput,
  AgentScheduleUpdate,
  AgentRepairSchedule,
  AgentRepairScheduleInput,
  AgentRepairScheduleUpdate,
} from "./agent-operations";

const REPORT_ONLY_BUDGETS = {
  max_reports: 1,
  max_actions: 0,
  max_downtime_seconds: 0,
  max_retries: 0,
  max_model_invocations: 0,
} as const;

export function newAgentSchedule(): AgentScheduleInput {
  return {
    name: "",
    enabled: true,
    checks: [{ operation: "system.status", params: {} }],
    window: {
      cron: "0 7 * * *",
      timezone: "Europe/London",
      duration_minutes: 30,
    },
    budgets: { max_checks: 1, ...REPORT_ONLY_BUDGETS },
    delivery: { channel: "mattermost-alerts", mode: "immediate" },
  };
}

export function editableSchedule(schedule: AgentSchedule): AgentScheduleUpdate {
  return {
    name: schedule.name,
    enabled: schedule.enabled,
    checks: schedule.checks.map((check) => ({
      operation: check.operation,
      params: { ...check.params },
    })),
    window: { ...schedule.window },
    budgets: { ...schedule.budgets },
    delivery: { ...schedule.delivery },
    revision: schedule.revision,
  };
}

export function scheduleReady(schedule: AgentScheduleInput): boolean {
  return Boolean(
    schedule.name.trim()
      && schedule.checks.length >= 1
      && schedule.checks.length <= 12
      && schedule.checks.every((check) => (
        check.operation
        && Object.values(check.params).every((value) => value.trim())
      ))
      && schedule.window.cron.trim()
      && schedule.window.timezone.trim()
      && Number.isInteger(schedule.window.duration_minutes)
      && schedule.window.duration_minutes >= 1
      && schedule.window.duration_minutes <= 1440,
  );
}

export function newAgentRepairSchedule(): AgentRepairScheduleInput {
  return {
    name: "Recover get_iplayer",
    enabled: false,
    operation: "container.restart",
    params: { name: "get_iplayer" },
    service_priority: "normal",
    window: {
      cron: "0 2 * * *",
      timezone: "Europe/London",
      duration_minutes: 60,
    },
    delivery: { channel: "mattermost-alerts", mode: "threaded" },
  };
}

export function editableRepairSchedule(
  schedule: AgentRepairSchedule,
): AgentRepairScheduleUpdate {
  return {
    name: schedule.name,
    enabled: schedule.enabled,
    operation: schedule.operation,
    params: { ...schedule.params },
    service_priority: schedule.service_priority,
    window: { ...schedule.window },
    delivery: { ...schedule.delivery },
    revision: schedule.revision,
  };
}

export function repairScheduleReady(
  schedule: AgentRepairScheduleInput,
): boolean {
  return Boolean(
    schedule.name.trim()
      && schedule.operation === "container.restart"
      && schedule.params.name === "get_iplayer"
      && schedule.window.cron.trim()
      && schedule.window.timezone.trim()
      && Number.isInteger(schedule.window.duration_minutes)
      && schedule.window.duration_minutes >= 1
      && schedule.window.duration_minutes <= 1440,
  );
}

export function editableFinding(finding: AgentFinding): AgentFindingContent {
  return {
    kind: finding.kind,
    title: finding.title,
    summary: finding.summary,
    component: finding.component,
    affected_version: finding.affected_version,
    expected_behavior: finding.expected_behavior,
    actual_behavior: finding.actual_behavior,
    reproduction_steps: [...finding.reproduction_steps],
    impact: finding.impact,
    frequency: finding.frequency,
    workaround: finding.workaround,
    confidence: finding.confidence,
    acceptance_criteria: [...finding.acceptance_criteria],
    source_type: finding.source_type,
  };
}

export function actionCanBeApproved(action: AgentAction): boolean {
  return action.state === "awaiting_approval" && action.authority_mode === "approval";
}

export function actionCanBeAttested(action: AgentAction): boolean {
  return action.state === "succeeded"
    && action.terminal_code === "verified"
    && action.risk === "R1"
    && action.trigger === "interactive"
    && action.authority_mode === "approval"
    && !action.events?.some((event) => event.phase === "canary_attested");
}

export function actionCanBeRejected(action: AgentAction): boolean {
  return action.state === "proposed" || action.state === "awaiting_approval";
}

export function actionCanBeCancelled(action: AgentAction): boolean {
  return ["proposed", "awaiting_approval", "authorised"].includes(action.state);
}
