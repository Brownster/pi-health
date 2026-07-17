import assert from "node:assert/strict";
import test from "node:test";

import type {
  CapabilityActionParameter,
  CapabilitySetupSchema,
  CapabilityStatus,
} from "../src/lib/capabilities.ts";
import {
  actionParameterChoices,
  deserializeChoice,
  groupSetupFields,
  initialActionRunState,
  metricPercent,
  reduceActionEvent,
  serializeChoice,
  setupInitialValues,
  validateSetupValues,
} from "../src/lib/capability-renderer.ts";

const schema: CapabilitySetupSchema = {
  schema_version: "1",
  schema_id: "test-provider-v1",
  title: "Provider setup",
  fields: [
    { key: "name", label: "Name", type: "text", required: true, max_length: 8 },
    { key: "count", label: "Count", type: "integer", required: true, minimum: 1, maximum: 4 },
    {
      key: "mode",
      label: "Mode",
      type: "select",
      required: true,
      default: 2,
      choices: [
        { value: 1, label: "One" },
        { value: 2, label: "Two" },
      ],
    },
    { key: "enabled", label: "Enabled", type: "boolean", required: false },
    { key: "advanced.path", label: "Path", type: "path", required: false },
  ],
  sections: [{ id: "general", label: "General", fields: ["name", "count", "mode", "enabled"] }],
};

const status: CapabilityStatus = {
  schema_version: "1",
  provider_id: "test-provider",
  capability_id: "storage.pooling",
  observed_at: "2026-07-17T10:00:00Z",
  lifecycle: {
    installed: true,
    enabled: true,
    configured: true,
    compatibility: "compatible",
    availability: "available",
  },
  health: { state: "healthy", message: "Ready", issues: [] },
  summary: [{ id: "pools", label: "Pools", value: 2, tone: "neutral" }],
  metrics: [],
  recent_activity: [],
  details: {
    pools: [
      { name: "media", mounted: true },
      { name: "archive", mounted: false },
    ],
  },
};

test("setup defaults remain flat and preserve scalar choice types", () => {
  assert.deepEqual(setupInitialValues(schema, { name: "media" }), {
    name: "media",
    count: "",
    mode: 2,
    enabled: false,
    "advanced.path": "",
  });
  const token = serializeChoice(2);
  assert.equal(deserializeChoice(token, schema.fields[2].choices ?? []), 2);
  assert.equal(deserializeChoice("unknown", schema.fields[2].choices ?? []), "");
});

test("setup sections reference existing fields without creating nested values", () => {
  const groups = groupSetupFields(schema);
  assert.deepEqual(groups.map((group) => group.id), ["general", "configuration"]);
  assert.deepEqual(groups[1].fields.map((field) => field.key), ["advanced.path"]);
});

test("setup validation coerces numbers and reports bounded field errors", () => {
  const valid = validateSetupValues(schema.fields, {
    name: "media",
    count: "3",
    mode: 2,
    enabled: true,
  });
  assert.deepEqual(valid.errors, []);
  assert.equal(valid.values.count, 3);

  const invalid = validateSetupValues(
    [{ ...schema.fields[0], pattern: "(a+)+$" }, schema.fields[1], schema.fields[2]],
    { name: "too-long-name", count: "2.5", mode: "2" },
  );
  assert.deepEqual(invalid.errors.map((error) => error.code), [
    "above_max_length",
    "invalid_integer",
    "invalid_choice",
  ]);
});

test("dynamic action choices only read bounded status paths", () => {
  const parameter: CapabilityActionParameter = {
    name: "pool",
    label: "Pool",
    type: "select",
    required: true,
    source: "status.details.pools[].name",
  };
  assert.deepEqual(actionParameterChoices(parameter, status), [
    { value: "media", label: "media" },
    { value: "archive", label: "archive" },
  ]);
  assert.deepEqual(
    actionParameterChoices({ ...parameter, source: "status.details.__proto__.value" }, status),
    [],
  );
  assert.deepEqual(
    actionParameterChoices({ ...parameter, source: "status.summary.pools" }, status),
    [{ value: 2, label: "2" }],
  );
});

test("metrics normalize explicit ranges and reject invalid ranges", () => {
  assert.equal(metricPercent(75, 50, 100), 50);
  assert.equal(metricPercent(200, 0, 100), 100);
  assert.equal(metricPercent(1, 1, 1), null);
});

test("action progress accepts one operation and monotonic events", () => {
  const running = reduceActionEvent(initialActionRunState(), {
    schema_version: "1",
    operation_id: "op-1",
    sequence: 0,
    type: "progress",
    percent: 25,
    message: "Starting",
  });
  const stale = reduceActionEvent(running, {
    schema_version: "1",
    operation_id: "op-1",
    sequence: 0,
    type: "error",
    message: "stale",
  });
  const foreign = reduceActionEvent(running, {
    schema_version: "1",
    operation_id: "op-2",
    sequence: 1,
    type: "error",
    message: "foreign",
  });
  const complete = reduceActionEvent(running, {
    schema_version: "1",
    operation_id: "op-1",
    sequence: 1,
    type: "complete",
    success: true,
    message: "Done",
  });

  assert.equal(running.percent, 25);
  assert.equal(stale, running);
  assert.equal(foreign, running);
  assert.equal(complete.phase, "complete");
  assert.equal(complete.percent, 100);
});

test("action output is bounded by line count and message size", () => {
  let state = initialActionRunState();
  for (let sequence = 0; sequence < 220; sequence += 1) {
    state = reduceActionEvent(state, {
      schema_version: "1",
      operation_id: "op-1",
      sequence,
      type: "output",
      message: "x".repeat(3_000),
    });
  }
  assert.ok(state.output.length <= 200);
  assert.ok(state.output.every((line) => line.length <= 2_000));
  assert.ok(state.output.reduce((total, line) => total + line.length, 0) <= 64 * 1024);
});
