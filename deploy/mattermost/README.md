# Mattermost (LAN) — deploy for the agent-investigate MVP (brick B1)

Temporary home: Holly's Pi (`192.168.0.45`) via Dockge, until the DAS Pi is up. ARM64 images are
used, so it runs on a Pi 4/5.

## 1. Stand it up
```bash
# on the Pi
mkdir -p /opt/stacks/mattermost && cd /opt/stacks/mattermost
# copy compose.yaml and .env.example from this repo's deploy/mattermost/
cp .env.example .env
# edit .env: set POSTGRES_PASSWORD (long random) and MM_SITE_URL=http://192.168.0.45:8065
docker compose up -d          # or add the stack in Dockge and start it
```
First boot takes a minute (Mattermost migrates the DB). Watch `docker compose logs -f mattermost`
until it's ready, then open `http://192.168.0.45:8065`.

## 2. First-run
1. Create the admin account and a team (e.g. `home`).
2. Create a channel for alerts, e.g. `~limeos-alerts`.

## 3. Incoming webhook (this is what the alert daemon posts to)
1. **Main menu → Integrations → Incoming Webhooks → Add Incoming Webhook.**
   - If Integrations is hidden: **System Console → Integrations → Integration Management →
     Enable Incoming Webhooks = true** (the compose already sets `ENABLEINCOMINGWEBHOOKS=true`).
2. Bind it to the `limeos-alerts` channel; save.
3. Copy the URL — it looks like `http://192.168.0.45:8065/hooks/xxxxxxxxxxxx`.

Give that URL to the alert daemon as `LIMEOS_ALERT_MATTERMOST_WEBHOOK` (see `deploy/alertd/`).

## Notes
- **LAN-only.** Don't expose 8065 to the Internet without a TLS reverse proxy.
- **Resources.** Mattermost + Postgres is the heaviest always-on piece (~0.5–1.5 GB). On a busy
  media Pi, watch memory; the compose sets conservative `mem_limit`s you can tune.
- **Storage.** On a small USB disk, keep an eye on `./volumes/postgres` and `./volumes/mattermost/data`.
- The threaded **bot** account + reaction approvals are only needed for the `@agent` step (brick B4);
  incoming webhooks alone are enough for the model-free alert notifications (brick B2).
