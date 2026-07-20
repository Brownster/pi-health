# Integration Lifecycle Management

Date: 2026-07-20
Status: Approved design

## Purpose

LimeOS can install Mattermost and AI Agents, but it cannot fully remove either
integration from the UI. AI Agents can be disabled. Mattermost can be configured, but
cannot be disabled, uninstalled, or purged.

This design adds explicit lifecycle controls without hiding built-in integrations or
silently deleting data. It separates reversible service control, local integration
removal, and permanent data deletion.

## Decisions

1. Built-in integration cards remain visible after uninstall so users can reinstall
   them.
2. Mattermost removal is blocked while AI Agents is installed.
3. Mattermost disable requires AI Agents to be disabled first.
4. Disabling Mattermost stops the entire Compose stack, including Postgres and alert
   delivery.
5. Mattermost uninstall preserves Docker volumes, the database recovery credential,
   and chat history.
6. Mattermost data purge is a separate irreversible action after uninstall.
7. AI Agents uninstall removes local credentials and runtime data but preserves the
   security audit log.
8. AI Agents uninstall offers `Remove Claude Code from this device`, enabled by default.
9. Destructive integration lifecycle actions require the existing `extensions.admin`
   permission.
10. Partial cleanup never reports success. It produces `cleanup_required` with a retry
   path.

## Product Model

Integration lifecycle belongs to the Integrations page. Settings / Advanced /
Extensions continues to manage installable provider packages. Integration adapters
remain visible under Extensions, but direct users to the owning integration card.

The UI uses three terms consistently:

| Action | Effect | Data |
| --- | --- | --- |
| Disable | Stop the integration's services | Preserve all configuration and data |
| Uninstall | Remove managed runtime resources | Preserve only data named in the confirmation |
| Delete data | Permanently remove retained application data | Irreversible |

## State Model

### AI Agents

```text
not_installed
    | install
    v
setup_required -> connected <-> disabled
                      |
                      | uninstall
                      v
               not_installed

Any interrupted uninstall -> cleanup_required -> retry -> not_installed
```

AI Agents keeps its current connected, degraded, disconnected, authenticating, and
setup-required states. `cleanup_required` takes precedence when the uninstall tombstone
records unfinished work.

### Mattermost

```text
not_installed -> connected/degraded <-> disabled
      ^                 |
      |                 | uninstall, only when AI Agents is not installed
      +-----------------+
        retained data

not_installed + retained data -> purge -> not_installed without retained data
Any interrupted operation -> cleanup_required -> retry
```

`installed` means LimeOS owns a runnable generated stack. `retained_data` means known
Mattermost Docker volumes remain after uninstall. These facts are independent.

## Dependency Rule

The assistant requires Mattermost for transport and identity. LimeOS therefore applies
different dependency gates to reversible and permanent Mattermost actions:

- Mattermost disable requires AI Agents to be disabled first. The assistant remains
  installed and can be re-enabled after Mattermost starts again.
- Mattermost uninstall requires AI Agents to be uninstalled first. Disabling the
  assistant is insufficient because its configuration, bot credentials, and remote
  identity still depend on Mattermost.

Blocked responses name AI Agents, state the required lifecycle action, and supply its
integration route. LimeOS never cascades into agent disable or removal.

## Data Ownership

### AI Agents

Uninstall removes these fixed integration-owned resources:

- `limeos-agent.service` and `limeopsd.service`
- `/etc/limeos/integrations/agents.json`
- `/etc/limeos/integrations/agents.env`
- `/etc/limeos/agent-policy.json`
- `/usr/lib/limeos-agent`
- `/var/lib/lime-agent/venv`
- `/var/lib/lime-agent/.claude`
- `/var/lib/lime-agent/state`
- transient LimeOps socket and release marker state

Uninstall preserves:

- `/var/log/limeos/agent-audit.jsonl`
- the `lime-agent`, `limeops`, and related system groups
- Mattermost, alerts, channels, messages, and other integrations

