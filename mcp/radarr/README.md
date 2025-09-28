# Radarr MCP Server

FastAPI service exposing Radarr telemetry (queue, health, missing movies) for MCP clients.

## Env Vars
- `RADARR_BASE_URL` (default `http://radarr:7878/api/v3`)
- `RADARR_API_KEY` or `RADARR_API_KEY_FILE`
- `RADARR_HTTP_TIMEOUT` (optional)

Refer to `docs/add_sonarr_and_radarr.md` for usage.
