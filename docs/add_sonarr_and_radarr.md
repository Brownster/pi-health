# Sonarr & Radarr MCP Integration Guide

This guide extends your Docker MCP pattern to add dedicated MCP servers for Sonarr and Radarr APIs. Each *arr app gets its own MCP server for proper API management, rate limiting, and tool organization.

Once `SONARR_MCP_BASE_URL` is exported (and optionally `MCP_READ_TIMEOUT` / `MCP_WRITE_TIMEOUT`), Pi-Health automatically attaches a `sonarr_status` tool to Ops-Copilot, so chat prompts that mention Sonarr/TV will pull live queue and health telemetry via the MCP gateway. You should:

1. Ensure the Sonarr MCP server is reachable from the Flask container (e.g. `http://sonarr-mcp:8080`).
2. Add `SONARR_MCP_BASE_URL=http://sonarr-mcp:8080` to the Pi-Health environment and restart the app.
3. Ask the assistant “How is Sonarr doing?” – the reply now includes queue length, health warnings, and missing items sourced from the MCP server. If the variable isn’t set, the assistant falls back to the legacy static message.

Repeat the same steps for Radarr by setting `RADARR_MCP_BASE_URL=http://radarr-mcp:8080`. After restarting Pi-Health, prompt “Any issues with Radarr?” and confirm the assistant calls out queue depth, missing movies, and health warnings from the MCP feed. Unsetting the variable removes the tool again without code changes.

---

## 1) Extended Docker Compose

```yaml
version: "3.9"

services:
  # Existing Docker MCP Server (unchanged)
  docker-socket-proxy:
    image: tecnativa/docker-socket-proxy:edge
    container_name: docker-socket-proxy
    environment:
      - LOG_LEVEL=info
      - EVENTS=1
      - PING=1
      - VERSION=1
      - CONTAINERS=1
      - IMAGES=1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks: [ops_net]
    restart: unless-stopped
    read_only: true

  docker-mcp:
    image: mcp/docker-mcp-server:latest
    container_name: mcp-docker
    environment:
      DOCKER_HOST: tcp://docker-socket-proxy:2375
    networks: [ops_net]
    restart: unless-stopped

  # NEW: Sonarr MCP Server
  sonarr-mcp:
    image: yourorg/sonarr-mcp-server:latest  # Custom build needed
    container_name: mcp-sonarr
    user: "10002:10002"
    environment:
      LOG_LEVEL: INFO
      SONARR_BASE_URL: http://sonarr:8989
      SONARR_API_KEY_FILE: /run/secrets/sonarr_api_key
      RATE_LIMIT_RPM: 30
    secrets:
      - sonarr_api_key
    networks: [ops_net]
    restart: unless-stopped
    read_only: true
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s

  # NEW: Radarr MCP Server
  radarr-mcp:
    image: yourorg/radarr-mcp-server:latest  # Custom build needed
    container_name: mcp-radarr
    user: "10003:10003"
    environment:
      LOG_LEVEL: INFO
      RADARR_BASE_URL: http://radarr:7878
      RADARR_API_KEY_FILE: /run/secrets/radarr_api_key
      RATE_LIMIT_RPM: 30
    secrets:
      - radarr_api_key
    networks: [ops_net]
    restart: unless-stopped
    read_only: true
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s

  # Existing AI Gateway (unchanged)
  ai-gateway:
    image: yourorg/ai-gateway:dev
    container_name: ai-gateway
    networks: [ops_net]
    restart: unless-stopped

networks:
  ops_net:
    driver: bridge

secrets:
  sonarr_api_key:
    file: ./secrets/sonarr_api_key.txt
  radarr_api_key:
    file: ./secrets/radarr_api_key.txt
```

---

## 2) Extended Tool Registry

