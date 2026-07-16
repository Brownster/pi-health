# LimeOS Stack Notifications

Consume Radarr/Sonarr/Lidarr/Readarr/Prowlarr (`*arr`) webhooks and present them in a
dedicated Mattermost channel, brokered through the LimeOS app rather than pointing each app
at a raw incoming webhook.

## Why brokered, not direct

`*arr` apps can post directly to a Slack/Mattermost webhook, but going through LimeOS lets us:

- **Normalize** the differing payloads into one consistent, colour-coded card.
- **Apply a policy** (quiet by default) so the channel carries signal, not per-release spam.
- **Own one secret** — the Mattermost incoming webhook URL never leaves the host; the apps
  only hold a per-install capability token.

Decisions (fixed): brokered LimeOS endpoint · one dedicated `#stack-notifications` channel ·
quiet default event set.

## Event policy

`normalize()` maps each app's `eventType` to a normalized event and forwards per policy:

- **Quiet (default):** imports, upgrades, health issues, health restored, failures, manual
  interaction required.
- **Verbose:** the above plus grabs, renames, library adds, application updates.
- **Never forwarded:** the connection `Test` (still answered `200` so the app's test passes)
  and unknown events.

Import events flagged `isUpgrade` are reclassified as upgrades. Health issues at `level=error`
render critical; failures / manual are warnings; everything else is info. Details are bounded
to 500 chars and only ever become attachment *data*, never markup.

## Components

| Layer | File | Responsibility |
| --- | --- | --- |
| Core (framework-neutral) | `stack_notifications_service.py` | `normalize`, `render_mattermost`, `StackNotificationsService` (`ingest`, `status`, `set_mode`) |
| Routes | `integrations_manager.py` | token-gated ingest + authenticated status/mode/enable |
| Provisioning | `mattermost_integration_service.py` | create the channel + webhook, persist config |
| Wiring | `app.py` | config read/write + webhook poster |
| UI | `frontend/src/components/integrations/stack-notifications-card.tsx` | status, copy-paste URL, quiet/verbose toggle, existing-user setup |

Config lives at `<integrations>/stack-notifications.json` (mode `0o600`):
`{ enabled, token, webhook_url, mode, source_default, channel_name }`.

## Endpoints

- `POST /api/integrations/stack-notifications/hook/<token>` — the `*arr` webhook sink. **No**
  login/CSRF (apps post directly); the per-install token is constant-time compared, the body
  is size-capped (256 KiB) before parsing, and a valid token always returns `200` so a
  connection Test succeeds even when the event is suppressed.
- `GET  /api/integrations/stack-notifications` — status for the integrations card (auth). The
  token is returned here so the admin can build the ingest URL; the route is authenticated.
- `PUT  /api/integrations/stack-notifications/mode` — switch quiet/verbose (auth + CSRF).
- `POST /api/integrations/stack-notifications/enable` — provision the channel/webhook on an
  already-installed Mattermost (auth + CSRF); streams via the operation registry.

## Channel provisioning

Creating a channel + incoming webhook needs an authenticated Mattermost session. The admin
password is **not stored**, which shapes two paths:

- **New users (automatic):** `stream_install` creates `#stack-notifications` + its webhook and
  writes the config right after the alerts channel, reusing the install-time admin session.
- **Existing users (guided):** the integrations card's **Set up** action re-collects the admin
  password (write-only, used only to log in) and runs `stream_enable_stack_notifications`,
  which idempotently ensures the channel + webhook + config.

Provisioning is idempotent: `ensure_channel`/`ensure_incoming_webhook` no-op when the objects
exist, and an existing token/mode is preserved so re-running never rotates a token the `*arr`
apps already use. The webhook lookup matches on our display name (`LimeOS Stack Notifications`)
so it never collides with the alerts webhook (`LimeOS Alerts`) on the same team.

## Configure an *arr app

Settings → Connect → add a **Webhook**: method `POST`, URL =
`http://<limeos-host>:<port>/api/integrations/stack-notifications/hook/<token>` (copy it from
the integrations card). Deliveries land in `~stack-notifications`.