When selected, Claude cleanup removes the LimeOS-managed Claude Code apt hold, package,
source, and signing key. The helper reports each item separately so a package-manager
failure can be retried.

LimeOS attempts to revoke or deactivate the remote `@limeos` bot with the supplied
Mattermost administrator credentials. Remote cleanup failure does not block local
uninstall. The final result records a warning and identifies the bot that may remain.

### Mattermost

Disable runs Compose down without volume deletion. It preserves the generated stack,
integration configuration, secrets, policy, database, uploaded content, plugins, and
logs.

Uninstall removes:

- Mattermost, Postgres, and alert daemon containers
- LimeOS-generated stack files and local images owned by that stack
- active Mattermost integration configuration and webhook credentials
- stack-notification and package-update webhook configuration
- runtime status for this integration

Uninstall retains the declared Mattermost Docker volumes:

- Postgres database
- Mattermost configuration
- uploaded data
- logs
- plugins
- one protected database recovery credential needed to reattach Postgres

A server-owned tombstone stores only the Compose project identity, retained-volume
fact, lifecycle operation, warnings, and timestamps. It stores no credential or webhook.
The database credential remains in a separate root-owned mode-`0600` recovery secret and
is never returned by an API. Reinstall consumes that secret instead of generating a new
database password. A successful reinstall returns it to the active Mattermost secret;
purge deletes it.

Purge removes only the allowlisted volumes declared by the Mattermost stack. It cannot
accept volume names or filesystem paths from the request.

## API Contract

All mutations require authentication, global CSRF validation, `extensions.admin`, and
an available operation slot. They return `202` with the existing operation ID and SSE
stream URL pattern.

```text
POST /api/integrations/agents/uninstall
POST /api/integrations/mattermost/disable
POST /api/integrations/mattermost/enable
POST /api/integrations/mattermost/uninstall
POST /api/integrations/mattermost/purge
```

Agent uninstall accepts only:

```json
{
  "confirmation": "AI Agents",
  "admin_username": "limeadmin",
  "admin_password": "write-only",
  "remove_claude_code": true
}
```

Mattermost uninstall accepts only:

```json
{"confirmation": "Mattermost"}
```

Mattermost purge accepts only:

```json
{
  "confirmation": "Mattermost",
  "acknowledge_data_loss": true
}
```

Disable and enable accept an empty JSON object. Unknown fields fail validation. Public
errors are bounded and never include credentials, command output, filesystem paths, or
Compose environment values.

Read responses add these bounded fields where relevant:

```json
{
  "state": "disabled",
  "installed": true,
  "retained_data": false,
  "cleanup_required": false,
  "allowed_actions": ["enable", "uninstall"]
}
```

The server calculates `allowed_actions`. The client does not infer dependency or safety
rules from display state.

## Service And Helper Boundaries

The Mattermost integration service owns Compose operations and lifecycle tombstones. It
uses the stored validated stack name and the server-owned stack-path resolver. Requests
cannot provide a project, file, image, container, or volume name.

The agent integration service orchestrates remote bot cleanup and calls one new fixed
helper command for local uninstall. The helper accepts only the Boolean
`remove_claude_code` option. Its implementation uses fixed allowlists for units, files,
directories, packages, apt sources, and keys. It does not run a caller-provided command
or path.

Both services follow this order:

1. Authorize and validate the full request.
2. Check current state and dependencies.
3. Write an operation tombstone.
4. Stop services before removing runtime resources.
5. Remove resources in idempotent steps.
6. Commit the final lifecycle state after required steps succeed.
7. Retain the tombstone with `cleanup_required` after partial failure.

Retries skip resources that are already absent. A failed remote bot cleanup is a warning;
a failed local service or data operation is an error.

## User Interface

Each installed integration card gains a compact **Manage integration** menu. Primary
setup, repair, test, and policy controls remain unchanged.