```yaml
services:
  docker-mcp:
    base_url: http://docker-mcp:8080
    transport: http
    auth: none

  sonarr-mcp:
    base_url: http://sonarr-mcp:8080
    transport: http
    auth: none

  radarr-mcp:
    base_url: http://radarr-mcp:8080
    transport: http
    auth: none

tools:
  # --- DOCKER TOOLS (existing) ---
  docker_ps:
    mcp: { service: docker-mcp, fn: docker_ps }
    mutating: false
    summary: "List running containers"

  # --- SONARR READ-ONLY TOOLS ---
  sonarr_system_status:
    mcp: { service: sonarr-mcp, fn: get_system_status }
    mutating: false
    summary: "Get Sonarr system health and version info"

  sonarr_queue_status:
    mcp: { service: sonarr-mcp, fn: get_queue }
    mutating: false
    summary: "Show download queue with progress and ETAs"

  sonarr_calendar:
    mcp: { service: sonarr-mcp, fn: get_calendar }
    mutating: false
    summary: "Show upcoming episodes (next 7 days)"

  sonarr_wanted_missing:
    mcp: { service: sonarr-mcp, fn: get_wanted_missing }
    mutating: false
    summary: "List missing episodes that should be downloaded"

  sonarr_disk_space:
    mcp: { service: sonarr-mcp, fn: get_disk_space }
    mutating: false
    summary: "Check available disk space on root folders"

  sonarr_health_check:
    mcp: { service: sonarr-mcp, fn: get_health }
    mutating: false
    summary: "Get current health warnings/errors"

  # --- SONARR MUTATING TOOLS ---
  sonarr_search_episode:
    mcp: { service: sonarr-mcp, fn: search_episode }
    mutating: true
    approval: required
    cooldown: { seconds: 300, key_by: series_id }
    summary: "Trigger manual search for specific episode"

  tip: After exporting SONARR_MCP_BASE_URL, you can trigger a search via:

  ```bash
  curl -sX POST http://sonarr-mcp:8080/tools/search_episode \
       -H 'content-type: application/json' \
       -d '{"episodeId":12345}'
  ```

  Ops-Copilot will surface this action automatically when an episode is missing.

  sonarr_refresh_series:
    mcp: { service: sonarr-mcp, fn: refresh_series }
    mutating: true
    approval: required
    cooldown: { seconds: 600, key_by: series_id }
    summary: "Refresh series metadata and scan for new episodes"

  sonarr_remove_queue_item:
    mcp: { service: sonarr-mcp, fn: remove_queue_item }
    mutating: true
    approval: required
    summary: "Remove stuck download from queue"

  # --- RADARR READ-ONLY TOOLS ---
  radarr_system_status:
    mcp: { service: radarr-mcp, fn: get_system_status }
    mutating: false
    summary: "Get Radarr system health and version info"

  radarr_queue_status:
    mcp: { service: radarr-mcp, fn: get_queue }
    mutating: false
    summary: "Show movie download queue"

  radarr_calendar:
    mcp: { service: radarr-mcp, fn: get_calendar }
    mutating: false
    summary: "Show recently released movies (last 30 days)"

  radarr_wanted_missing:
    mcp: { service: radarr-mcp, fn: get_wanted_missing }
    mutating: false
    summary: "List wanted movies not yet downloaded"

  radarr_disk_space:
    mcp: { service: radarr-mcp, fn: get_disk_space }
    mutating: false
    summary: "Check available disk space"

  radarr_health_check:
    mcp: { service: radarr-mcp, fn: get_health }
    mutating: false
    summary: "Get current health status"

  # --- RADARR MUTATING TOOLS ---
  radarr_search_movie:
    mcp: { service: radarr-mcp, fn: search_movie }
    mutating: true
    approval: required
    cooldown: { seconds: 300, key_by: movie_id }
    summary: "Trigger manual search for specific movie"

  radarr_refresh_movie:
    mcp: { service: radarr-mcp, fn: refresh_movie }
    mutating: true
    approval: required
    cooldown: { seconds: 600, key_by: movie_id }
    summary: "Refresh movie metadata"

  radarr_remove_queue_item:
    mcp: { service: radarr-mcp, fn: remove_queue_item }
    mutating: true
    approval: required
    summary: "Remove stuck download from queue"
```

---

## 3) Extended Gateway Adapter

