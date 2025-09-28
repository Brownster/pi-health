# Sonarr MCP Server

FastAPI service exposing Sonarr telemetry via the Model Context Protocol (MCP).

## Endpoints
- `POST /tools/get_system_status`
- `POST /tools/get_queue`
- `POST /tools/get_health`
- `POST /tools/get_wanted_missing`
- `GET /health`

## Configuration
- `SONARR_BASE_URL` (defaults to `http://sonarr:8989/api/v3`)
- `SONARR_API_KEY` or `SONARR_API_KEY_FILE`
- `SONARR_HTTP_TIMEOUT` (optional, seconds)

See `docs/add_sonarr_and_radarr.md` for integration guidance.
