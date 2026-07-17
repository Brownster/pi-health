import assert from "node:assert/strict";
import test from "node:test";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";


test("generic renderer emits accessible bounded status, setup, and action tools", async () => {
  const vite = await createServer({ appType: "custom", server: { middlewareMode: true } });
  try {
    const { GenericCapabilityRenderer } = await vite.ssrLoadModule(
      "/src/components/capabilities/generic-capability-renderer.tsx",
    );
    const status = {
      schema_version: "1",
      provider_id: "unionfs-provider",
      capability_id: "storage.pooling",
      observed_at: "2026-07-17T10:00:00Z",
      lifecycle: {
        installed: true,
        enabled: true,
        configured: true,
        compatibility: "compatible",
        availability: "available",
      },
      health: {
        state: "warning",
        message: "One pool needs attention.",
        issues: [
          {
            code: "pool_unavailable",
            severity: "warning",
            message: "Archive pool is unavailable.",
          },
        ],
      },
      summary: [{ id: "pools", label: "Pools", value: "1/2", tone: "warning" }],
      metrics: [{ id: "used", label: "Used", value: 63, unit: "%", minimum: 0, maximum: 100 }],
      recent_activity: [],
      details: { raw_secret: "must-not-render", pools: [{ name: "archive" }] },
    };
    const setup = {
      schema_version: "1",
      schema_id: "unionfs-pool-v1",
      title: "Configure pool provider",
      fields: [
        { key: "pool_name", label: "Pool name", type: "text", required: true },
        {
          key: "credential_ref",
          label: "Credential",
          type: "secret_reference",
          required: false,
        },
      ],
    };
    const actions = {
      schema_version: "1",
      provider_id: "unionfs-provider",
      capability_id: "storage.pooling",
      actions: [
        {
          id: "mount",
          label: "Mount pool",
          intent: "mutation",
          permission: "capability.operate",
          timeout_seconds: 60,
          parameters: [],
          confirmation: {
            title: "Mount pool?",
            message: "Mount the saved pool.",
            confirm_label: "Mount",
          },
          result_mode: "stream",
        },
        {
          id: "inspect",
          label: "Inspect pool",
          intent: "diagnostic",
          permission: "capability.diagnose",
          timeout_seconds: 30,
          parameters: [],
          result_mode: "immediate",
        },
        {
          id: "unmount",
          label: "Unmount pool",
          intent: "mutation",
          permission: "capability.operate",
          timeout_seconds: 60,
          parameters: [],
          result_mode: "stream",
        },
      ],
      availability: [
        { id: "mount", available: false, unavailable_reason: "Provider is not configured." },
        { id: "unmount", available: true },
      ],
    };

    const html = renderToStaticMarkup(
      React.createElement(GenericCapabilityRenderer, {
        status,
        setup,
        actions,
        onSave: async () => undefined,
        onAction: async () => undefined,
      }),
    );

    assert.match(html, /data-capability-renderer="generic"/);
    assert.match(html, /Provider status/);
    assert.match(html, /Archive pool is unavailable/);
    assert.match(html, /Configure pool provider/);
    assert.match(html, /autoComplete="off"/);
    assert.match(html, /Mount pool/);
    assert.match(html, /Provider is not configured/);
    assert.match(html, /Availability was not reported/);
    assert.match(html, /Confirmation is unavailable/);
    assert.doesNotMatch(html, /must-not-render/);
  } finally {
    await vite.close();
  }
});
