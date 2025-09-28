# Pi-Health MCP Monorepo (wip)

This directory will host the FastAPI-based Model Context Protocol (MCP) servers that Pi-Health relies on for live telemetry and mutating actions (Docker, Sonarr/Radarr/Lidarr, SABnzbd, Jellyfin, Jellyseerr, etc.).

Each service will graduate into its own subfolder containing:

- `main.py` – FastAPI application exposing the documented tools
- `client.py` – helper for talking to the upstream service (REST/CLI)
- `requirements.txt` and `Dockerfile`
- `README.md` summarising environment variables and local smoke tests

For now the `docs/add_*.md` guides capture the desired behaviour. As we port each service into `mcp/<service>/`, we will:

1. Lift the reference code from the doc into `main.py`
2. Reuse shared helpers from `mcp/common`
3. Add unit/integration tests
4. Publish a container image via CI

| Service   | Status    | Notes |
|-----------|-----------|-------|
| docker    | implemented (`main.py`) | Compose restart/start/stop via socket proxy |
| sonarr    | implemented | Queue, health, missing episodes |
| radarr    | implemented | Queue, health, missing movies |
| lidarr    | implemented | Queue, health, missing albums |
| sabnzbd   | implemented | Queue, speed, warnings |
| jellyfin  | implemented | System info, sessions, tasks |
| jellyseerr| implemented | Status, request listing |

As we implement each server we'll update this table with links to the actual code.