```python
# gateway/adapters/arr_mcp.py
import os
from typing import Any, Dict, Optional
from .docker_mcp import ToolError, httpx

class ArrMCPClient:
    """Generic client for *arr MCP servers"""

    def __init__(self, service_name: str, base_url: Optional[str] = None):
        self.service = service_name
        self.base = base_url or f"http://{service_name}-mcp:8080"
        self.read_timeout = 10.0  # *arr APIs can be slower
        self.write_timeout = 45.0  # Searches can take time

    def call(self, fn: str, args: Dict[str, Any], mutating: bool = False) -> Dict[str, Any]:
        url = f"{self.base}/tools/{fn}"
        timeout = self.write_timeout if mutating else self.read_timeout

        try:
            r = httpx.post(url, json=args, timeout=timeout)
            if r.status_code >= 400:
                raise ToolError(f"{self.service.title()} MCP {fn} -> {r.status_code}: {r.text[:300]}")
            return r.json()
        except httpx.TimeoutException:
            raise ToolError(f"{self.service.title()} MCP {fn} timed out after {timeout}s")
```

```python
# gateway/main.py (additions)
from adapters.arr_mcp import ArrMCPClient

# Initialize MCP clients
docker_mcp = DockerMCPClient()
sonarr_mcp = ArrMCPClient("sonarr")
radarr_mcp = ArrMCPClient("radarr")

MCP_CLIENTS = {
    "docker-mcp": docker_mcp,
    "sonarr-mcp": sonarr_mcp,
    "radarr-mcp": radarr_mcp
}

@app.post("/chat/tool")
def run_tool(payload: dict):
    tool_name = payload["tool"]
    args = payload.get("args", {})

    if tool_name not in REG["tools"]:
        raise HTTPException(400, "Unknown tool")

    tool = REG["tools"][tool_name]
    service_name = tool["mcp"]["service"]

    # Get the appropriate MCP client
    mcp_client = MCP_CLIENTS.get(service_name)
    if not mcp_client:
        raise HTTPException(500, f"MCP service {service_name} not configured")

    try:
        result = mcp_client.call(tool["mcp"]["fn"], args, mutating=tool.get("mutating", False))
    except ToolError as e:
        raise HTTPException(502, str(e))

    return {"ok": True, "tool": tool_name, "result": result}
```

---

## 4) Schema Validation (Extended)

```yaml
# policy.yaml additions
schemas:
  sonarr_search_episode:
    type: object
    properties:
      episodeId: { type: integer, minimum: 1 }
    required: [episodeId]
    additionalProperties: false

  sonarr_refresh_series:
    type: object
    properties:
      seriesId: { type: integer, minimum: 1 }
    required: [seriesId]
    additionalProperties: false

  sonarr_remove_queue_item:
    type: object
    properties:
      id: { type: integer, minimum: 1 }
      removeFromClient: { type: boolean, default: false }
      blacklist: { type: boolean, default: false }
    required: [id]
    additionalProperties: false

  radarr_search_movie:
    type: object
    properties:
      movieId: { type: integer, minimum: 1 }
    required: [movieId]
    additionalProperties: false

  radarr_refresh_movie:
    type: object
    properties:
      movieId: { type: integer, minimum: 1 }
    required: [movieId]
    additionalProperties: false

  radarr_remove_queue_item:
    type: object
    properties:
      id: { type: integer, minimum: 1 }
      removeFromClient: { type: boolean, default: false }
      blacklist: { type: boolean, default: false }
    required: [id]
    additionalProperties: false

cooldowns:
  sonarr_search_episode: { seconds: 300, key: "episodeId" }
  sonarr_refresh_series: { seconds: 600, key: "seriesId" }
  radarr_search_movie: { seconds: 300, key: "movieId" }
  radarr_refresh_movie: { seconds: 600, key: "movieId" }
```

---

## 5) Custom MCP Server Implementation (Sonarr example)

