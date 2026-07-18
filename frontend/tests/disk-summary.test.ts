import assert from "node:assert/strict";
import test from "node:test";

import { mergeDiskSummaryHealth, normalizeDiskSummary } from "../src/lib/disk-summary.ts";


test("normalizes the CP-010 disk summary contract", () => {
  const result = normalizeDiskSummary({
    state: "attention",
    counts: {total: 2, healthy: 1, warning: 1, assigned: 1, unassigned: 1, unused: 0},
    capacity: {
      mounted_total_bytes: 1000,
      mounted_used_bytes: 400,
      mounted_available_bytes: 600,
      mounted_percent: 40,
    },
    sources: {inventory: "available", smart: "available", assignments: "degraded"},
    devices: [
      {
        name: "sda",
        path: "/dev/sda",
        health: "warning",
        temperature_c: 57,
        mounted: true,
        mounted_capacity: {mounted_total_bytes: 1000},
        assignments: [{provider_id: "snapraid", role: "data", device_path: "/dev/sda1"}],
      },
    ],
    warnings: [{code: "provider_config_invalid", source: "mergerfs", message: "Unavailable"}],
    collected_at: "2026-07-18T12:30:00Z",
  });

  assert.equal(result.state, "attention");
  assert.equal(result.counts.total, 2);
  assert.equal(result.counts.failing, 0);
  assert.equal(result.capacity.mounted_percent, 40);
  assert.equal(result.devices[0]?.health, "warning");
  assert.equal(result.devices[0]?.assignments[0]?.provider_id, "snapraid");
  assert.equal(result.sources.assignments, "degraded");
});

test("malformed data fails closed instead of reporting healthy zeroes", () => {
  const result = normalizeDiskSummary({
    state: "healthy-ish",
    counts: {total: "3", assigned: "0"},
    sources: {inventory: "maybe"},
    devices: [{health: "excellent", mounted: "yes"}],
  });

  assert.equal(result.state, "unavailable");
  assert.equal(result.counts.total, 0);
  assert.equal(result.counts.assigned, null);
  assert.equal(result.sources.inventory, "unavailable");
  assert.equal(result.sources.smart, "unavailable");
  assert.equal(result.devices[0]?.health, "unknown");
  assert.equal(result.devices[0]?.mounted, false);
});

test("merges independently loaded SMART health into an embedded summary", () => {
  const summary = normalizeDiskSummary({
    state: "attention",
    counts: {total: 2, unknown: 2, mounted: 1, unmounted: 1},
    capacity: {mounted_total_bytes: 1000, mounted_used_bytes: 400, mounted_available_bytes: 600},
    sources: {inventory: "available", smart: "not_checked", assignments: "available"},
    devices: [
      {name: "sda", path: "/dev/sda", health: "unknown", assignments: []},
      {name: "sdb", path: "/dev/sdb", health: "unknown", assignments: []},
    ],
  });

  const merged = mergeDiskSummaryHealth(summary, {
    "/dev/sda": {health_status: "healthy", temperature_c: 38},
    "/dev/sdb": {health_status: "warning", temperature_c: 56},
  });

  assert.equal(merged.state, "attention");
  assert.equal(merged.sources.smart, "available");
  assert.equal(merged.counts.healthy, 1);
  assert.equal(merged.counts.warning, 1);
  assert.equal(merged.counts.unknown, 0);
  assert.equal(merged.devices[0]?.temperature_c, 38);
});
