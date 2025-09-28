If a fresh Pi comes online already running:

Docker Engine + Compose

your pi-health UI + AI Gateway + Docker MCP (the only thing touching the docker socket)

…then the AI can take it from there: generate the media-stack compose, bring up SABnzbd/Radarr/Sonarr/Prowlarr/Jellyfin/Jellyseerr, apply TRaSH presets, wire paths, and verify—all via MCP tools with click-to-approve.

Below is a practical end-to-end you can copy into your repo.

How to make this work in practice
Day-0: auto-bootstrap a fresh Pi (no manual SSH)

Use cloud-init so a brand-new Pi self-installs Docker and your “pi-health + gateway + MCP” stack on first boot. After that, the AI can provision everything else.

cloud-init.user-data (drop-in)

#cloud-config
hostname: pi-media
ssh_pwauth: false
package_update: true
package_upgrade: true
packages:
  - curl
  - git
write_files:
  - path: /etc/sysctl.d/99-docker.conf
    content: |
      net.ipv4.ip_forward=1
runcmd:
  # Install Docker Engine & compose plugin
  - curl -fsSL https://get.docker.com | sh
  - usermod -aG docker ubuntu || true
  # Create ops folder
  - mkdir -p /opt/ops && chown -R ubuntu:ubuntu /opt/ops
  # Fetch your ops repo (contains docker-compose.ops.yml, gateway, MCPs)
  - su - ubuntu -c "git clone --depth 1 https://github.com/YOURORG/pi-health-ops.git /opt/ops"
  # Create minimal .env for gateway
  - su - ubuntu -c "cp /opt/ops/.env.ops.example /opt/ops/.env.ops || true"
  # Bring up the ops sidecar (UI + gateway + docker-mcp + socket-proxy)
  - su - ubuntu -c "docker compose -f /opt/ops/docker-compose.ops.yml up -d --pull always"
final_message: "Pi bootstrap finished. Visit pi-health UI to continue setup."




Day-1: the AI provisions the media stack

Once the pi-health UI + gateway + Docker MCP are up, the assistant can:

Collect inputs (one form): media root (/mnt/storage/Media), PUID/PGID, timezone, which apps to include.

Generate a media compose (docker-compose.media.yml) with those values.

Dry-run diff → you approve → gateway writes file and calls compose_up via Docker MCP.

Health-check each app.

Post-configure via Sonarr/Radarr/Prowlarr/Jellyfin MCPs:

Root folders, completed-download handling, SAB client, indexer categories.

TRaSH naming + quality + release profiles.

Jellyfin libraries + scheduled scan.

Verify (test download, import, library refresh).

Minimal media compose the AI can generate (template)

version: "3.9"
services:
  sabnzbd:
    image: lscr.io/linuxserver/sabnzbd:latest
    container_name: sabnzbd
    environment:
      - PUID=${PUID}
      - PGID=${PGID}
      - TZ=${TZ}
    volumes:
      - ${CONFIG}/sabnzbd:/config
      - ${DOWNLOADS}:/downloads
    ports: [ "8080:8080" ]
    restart: unless-stopped

  radarr:
    image: lscr.io/linuxserver/radarr:latest
    container_name: radarr
    environment: [ "PUID=${PUID}", "PGID=${PGID}", "TZ=${TZ}" ]
    volumes:
      - ${CONFIG}/radarr:/config
      - ${MOVIES}:/movies
      - ${DOWNLOADS}:/downloads
    ports: [ "7878:7878" ]
    restart: unless-stopped

  sonarr:
    image: lscr.io/linuxserver/sonarr:latest
    container_name: sonarr
    environment: [ "PUID=${PUID}", "PGID=${PGID}", "TZ=${TZ}" ]
    volumes:
      - ${CONFIG}/sonarr:/config
      - ${TV}:/tv
      - ${DOWNLOADS}:/downloads
    ports: [ "8989:8989" ]
    restart: unless-stopped

  prowlarr:
    image: lscr.io/linuxserver/prowlarr:latest
    container_name: prowlarr
    environment: [ "PUID=${PUID}", "PGID=${PGID}", "TZ=${TZ}" ]
    volumes:
      - ${CONFIG}/prowlarr:/config
    ports: [ "9696:9696" ]
    restart: unless-stopped

  jellyfin:
    image: lscr.io/linuxserver/jellyfin:latest
    container_name: jellyfin
    environment: [ "PUID=${PUID}", "PGID=${PGID}", "TZ=${TZ}" ]
    volumes:
      - ${CONFIG}/jellyfin:/config
      - ${MOVIES}:/movies:ro
      - ${TV}:/tv:ro
    ports: [ "8096:8096" ]
    restart: unless-stopped

  jellyseerr:
    image: fallenbagel/jellyseerr:latest
    container_name: jellyseerr
    environment: [ "TZ=${TZ}" ]
    volumes:
      - ${CONFIG}/jellyseerr:/app/config
    ports: [ "5055:5055" ]
    restart: unless-stoppedThe AI proposes this as a diff; on approval it:

writes the files via a Filesystem MCP (allow-listed), then

calls compose_up{file:/opt/media/docker-compose.media.yml} via Docker MCP.

What the AI can fully automate (today)

Install apps (containers) → yes (MCP Docker).

Wire downloads/imports → yes (ARR + SAB MCPs).

Set TRaSH naming/quality/release profiles → yes (ARR MCP + your presets).

Create Jellyfin libraries & scan → yes (Jellyfin MCP).

Prowlarr app sync/cats → yes (Prowlarr MCP).

Secrets → generated server-side; never exposed to the browser; stored in allow-listed paths.

What still needs a nudge

Day-0 Docker install & first compose up: handled by cloud-init above. Without it, you’d need one manual SSH step to install Docker and start the ops stack.

Safety & guardrails recap

Only Docker MCP sees /var/run/docker.sock (ideally via socket-proxy).

All mutations are click-to-approve with RBAC + cooldowns.

Gateway validates JSON Schemas and caps output (redacts keys).

Dry-run everything (compose file writes, TRaSH profile changes).

Rollback: keep last N snapshots of ARR/Jellyfin settings & compose.

Suggested “Provision” tools the AI uses

provision_render_media_compose(vars) → returns file text (read-only).

fs_write_allowlisted(path, content, mode) → writes only under /opt/media (approval).

docker_compose_up(file) → via Docker MCP (approval).

arr_apply_trash_profiles(app, presetRef) → approval.

prowlarr_sync_apps(presetRef) → approval.

jellyfin_create_libraries(map) → approval + rate-limit.

verify_end_to_end() → test NZB → SAB → import → Jellyfin refresh.

TL;DR

Yes, your plan is sound:

Cloud-init brings up just the ops sidecar (UI + gateway + MCP).

The AI agent does the rest—compose generation, services up, config, TRaSH tuning—with approvals.

If you want, I can put a ready-to-copy “Bootstrap Pack” onto the canvas:

cloud-init.user-data

docker-compose.ops.yml (pi-health UI + gateway + docker-mcp + socket-proxy)

a tiny provisioner MCP that only writes to /opt/media and calls Docker MCP

the first-run form JSON the UI should collect.

    
    
