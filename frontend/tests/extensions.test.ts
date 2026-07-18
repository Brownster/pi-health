import assert from "node:assert/strict";
import test from "node:test";

import type { ExtensionDescriptor } from "../src/lib/capabilities.ts";
import {
  capabilitySurfaceLink,
  extensionUpdateLabel,
  extensionLifecycleActions,
  groupExtensions,
  healthTone,
  humanizeCapabilityId,
} from "../src/lib/extensions.ts";

function extension(
  id: string,
  name: string,
  capabilityId?: string,
): ExtensionDescriptor {
  return {
    id,
    name,
    description: `${name} provider`,
    version: "1.0.0",
    runtime_kind: "builtin-python",
    source: "builtin",
    installed: true,
    enabled: true,
    contract_state: "valid",
    compatibility: "compatible",
    health: { state: "healthy", message: "Ready", counts: { healthy: 1 } },
    capabilities: capabilityId
      ? [
          {
            id: capabilityId,
            provider_id: id,
            surface: "pools",
            operational: true,
            status: {
              schema_version: "1",
              provider_id: id,
              capability_id: capabilityId,
              observed_at: "2026-07-17T10:00:00Z",
              lifecycle: {
                installed: true,
                enabled: true,
                configured: true,
                compatibility: "compatible",
                availability: "available",
              },
              health: { state: "healthy", message: "Ready", issues: [] },
              summary: [],
              metrics: [],
              recent_activity: [],
              details: {},
            },
          },
        ]
      : [],
  };
}

test("extensions group by primary capability with other providers last", () => {
  const groups = groupExtensions([
    extension("zfs", "ZFS", "storage.pooling"),
    extension("other", "Other"),
    extension("mergerfs", "MergerFS", "storage.pooling"),
    extension("mattermost", "Mattermost", "integration.chat"),
  ]);

  assert.deepEqual(groups.map((group) => group.id), [
    "integration.chat",
    "storage.pooling",
    "other",
  ]);
  assert.deepEqual(groups[1].extensions.map((item) => item.name), ["MergerFS", "ZFS"]);
  assert.equal(groups[2].label, "Other capabilities");
});

test("capability links expose only currently owned domain pages", () => {
  assert.equal(capabilitySurfaceLink("pools"), "/pools");
  assert.equal(capabilitySurfaceLink("integrations"), "/integrations");
  assert.equal(capabilitySurfaceLink("protection"), "/protection");
  assert.equal(capabilitySurfaceLink("unknown"), null);
  assert.equal(humanizeCapabilityId("storage.remote_mount"), "Storage remote mount");
});

test("health and update labels remain bounded", () => {
  const provider = extension("mergerfs", "MergerFS", "storage.pooling");
  assert.equal(healthTone("healthy"), "success");
  assert.equal(healthTone("unconfigured"), "warning");
  assert.equal(healthTone("incompatible"), "danger");
  assert.equal(extensionUpdateLabel(provider), "not reported");
  assert.equal(extensionUpdateLabel({ ...provider, update_state: "available" }), "update available");
});

test("lifecycle actions follow the package runtime and state", () => {
  const builtin = extension("mergerfs", "MergerFS", "storage.pooling");
  const github = {
    ...extension("openpool", "OpenPool", "storage.pooling"),
    runtime_kind: "github-python",
    source: "owner/openpool",
    enabled: false,
  };
  const integration = {
    ...extension("mattermost", "Mattermost", "integration.chat"),
    runtime_kind: "integration-adapter",
  };

  assert.deepEqual(extensionLifecycleActions(builtin), ["disable"]);
  assert.deepEqual(extensionLifecycleActions(github), ["enable", "update", "repair", "remove"]);
  assert.deepEqual(extensionLifecycleActions(integration), []);
});
