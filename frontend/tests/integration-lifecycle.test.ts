import assert from "node:assert/strict";
import test from "node:test";

import {
  lifecycleActions,
  lifecycleBlockedActions,
  lifecycleCleanupOperation,
  lifecycleContractFields,
  lifecycleMutationRoute,
  lifecycleNavigationTarget,
  lifecycleWarnings,
} from "../src/lib/integration-lifecycle-contract.ts";

test("lifecycle actions keep only known integration actions in fixed order", () => {
  assert.deepEqual(
    lifecycleActions("agents", ["uninstall", "unknown", "disable", "purge", "disable"]),
    ["disable", "uninstall"],
  );
  assert.deepEqual(
    lifecycleActions("mattermost", ["purge", "authenticate", "setup"]),
    ["setup", "purge"],
  );
  assert.deepEqual(lifecycleActions("agents", "disable"), []);
});

test("blocked actions accept only the frozen dependency and internal route", () => {
  const valid = {
    action: "disable",
    dependency_code: "agents_must_be_disabled",
    message: "Disable AI Agents before stopping Mattermost.",
    required_action: "disable",
    route: "/integrations#ai-agents",
  };
  assert.deepEqual(lifecycleBlockedActions([
    valid,
    { ...valid, route: "https://example.invalid" },
    { ...valid, route: "/settings" },
    { ...valid, dependency_code: "unknown" },
  ]), [valid]);
  assert.deepEqual(lifecycleNavigationTarget(valid), {
    path: "/integrations",
    anchor: "ai-agents",
  });
  assert.equal(lifecycleNavigationTarget({ ...valid, route: "//example.invalid" }), null);
});

test("mutation routes cannot be supplied or inferred outside the fixed catalog", () => {
  assert.equal(lifecycleMutationRoute("agents", "disable"), "/api/integrations/agents/disable");
  assert.equal(lifecycleMutationRoute("agents", "purge"), null);
  assert.equal(
    lifecycleMutationRoute("mattermost", "retry_cleanup", "uninstall"),
    "/api/integrations/mattermost/uninstall",
  );
  assert.equal(lifecycleMutationRoute("mattermost", "retry_cleanup", "setup"), null);
});

test("warnings keep only the bounded frozen catalog entry", () => {
  assert.deepEqual(lifecycleWarnings([
    {
      code: "agent_bot_cleanup_failed",
      message: "AI Agents was removed locally, but the Mattermost bot could not be removed.",
    },
    { code: "unknown", message: "Unknown warning" },
    { code: "agent_bot_cleanup_failed", message: "line\nbreak" },
  ]), [
    {
      code: "agent_bot_cleanup_failed",
      message: "AI Agents was removed locally, but the Mattermost bot could not be removed.",
    },
  ]);
});

test("status contract fields are normalized together at the API boundary", () => {
  const fields = lifecycleContractFields("mattermost", {
    allowed_actions: ["uninstall", "authenticate", "disable"],
    blocked_actions: [
      {
        action: "disable",
        dependency_code: "agents_must_be_disabled",
        message: "Disable AI Agents before stopping Mattermost.",
        required_action: "disable",
        route: "https://example.invalid",
      },
    ],
    warnings: [{ code: "agent_bot_cleanup_failed", message: "Remote cleanup failed." }],
    cleanup_operation: {
      id: "agent-cleanup-1",
      action: "uninstall",
      state: "failed",
      started_at: "2026-07-21T10:00:00Z",
      updated_at: "2026-07-21T10:01:00Z",
      retryable: true,
    },
  });

  assert.deepEqual(fields, {
    allowed_actions: ["disable", "uninstall"],
    blocked_actions: [],
    cleanup_operation: {
      id: "agent-cleanup-1",
      action: "uninstall",
      state: "failed",
      started_at: "2026-07-21T10:00:00Z",
      updated_at: "2026-07-21T10:01:00Z",
      retryable: true,
    },
    warnings: [{ code: "agent_bot_cleanup_failed", message: "Remote cleanup failed." }],
  });
});

test("cleanup operations reject actions without a fixed retry route", () => {
  const operation = {
    id: "cleanup-1",
    action: "setup",
    state: "failed",
    started_at: "2026-07-21T10:00:00Z",
    updated_at: "2026-07-21T10:01:00Z",
    retryable: true,
  };
  assert.equal(lifecycleCleanupOperation("agents", operation), null);
  assert.equal(lifecycleCleanupOperation("agents", { ...operation, action: "disable" })?.action, "disable");
});
