# Mattermost Integration and Alert Management

## Goal

Make Mattermost and LimeOS alerts one guided installation. Put installation,
connection health, alert policy, and silences on a dedicated Integrations page.
Reserve the same integration for the planned Mattermost AI agent.

## Product Decisions

- Add an Integrations page under System.
- Install Postgres, Mattermost, and the alert daemon as one stack.
- Automatically create the first Mattermost admin, the `limeos` team, the
  `limeos-alerts` channel, and an incoming webhook.
- Manage alerts by category and individual resource.
- Support permanent and timed resource silences. Defer recurring maintenance
  schedules.
- Keep existing catalog definitions for compatibility, but direct new
  Mattermost installations to Integrations.

## Architecture

The Integrations page owns Mattermost installation, bootstrap, status, alert
policy, silences, and test delivery. Mattermost remains the user-facing chat
interface.

The setup form collects the Mattermost site URL, admin username, email,
password, stack name, and channel name. LimeOS generates the database password
and webhook secret. A Mattermost quickstart service performs these steps:

1. Create one Compose stack with Postgres, Mattermost, and `limeos-alertd`.
2. Start Postgres and Mattermost and wait for their health checks.
3. Run `mmctl --local` in the Mattermost container to create or find the admin,
   `limeos` team, and `limeos-alerts` channel.
4. Create or find the incoming webhook and write it to the alert daemon
   environment.
5. Start the alert daemon and send a test notification.
6. Stream progress through the existing operation registry.

The workflow is idempotent. A retry discovers completed resources and resumes
at the failed stage.

Store non-secret metadata and policy in
`/etc/limeos/integrations/mattermost.json`. Store the database password,
bootstrap password, and webhook URL in
`/etc/limeos/integrations/mattermost.env` with mode `0600`. API responses never
return stored secrets. Password inputs are write-only; the UI reports only
whether required credentials exist.

## Alert Policy

Expose these categories with an enable toggle and an availability state:

| Category | Conditions |
| --- | --- |
| Containers | A long-running container is down or unhealthy |
| SMART | A disk reports a failing health assessment |
| Mounts | A configured required mountpoint disappears |
| SnapRAID | Status reports an error, degradation, or required sync |

Discovered resources appear below each category. A user can silence one
resource permanently or until an ISO-8601 expiry time. A silence records its
category, stable resource key, creation time, optional expiry, and optional
reason. The daemon removes expired silences.

The daemon evaluates every available signal before it applies notification
policy. This preserves active incident state while a category or resource is
silent. An incident that opens during a silence remains pending. If the fault
still exists when the silence expires, the daemon sends one incident. A
disabled category sends neither incidents nor recoveries. Re-enabling it sends
one notification for each active, undelivered incident.

The alert daemon reloads policy after the JSON file changes. It persists latest
resource observations, incidents, delivery state, the last successful
Mattermost delivery, and provider errors. The Integrations API reads these
status files and writes policy atomically.

Add a read-only helper command that returns host SMART, mount, and SnapRAID
snapshots. The alert daemon reads this command through the mounted helper
socket. It continues to read containers through the read-only Docker socket.
Provider errors produce an unavailable state, not an infrastructure incident.

## Interface

Mattermost has one status header: Not installed, Installing, Connected,
Degraded, or Disconnected. It shows the site URL, channel, last successful
delivery, and the relevant recovery action.

Before installation, the primary action opens a setup dialog. Common fields
appear first. Port, timezone, polling interval, and failure threshold remain
under advanced settings. The dialog streams the concrete install and bootstrap
stages and retains an actionable error for retry.

After installation, the page uses three tabs:

- **Overview:** service health, Mattermost link, channel and webhook state,
  test delivery, and repair controls.
- **Alert policy:** category toggles, discovered resources, required mounts,
  active incidents, and silence controls.
- **AI agent:** a reserved unavailable state until the agent listener ships.

Removal requires confirmation. Users can remove services while retaining data
or remove LimeOS integration configuration. Persistent Mattermost data is
retained by default.

## Error Handling

Report separate failures for database readiness, Mattermost readiness,
bootstrap account creation, team creation, channel creation, webhook creation,
alert daemon startup, and test delivery. Retrying resumes from the failed
stage. Never include a password, token, webhook URL, or database connection
string in progress events or errors.

If LimeOS detects compatible Mattermost services in one existing stack, offer
to adopt them. If services span multiple stacks or the credentials cannot be
verified, report the conflict and leave them unchanged.

## Verification

Service tests cover idempotent install and bootstrap, partial-failure recovery,
secret redaction, policy validation, permanent and timed silences, pending
delivery, category re-enable behavior, and unavailable providers.

API tests cover authentication, CSRF, status, policy updates, test delivery,
and streamed progress. Frontend tests cover initial setup, install progress,
connected and degraded states, category and resource controls, silence dialogs,
responsive layout, and keyboard access. Existing catalog and evaluator tests
remain compatibility coverage.

