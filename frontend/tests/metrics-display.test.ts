import assert from "node:assert/strict";
import test from "node:test";

import {
  formatBytes,
  formatDuration,
  formatPercent,
  formatRate,
} from "../src/lib/format.ts";
import {
  isMemoryAccountingUnavailable,
  type ContainerMemoryReading,
} from "../src/lib/container-metrics.ts";

function container(overrides: Partial<ContainerMemoryReading> = {}): ContainerMemoryReading {
  return { status: "running", memory_used: null, ...overrides };
}

test("an unknown reading renders as unknown, never as zero", () => {
  // Number(null) is 0, which used to turn "no data" into a convincing 0.0% / 0 B.
  assert.equal(formatPercent(null), "—");
  assert.equal(formatPercent(undefined), "—");
  assert.equal(formatBytes(null), "—");
  assert.equal(formatBytes(undefined), "—");
  assert.equal(formatRate(null), "—");
  assert.equal(formatDuration(null), "—");
});

test("a real zero still renders as zero", () => {
  assert.equal(formatPercent(0), "0.0%");
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatRate(0), "0 B/s");
  assert.equal(formatDuration(0), "0s");
});

test("values format at human scale", () => {
  assert.equal(formatPercent(12.34), "12.3%");
  assert.equal(formatPercent(12.34, 0), "12%");
  assert.equal(formatBytes(1536), "1.5 KB");
  assert.equal(formatRate(2 * 1024 * 1024), "2.0 MB/s");
  assert.equal(formatDuration(45), "45s");
  assert.equal(formatDuration(90 * 60), "1h 30m");
  assert.equal(formatDuration(3 * 86_400 + 4 * 3_600), "3d 4h");
});

test("NaN and negative byte counts are treated as unknown", () => {
  assert.equal(formatPercent(Number.NaN), "—");
  assert.equal(formatBytes(Number.POSITIVE_INFINITY), "—");
  assert.equal(formatBytes(-1), "—");
});

test("memory accounting is flagged off only when every running container reports nothing", () => {
  assert.equal(
    isMemoryAccountingUnavailable([container(), container()]),
    true,
  );
  assert.equal(
    isMemoryAccountingUnavailable([container(), container({ memory_used: 1024 })]),
    false,
  );
});

test("a host with no running containers is not reported as missing accounting", () => {
  assert.equal(isMemoryAccountingUnavailable([]), false);
  assert.equal(isMemoryAccountingUnavailable([container({ status: "exited" })]), false);
});
