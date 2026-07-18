import assert from "node:assert/strict";
import test from "node:test";

import type { CapabilityDescriptor, CapabilityStatus } from "../src/lib/capabilities.ts";
import {
  adaptLegacyPoolingProviders,
  poolCapabilityView,
} from "../src/lib/pool-capabilities.ts";
import type { PluginDetail, StoragePlugin } from "../src/lib/storage-plugins.ts";

function status(providerId: string, configured = true): CapabilityStatus {
  return {
    schema_version: "1",
    provider_id: providerId,
    capability_id: "storage.pooling",
    observed_at: "2026-07-18T12:00:00Z",
    lifecycle: {
      installed: true,
      enabled: true,
      configured,
      compatibility: "compatible",
      availability: "available",
    },
    health: { state: configured ? "warning" : "unconfigured", message: "One pool needs attention.", issues: [] },
    summary: [],
    metrics: [],
    recent_activity: [{ id: "mount", occurred_at: "2026-07-18T11:55:00Z", kind: "warning", summary: "Archive mount failed." }],
    details: {
      pools: [
        {
          name: "media",
          mount_point: "/mnt/media",
          mounted: true,
          branches: ["/mnt/disk1", "/mnt/disk2"],
          policy: "epmfs",
          total_bytes: 4_000,
          free_bytes: 1_500,
          used_percent: 62.5,
        },
        { name: "archive", mount_point: "/mnt/archive", mounted: false, branches: 1 },
      ],
    },
  };
}

test("pool capability view separates enabled operation from available providers", () => {
  const capability: CapabilityDescriptor = {
    id: "storage.pooling",
    surface: "pools",
    providers: [
      { id: "mergerfs", name: "MergerFS", enabled: true, operational: true, status: status("mergerfs") },
      { id: "openpool", name: "OpenPool", enabled: false, operational: false, status: { ...status("openpool", false), lifecycle: { ...status("openpool", false).lifecycle, enabled: false }, health: { state: "disabled", message: "Provider is disabled.", issues: [] } } },
    ],
  };

  const view = poolCapabilityView(capability);

  assert.deepEqual(view.enabledProviders.map((provider) => provider.id), ["mergerfs"]);
  assert.deepEqual(view.availableProviders.map((provider) => provider.id), ["openpool"]);
  assert.deepEqual(view.pools.map((pool) => pool.name), ["archive", "media"]);
  assert.equal(view.summary.totalPools, 2);
  assert.equal(view.summary.mountedPools, 1);
  assert.equal(view.summary.totalBytes, 4_000);
  assert.equal(view.summary.freeBytes, 1_500);
  assert.equal(view.summary.warnings, 1);
  assert.equal(view.pools[1].branchCount, 2);
  assert.equal(view.pools[1].policy, "epmfs");
  assert.equal(view.pools[1].recentAction, null);
});

test("legacy adapter exposes only MergerFS as pooling and preserves configuration", () => {
  const plugins: StoragePlugin[] = [
    { id: "mergerfs", name: "MergerFS", description: "Pool", version: "1", installed: true, enabled: true, configured: true, status: "ok", status_message: "Ready", category: "storage", kind: "pool", type: "builtin" },
    { id: "snapraid", name: "SnapRAID", description: "Protection", version: "1", installed: true, enabled: true, configured: true, status: "healthy", status_message: "Protected", category: "storage", kind: "pool", type: "builtin" },
  ];
  const details: Record<string, PluginDetail | null> = {
    mergerfs: {
      id: "mergerfs",
      name: "MergerFS",
      description: "Pool",
      installed: true,
      kind: "pool",
      status: { status: "ok", message: "Ready", details: status("mergerfs").details },
      commands: [],
      schema: {},
      config: { pools: [{ name: "media" }] },
    },
  };

  const capability = adaptLegacyPoolingProviders(plugins, details, "2026-07-18T12:00:00Z");
  const view = poolCapabilityView(capability);

  assert.deepEqual(capability.providers.map((provider) => provider.id), ["mergerfs"]);
  assert.deepEqual(view.pools.map((pool) => pool.name), ["archive", "media"]);
  assert.equal(view.enabledProviders[0].source, "legacy");
});
