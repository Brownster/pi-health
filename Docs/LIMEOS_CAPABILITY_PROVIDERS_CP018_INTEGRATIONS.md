# LimeOS Capability Providers CP-018 Integration Adapters

Date: 2026-07-18

Status: Implemented

Runtime commit: `d4e9934`

Scope: CP-018 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Registry Alignment

The backend capability registry now discovers the two LimeOS-managed integration
providers during normal production startup:

- Mattermost provides the tailored `integration.chat` capability.
- AI Agents provides the tailored, provider-neutral `agent.provider` capability.
- Both capabilities link to the existing Integrations page.
- Both runtimes use `integration-adapter`, so Extensions does not offer package enable,
  disable, update, repair, or removal actions.

The production manifests describe the existing delivery diagnostics. They do not add a
generic action transport or move any operation into the extension lifecycle API.

## Read-Only Status Mapping

`IntegrationCapabilityAdapter` reads the existing public service status methods and maps
them into the versioned capability status contract:

- Mattermost reports stack connectivity, alert-delivery configuration, bounded service
  counts, channel identity, monitored-resource count, active-incident count, and latest
  delivery outcome.
- AI Agents reports the provider identity and version, authentication and compatibility,
  gateway and broker state, runtime configuration, and Mattermost channel identity.
- Missing setup remains discoverable as `unconfigured` rather than making the adapter
  appear absent.
- Disabled, degraded, disconnected, and unavailable runtime states remain distinct.
- A failing agent helper status is isolated and cannot hide Mattermost or storage
  providers from the registry.

The adapter intentionally excludes alert-delivery error text, webhook values, credentials,
agent prompts, usage records, and audit records. The registry's server-owned redaction is
still applied to the bounded result.

## Ownership Boundary

The existing `/api/integrations/*` services and Integrations UI retain ownership of:

- Mattermost installation, repair, stack configuration, alert policy, silences, channel
  provisioning, and delivery tests
- AI Agents installation, Claude authentication, permission display, usage, audit,
  repair, disable, and assistant tests
- Authentication, operation streaming, confirmation, and error recovery

The shared registry supplies discovery and glanceable health only. CP-018 adds no
scheduler, polling loop, database, privileged helper command, or provider-supplied UI.
Status is read on demand when a capability or extension endpoint is requested.

## Existing-Instance Deployment

No manual migration is required:

- Existing Mattermost stack, webhook, alert policy, silence, agent runtime, Claude
  authentication, bot, usage, and audit files remain unchanged.
- Existing integration API routes and setup payloads remain unchanged.
- Updating does not install, repair, authenticate, enable, disable, or test either
  integration.
- No frontend source changed; the committed `static/v2` bundle remains fresh, so a target
  Pi does not need npm.

Use the normal LimeOS updater and restart. On Holly, confirm Integrations still reports
Mattermost and AI Agents correctly, then open Settings / Advanced / Extensions and verify
that both providers link back to Integrations with matching health.

## Verification

- Full non-E2E suite: 1,689 passed, 1 skipped
- Adapter, registry, manifest contract, and capability API suite: 106 passed
- Existing Mattermost, AI Agents, application, and integration API suite: 138 passed,
  1 skipped
- Integrations and Extensions Playwright regression: 23 passed
- Ruff lint, Python compilation, bundle freshness, and `git diff --check`: passed

CP-019 owns the final primary-navigation migration. CP-020 retains the complete
cross-domain hardening gate before the Holly release signoff.
