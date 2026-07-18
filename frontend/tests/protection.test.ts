import assert from "node:assert/strict";
import test from "node:test";

import type { CapabilityDescriptor, CapabilityStatus } from "../src/lib/capabilities.ts";
import {
  adaptLegacyProtectionProviders,
  enrichProtectionCapability,
  protectionCapabilityView,
} from "../src/lib/protection-capabilities.ts";
import type { PluginDetail, StoragePlugin } from "../src/lib/storage-plugins.ts";

function protectionStatus(providerId: string, configured = true): CapabilityStatus {
  return {
    schema_version: "1",
    provider_id: providerId,
    capability_id: "storage.protection",
    observed_at: "2026-07-18T12:00:00Z",
    lifecycle: {
      installed: true,
      enabled: true,
      configured,
      compatibility: "compatible",
      availability: "available",
    },
    health: { state: configured ? "warning" : "unconfigured", message: "Sync required.", issues: [] },
    summary: [],
    metrics: [],
    recent_activity: [],
    details: {
      protection_sets: configured ? [{
        name: "media parity",
        kind: "parity",
        protected_targets: 3,
        unprotected_targets: 1,
        parity_targets: 1,
        last_success_at: "2026-07-18T10:00:00Z",
        next_run_at: "2026-07-19T03:00:00Z",
        sync_required: true,
      }] : [],
    },
  };
}

test("protection view separates configured, setup, and available providers", () => {
  const configured = protectionStatus("backup");
  const setup = protectionStatus("snapshots", false);
  const disabled = protectionStatus("replica", false);
  const capability: CapabilityDescriptor = {
    id: "storage.protection",
    surface: "protection",
    providers: [
      { id: "backup", name: "Backup", enabled: true, operational: false, status: configured },
      { id: "snapshots", name: "Snapshots", enabled: true, operational: false, status: setup },
      { id: "replica", name: "Replica", enabled: false, operational: false, status: { ...disabled, lifecycle: { ...disabled.lifecycle, enabled: false }, health: { state: "disabled", message: "Disabled", issues: [] } } },
    ],
  };

  const view = protectionCapabilityView(capability);

  assert.deepEqual(view.configuredProviders.map((provider) => provider.id), ["backup"]);
  assert.deepEqual(view.setupProviders.map((provider) => provider.id), ["snapshots"]);
  assert.deepEqual(view.availableProviders.map((provider) => provider.id), ["replica"]);
  assert.equal(view.summary.totalSets, 1);
  assert.equal(view.summary.protectedTargets, 3);
  assert.equal(view.summary.unprotectedTargets, 1);
  assert.equal(view.summary.warnings, 1);
  assert.equal(view.summary.latestRunAt, "2026-07-18T10:00:00Z");
  assert.equal(view.protectionSets[0].requiredAction, "Sync required");
});

test("legacy adapter exposes only SnapRAID and preserves known protection state", () => {
  const plugins: StoragePlugin[] = [
    { id: "mergerfs", name: "MergerFS", description: "Pool", version: "1", installed: true, enabled: true, configured: true, status: "ok", status_message: "Ready", category: "storage", kind: "pool", type: "builtin" },
    { id: "snapraid", name: "SnapRAID", description: "Parity", version: "1", installed: true, enabled: true, configured: true, status: "degraded", status_message: "Sync required", category: "storage", kind: "pool", type: "builtin" },
  ];
  const details: Record<string, PluginDetail | null> = {
    snapraid: {
      id: "snapraid", name: "SnapRAID", description: "Parity", installed: true, kind: "pool",
      status: { status: "degraded", message: "Sync required", details: { data_drives: 2, parity_drives: 1, sync_required: true, last_run_at: "2026-07-18T09:00:00Z" } },
      commands: [], schema: {},
      config: { enabled: true, drives: [], schedule: { sync_enabled: true, sync_cron: "0 3 * * *" } },
    },
  };

  const capability = adaptLegacyProtectionProviders(plugins, details, "2026-07-18T12:00:00Z");
  const view = protectionCapabilityView(capability);

  assert.deepEqual(capability.providers.map((provider) => provider.id), ["snapraid"]);
  assert.equal(view.protectionSets[0].protectedTargets, 2);
  assert.equal(view.protectionSets[0].parityTargets, 1);
  assert.equal(view.protectionSets[0].unprotectedTargets, null);
  assert.equal(view.protectionSets[0].schedule, "0 3 * * *");
  assert.equal(view.protectionSets[0].requiredAction, "Sync required");
});

test("registry status keeps ownership while legacy details fill an adapter gap", () => {
  const registryStatus = protectionStatus("snapraid");
  registryStatus.details = {};
  const legacyStatus = protectionStatus("snapraid");
  const merged = enrichProtectionCapability(
    { id: "storage.protection", surface: "protection", providers: [{ id: "snapraid", name: "SnapRAID", enabled: true, operational: true, status: registryStatus }] },
    { id: "storage.protection", surface: "protection", providers: [{ id: "snapraid", name: "SnapRAID", enabled: true, operational: true, source: "legacy", status: legacyStatus }] },
  );

  assert.deepEqual((merged.providers[0].status as CapabilityStatus).details, legacyStatus.details);
  assert.equal(merged.providers[0].source, undefined);
});

test("legacy adapter does not invent a zero-drive set when detail is unavailable", () => {
  const plugins: StoragePlugin[] = [{
    id: "snapraid", name: "SnapRAID", description: "Parity", version: "1",
    installed: true, enabled: true, configured: true, status: "healthy",
    status_message: "Protected", category: "storage", kind: "pool", type: "builtin",
  }];

  const capability = adaptLegacyProtectionProviders(
    plugins,
    { snapraid: null },
    "2026-07-18T12:00:00Z",
  );
  const view = protectionCapabilityView(capability);

  assert.equal(view.protectionSets.length, 0);
  assert.equal(view.configuredProviders[0].status.lifecycle.availability, "unknown");
  assert.equal(view.summary.protectedTargets, null);
});
