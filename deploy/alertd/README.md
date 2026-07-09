# Alert daemon deploy (brick B2)

The daemon polls native health signals, folds them into deduplicated incidents, and posts to a
Mattermost incoming webhook. **No model.** Set the webhook from `deploy/mattermost/` first.

## Run it
Pick the option that matches how pi-health runs on the host:

- **Containerized pi-health (likely on Holly's Pi):** add `compose.sidecar.yaml`'s `limeos-alertd`
  service to your pi-health stack, set `LIMEOS_ALERT_MATTERMOST_WEBHOOK`, and start it. It reuses
  the pi-health image with `command: python alert_daemon.py`.
- **Host install:** use `limeos-alertd.service` (systemd), with an `EnvironmentFile` holding the
  webhook + tuning.

## Config
| Env | Default | Meaning |
|---|---|---|
| `LIMEOS_ALERT_MATTERMOST_WEBHOOK` | (unset) | Incoming-webhook URL. Unset = dry run (logs only). |
| `LIMEOS_ALERT_POLL_SECONDS` | 60 | Evaluation interval. |
| `LIMEOS_ALERT_FAIL_THRESHOLD` | 2 | Consecutive failures before an incident opens. |
| `LIMEOS_ALERT_REQUIRED_MOUNTS` | (empty) | Comma-separated mountpoints that must be present. |
| `LIMEOS_STATE_DIR` | /var/lib/limeos | Where `alerts.json` persists (survives restarts). |

## What works where, right now
- **Container down / unhealthy — works today** via the mounted docker socket. This is enough for a
  full end-to-end smoke on Holly's Pi: stop a `restart: unless-stopped` container and you should get
  one Mattermost incident; start it and get one recovery. (One-shot / cron-style containers with
  `restart: no`/`on-failure` are intentionally ignored.)
- **Mounts** — needs the daemon to see the *host* mount table. A container sees its own
  `/proc/self/mounts`, so leave `LIMEOS_ALERT_REQUIRED_MOUNTS` empty in the sidecar until it runs
  with host mount visibility (`pid: host` or a bind of the host mount table). On a host/systemd
  install it works directly.
- **SMART / SnapRAID** — the live readers are stubbed pending Pi deployment (they need the
  privileged helper / plugin config). They'll be wired on the DAS Pi. Until then these simply emit
  no signals (the evaluator treats "no signal" as fine).

## Smoke test (do this once Mattermost is up)
1. Set the webhook, start the daemon (sidecar or systemd).
2. `docker stop <an unless-stopped container>` — within ~2 polls you get a 🟠 incident in the alerts
   channel.
3. `docker start <it>` — you get one ✅ recovery.
4. Restart the daemon mid-incident — it must not re-page the still-open incident (state persisted).