```python
# sonarr-mcp-server/main.py (skeleton)
from fastapi import FastAPI
import httpx, os

app = FastAPI()

SONARR_BASE = os.getenv("SONARR_BASE_URL", "http://sonarr:8989")
API_KEY = open(os.getenv("SONARR_API_KEY_FILE")).read().strip()

class SonarrClient:
    def __init__(self):
        self.base = SONARR_BASE
        self.headers = {"X-Api-Key": API_KEY}

    def get(self, endpoint, params=None):
        url = f"{self.base}/api/v3/{endpoint}"
        r = httpx.get(url, headers=self.headers, params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def post(self, endpoint, data=None):
        url = f"{self.base}/api/v3/{endpoint}"
        r = httpx.post(url, headers=self.headers, json=data, timeout=30)
        r.raise_for_status()
        return r.json()

    def delete(self, endpoint):
        url = f"{self.base}/api/v3/{endpoint}"
        r = httpx.delete(url, headers=self.headers, timeout=10)
        r.raise_for_status()
        return r.json()

sonarr = SonarrClient()

@app.get("/health")
def health():
    try:
        sonarr.get("system/status")
        return {"status": "healthy"}
    except:
        return {"status": "unhealthy"}

@app.post("/tools/get_system_status")
def get_system_status(args: dict):
    return sonarr.get("system/status")

@app.post("/tools/get_queue")
def get_queue(args: dict):
    return sonarr.get("queue", {"includeUnknownSeriesItems": True})

@app.post("/tools/get_health")
def get_health(args: dict):
    return sonarr.get("health")

@app.post("/tools/search_episode")
def search_episode(args: dict):
    episode_id = args["episodeId"]
    return sonarr.post("command", {"name": "EpisodeSearch", "episodeIds": [episode_id]})

@app.post("/tools/remove_queue_item")
def remove_queue_item(args: dict):
    queue_id = args["id"]
    params = {
        "removeFromClient": args.get("removeFromClient", False),
        "blacklist": args.get("blacklist", False)
    }
    return sonarr.delete(f"queue/{queue_id}")
```

---

## 6) Prompt Examples

* "What's wrong with Sonarr?"
* "Show me the Radarr download queue"
* "Search for the latest episode of [Show]"
* "Refresh metadata for [Movie]"

---

## 7) Deployment Steps

1. Build custom MCP servers (`docker build ...`).
2. Add API key files under `./secrets`.
3. Deploy with `docker-compose -f docker-compose.ops.yml up -d`.
4. Test health endpoints and gateway proxying.

---

## 8) Benefits

* Isolated API management per app
* Rate limiting and error handling per service
* Rich toolset mapped to ARR APIs
* Consistent security + approval model across stack
* Easy to add more apps (Prowlarr, Overseerr, etc.)


1. Add Resource Limits to Docker Compose

2. Enhance error handling
@app.post("/tools/get_queue")
def get_queue(args: dict):
    try:
        return sonarr.get("queue", {"includeUnknownSeriesItems": True})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(401, "Invalid API key")
        elif e.response.status_code == 503:
            raise HTTPException(503, "Sonarr service unavailable")
        raise HTTPException(502, f"Sonarr API error: {e}")

  3. add calendar tools
  @app.post("/tools/get_calendar")
def get_calendar(args: dict):
    from datetime import datetime, timedelta
    end_date = (datetime.now() + timedelta(days=7)).isoformat()
    return sonarr.get("calendar", {"start": datetime.now().isoformat(), "end": end_date})

@app.post("/tools/get_disk_space")
def get_disk_space(args: dict):
    return sonarr.get("diskspace")

@app.post("/tools/get_wanted_missing")
def get_wanted_missing(args: dict):
    return sonarr.get("wanted/missing", {"pageSize": 50, "sortKey": "airDateUtc", "sortDirection": "descending"})


4. dockerfile ensure ports are not already in use (we use a lot already)
# sonarr-mcp-server/Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
RUN useradd -r -u 10002 sonarr-mcp
USER sonarr-mcp
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

5. quicj build scripts
# build.sh
#!/bin/bash
set -e

echo "Building Sonarr MCP Server..."
docker build -t yourorg/sonarr-mcp-server:latest ./sonarr-mcp-server/

echo "Building Radarr MCP Server..."
docker build -t yourorg/radarr-mcp-server:latest ./radarr-mcp-server/

echo "Getting API keys..."
mkdir -p secrets
echo "Paste Sonarr API key:"
read -s sonarr_key
echo "$sonarr_key" > secrets/sonarr_api_key.txt

echo "Paste Radarr API key:"
read -s radarr_key
echo "$radarr_key" > secrets/radarr_api_key.txt

echo "Starting services..."
docker-compose -f docker-compose.ops.yml up -d

echo "Testing health endpoints..."
sleep 10
curl -f http://localhost:8080/health || echo "Sonarr MCP health check failed"
curl -f http://localhost:8081/health || echo "Radarr MCP health check failed"