### AI Agents

The menu provides Disable, Enable and repair, and Uninstall. The uninstall dialog:

- lists the services, credentials, runtime, and usage data that will be removed;
- states that Mattermost and the security audit log remain;
- requests Mattermost administrator credentials for remote bot cleanup;
- includes `Remove Claude Code from this device`, enabled by default;
- requires typing `AI Agents` before confirmation.

Completion distinguishes full success from success with a remote-bot warning.

### Mattermost

The menu provides Disable, Enable, and Uninstall according to server-provided actions.
If AI Agents is active, Mattermost disable explains that the assistant must be disabled
first and links to its card. If AI Agents is installed, Mattermost uninstall explains
that the assistant must be uninstalled first and supplies the same direct link.

Mattermost uninstall states that containers, alert delivery, and LimeOS configuration
will be removed while chat history remains. It requires typing `Mattermost`.

After uninstall, the persistent card shows `Data retained` with Set up and Delete data
actions. Delete data requires typing `Mattermost` and selecting an explicit irreversible
loss acknowledgement. The confirmation names database records, messages, uploads,
plugins, and retained logs.

### Operation Recovery

Operation dialogs stream named steps and cannot close while a required cleanup step is
running. Errors retain the completed steps and output. A page refresh reconstructs the
state from server-owned config, service facts, and tombstones.

`cleanup_required` replaces normal actions with Retry cleanup and bounded manual
guidance. The UI does not report an integration as removed until required local cleanup
finishes.

## Accessibility And Responsive Behavior

- Menus and dialogs use semantic buttons, labels, descriptions, and visible focus.
- Focus enters each dialog, remains trapped, and returns to its trigger.
- Typed confirmation fields identify the required value in visible text.
- Destructive actions use text and icons, not color alone.
- Progress and completion changes use live regions.
- Long service errors wrap within the dialog and never cause horizontal overflow.
- Dialog actions remain reachable at phone, tablet, and desktop widths.

## Test Strategy

Backend tests cover:

- authentication, CSRF, `extensions.admin`, request allowlists, and redaction;
- state transitions and server-owned allowed actions;
- Mattermost disable blocking while AI Agents is active and uninstall blocking while it
  is installed;
- fixed helper parameters and path, unit, package, and volume allowlists;
- disable, enable, retained-volume uninstall, purge, and reinstall;
- agent local cleanup, optional Claude removal, and audit retention;
- remote bot success, failure warning, and unavailable Mattermost;
- idempotent retries and failure at each cleanup step;
- tombstone recovery after process restart.

Playwright tests cover:

- administrator and non-admin controls;
- blocked Mattermost uninstall with a direct AI Agents link;
- typed confirmations and irreversible acknowledgement;
- streamed success, warning, failure, refresh, and retry states;
- persistent uninstalled cards and retained-data status;
- keyboard operation, focus restoration, and responsive overflow;
- reinstall after retained-data uninstall.

The full suite, committed bundle digest, and target-Pi canary remain release gates. The
target Pi does not need npm.

## Rollout And Rollback

Implementation ships additively. Existing integrations default to their current state;
no database or configuration migration is required. New tombstones are created only
when a lifecycle operation starts.

Rollout first verifies disable and enable on a disposable or backed-up Mattermost stack,
then agent uninstall, retained-data Mattermost uninstall, reinstall, and purge. Holly's
canary records the starting revision, container and volume inventory, configuration,
operation logs, and final state.

Code rollback restores the previous committed bundle and services. It cannot restore
purged Mattermost data. The purge dialog must state that boundary before confirmation.

## Non-Goals

- Removing built-in integration cards from discovery
- Cascading Mattermost removal into AI Agents removal
- Deleting the agent security audit log
- Deleting agent system users or groups
- Accepting caller-provided paths, unit names, package names, or volume names
- Removing third-party extension packages from the Integrations page
- Adding general backup or export workflows as part of lifecycle removal
