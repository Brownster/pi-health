# Lidarr MCP Server

FastAPI service exposing Lidarr queue, health, and missing releases for MCP.

Env vars: `LIDARR_BASE_URL` (default `http://lidarr:8686/api/v1`), `LIDARR_API_KEY`/`_FILE`, optional `LIDARR_HTTP_TIMEOUT`.
