# Lidarr MCP Integration Guide

This guide follows the same pattern as the Sonarr/Radarr integrations so Lidarr telemetry (queue, health, missing albums) can appear inside Ops-Copilot.

## 1) MCP Server & Gateway
- Deploy the Lidarr MCP server alongside your stack (see Lidarr MCP repo for container image). Expose it on an internal URL such as `http://lidarr-mcp:8080`.
- Register the server and tools in your gateway (`tool_registry.yaml` / `policy.yaml`) so it exposes `get_system_status`, `get_queue`, `get_health`, and `get_wanted_missing`.

## 2) Pi-Health Environment Variables
Set the base URL (and optional timeouts) for the Flask app, then restart:

```bash
LIDARR_MCP_BASE_URL=http://lidarr-mcp:8080
MCP_READ_TIMEOUT=5.0   # optional override
MCP_WRITE_TIMEOUT=30.0 # optional override
```

## 3) Verification Checklist
1. Hit the MCP health endpoint directly: `curl http://lidarr-mcp:8080/health` → `healthy`.
2. Restart Pi-Health (`docker compose restart pi-health-dashboard`, `systemctl restart`, etc.).
3. On the Ops-Copilot page ask “What’s Lidarr up to?” — the assistant should summarise download queue length, health warnings, and missing releases coming from the MCP server.
4. Remove the env var to disable the tool; the assistant goes back to the default response without redeploying code.

With the environment variable configured, any music-related chat prompts automatically leverage the `lidarr_status` tool, giving your family context about stalled downloads or health alerts in real time.
