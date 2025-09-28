# Jellyseerr MCP Integration Guide

This guide adds a **Jellyseerr** MCP server to your ops‑copilot stack so non‑technical users can search, request, and review media via Jellyseerr (Overseerr‑style request manager that supports Jellyfin/Plex). It mirrors your Docker/ARR/Jellyfin pattern: **Gateway = policy + approvals + audit; MCP Server = execution; least‑privilege by default.**

---

## 0) Pi-Health Integration Quickstart

1. Deploy the Jellyseerr MCP server from this guide’s compose snippet and confirm it reports `healthy` (`curl http://jellyseerr-mcp:8080/health`).
2. Export `JELLYSEERR_MCP_BASE_URL=http://jellyseerr-mcp:8080` for the Pi-Health app (plus optional `MCP_READ_TIMEOUT` / `MCP_WRITE_TIMEOUT` overrides) and restart the container/service.
3. Ask Ops-Copilot “Any pending requests?” — the assistant now summarises pending vs approved counts sourced from Jellyseerr. Unset the variable to disable the tool without code changes.

---

## 1) Extended Docker Compose

```yaml
version: "3.9"

services:
  # (Already present) Docker MCP + optional socket proxy + AI gateway ...

  # NEW: Jellyseerr MCP Server
  jellyseerr-mcp:
    image: yourorg/jellyseerr-mcp-server:latest
    container_name: mcp-jellyseerr
    user: "10006:10006"
    environment:
      LOG_LEVEL: INFO
      JELLYSEERR_BASE_URL: http://jellyseerr:5055
      JELLYSEERR_API_KEY_FILE: /run/secrets/jellyseerr_api_key
      RATE_LIMIT_RPM: 30
      DEFAULT_IS_4K: "false"
    secrets:
      - jellyseerr_api_key
    networks: [ops_net]
    restart: unless-stopped
    read_only: true
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3

networks:
  ops_net:
    driver: bridge

secrets:
  jellyseerr_api_key:
    file: ./secrets/jellyseerr_api_key.txt
```

> Place the API key in `./secrets/jellyseerr_api_key.txt`. The MCP server uses it server‑side; never expose it to the browser.

---

## 2) Tool Registry (gateway) — `tool_registry.yaml`

```yaml
services:
  jellyseerr-mcp:
    base_url: http://jellyseerr-mcp:8080
    transport: http
    auth: none

tools:
  # ---------- READ-ONLY ----------
  jellyseerr_status:
    mcp: { service: jellyseerr-mcp, fn: get_status }
    mutating: false
    summary: "Server status (version, media server links, health)."

  jellyseerr_search_media:
    mcp: { service: jellyseerr-mcp, fn: search_media }
    mutating: false
    summary: "Search TMDB via Jellyseerr and return deduped results."

  jellyseerr_requests_list:
    mcp: { service: jellyseerr-mcp, fn: get_requests }
    mutating: false
    summary: "List recent requests with approval/download states."

  jellyseerr_request_detail:
    mcp: { service: jellyseerr-mcp, fn: get_request }
    mutating: false
    summary: "Fetch a single request by id."

  # ---------- MUTATING (approval required) ----------
  jellyseerr_request_movie:
    mcp: { service: jellyseerr-mcp, fn: request_movie }
    mutating: true
    approval: required
    cooldown: { seconds: 60, key_by: tmdbId }
    summary: "Create a movie request (optionally 4K)."

  jellyseerr_request_tv:
    mcp: { service: jellyseerr-mcp, fn: request_tv }
    mutating: true
    approval: required
    cooldown: { seconds: 60, key_by: tmdbId }
    summary: "Create a TV request (full/partial seasons)."

  jellyseerr_approve_request:
    mcp: { service: jellyseerr-mcp, fn: approve_request }
    mutating: true
    approval: required
    roles: [admin]
    summary: "Approve a pending request (admin only)."

  jellyseerr_delete_request:
    mcp: { service: jellyseerr-mcp, fn: delete_request }
    mutating: true
    approval: required
    roles: [admin]
    summary: "Delete/cancel a request (admin only)."
```

---

## 3) Policy & Validation (gateway) — `policy.yaml` additions

```yaml
schemas:
  jellyseerr_search_media:
    type: object
    properties:
      query: { type: string, minLength: 1 }
      page:  { type: integer, minimum: 1, maximum: 10, default: 1 }
      mediaType: { type: string, enum: ["movie","tv","multi"], default: "multi" }
    required: [query]
    additionalProperties: false

  jellyseerr_request_movie:
    type: object
    properties:
      tmdbId: { type: integer, minimum: 1 }
      is4k:   { type: boolean, default: false }
      serverId: { type: integer, minimum: 1 }
      profileId: { type: integer, minimum: 1 }
      rootFolderId: { type: integer, minimum: 1 }
      # Above ids are optional; use Jellyseerr defaults if omitted
    required: [tmdbId]
    additionalProperties: false

  jellyseerr_request_tv:
    type: object
    properties:
      tmdbId: { type: integer, minimum: 1 }
      is4k:   { type: boolean, default: false }
      seasons: {
        type: array,
        items: { type: integer, minimum: 0 },
        minItems: 0,
        uniqueItems: true
      }
      serverId: { type: integer, minimum: 1 }
      profileId: { type: integer, minimum: 1 }
      rootFolderId: { type: integer, minimum: 1 }
    required: [tmdbId]
    additionalProperties: false

  jellyseerr_approve_request:
    type: object
    properties:
      id: { type: integer, minimum: 1 }
    required: [id]
    additionalProperties: false

  jellyseerr_delete_request:
    type: object
    properties:
      id: { type: integer, minimum: 1 }
    required: [id]
    additionalProperties: false

cooldowns:
  jellyseerr_request_movie: { seconds: 60, key: "tmdbId" }
  jellyseerr_request_tv:    { seconds: 60, key: "tmdbId" }
```

> Keep the RBAC you already use: standard users can request; only **admin** can approve/delete. Your gateway enforces approvals and roles before contacting the MCP.

---

## 4) Jellyseerr MCP Server — implementation skeleton

```python
# jellyseerr-mcp-server/main.py
from fastapi import FastAPI, HTTPException
import httpx, os
from typing import Any, Dict, Optional

app = FastAPI()

BASE = os.getenv("JELLYSEERR_BASE_URL", "http://jellyseerr:5055").rstrip("/")
API_KEY_PATH = os.getenv("JELLYSEERR_API_KEY_FILE", "/run/secrets/jellyseerr_api_key")
API_KEY = open(API_KEY_PATH).read().strip()
HEADERS = {"X-Api-Key": API_KEY, "Content-Type": "application/json"}

READ_TIMEOUT = float(os.getenv("READ_TIMEOUT", "6.0"))
WRITE_TIMEOUT = float(os.getenv("WRITE_TIMEOUT", "20.0"))
DEFAULT_IS_4K = os.getenv("DEFAULT_IS_4K", "false").lower() == "true"

class JSClient:
    def __init__(self, base: str):
        self.base = base

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None):
        url = f"{self.base}{path}"
        r = httpx.get(url, headers=HEADERS, params=params or {}, timeout=READ_TIMEOUT)
        r.raise_for_status(); return r.json()

    def _post(self, path: str, data: Dict[str, Any]):
        url = f"{self.base}{path}"
        r = httpx.post(url, headers=HEADERS, json=data, timeout=WRITE_TIMEOUT)
        r.raise_for_status(); return r.json() if r.content else {"ok": True}

    def _delete(self, path: str):
        url = f"{self.base}{path}"
        r = httpx.delete(url, headers=HEADERS, timeout=WRITE_TIMEOUT)
        r.raise_for_status(); return {"ok": True}

js = JSClient(BASE)

@app.get("/health")
def health():
    try:
        s = js._get("/api/v1/status")
        return {"status": "healthy", "version": s.get("version")}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

# ---------- READ-ONLY TOOLS ----------

@app.post("/tools/get_status")
def get_status(args: Dict[str, Any]):
    return js._get("/api/v1/status")

@app.post("/tools/search_media")
def search_media(args: Dict[str, Any]):
    query = args["query"]
    page = int(args.get("page", 1))
    media_type = args.get("mediaType", "multi")
    return js._get("/api/v1/search", {"query": query, "page": page, "mediaType": media_type})

@app.post("/tools/get_requests")
def get_requests(args: Dict[str, Any]):
    # Optional filters: take, skip, requestedBy, status etc. Keep minimal here.
    return js._get("/api/v1/request")

@app.post("/tools/get_request")
def get_request(args: Dict[str, Any]):
    rid = int(args["id"])
    return js._get(f"/api/v1/request/{rid}")

# ---------- MUTATING TOOLS ----------

@app.post("/tools/request_movie")
def request_movie(args: Dict[str, Any]):
    payload = {
        "mediaType": "movie",
        "tmdbId": int(args["tmdbId"]),
        "is4k": bool(args.get("is4k", DEFAULT_IS_4K))
    }
    # Optional server/profile/rootFolder ids if provided
    for k in ("serverId","profileId","rootFolderId"):
        if k in args: payload[k] = int(args[k])
    return js._post("/api/v1/request", payload)

@app.post("/tools/request_tv")
def request_tv(args: Dict[str, Any]):
    payload = {
        "mediaType": "tv",
        "tmdbId": int(args["tmdbId"]),
        "is4k": bool(args.get("is4k", DEFAULT_IS_4K))
    }
    # Optional specific seasons
    if "seasons" in args:
        payload["seasons"] = sorted({int(s) for s in args["seasons"]})
    for k in ("serverId","profileId","rootFolderId"):
        if k in args: payload[k] = int(args[k])
    return js._post("/api/v1/request", payload)

@app.post("/tools/approve_request")
def approve_request(args: Dict[str, Any]):
    rid = int(args["id"])
    return js._post(f"/api/v1/request/{rid}/approve", {})

@app.post("/tools/delete_request")
def delete_request(args: Dict[str, Any]):
    rid = int(args["id"])
    return js._delete(f"/api/v1/request/{rid}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

> Endpoints/fields may vary slightly by Jellyseerr version. Keep the client small and conservative, and prefer server defaults for server/profile/root folder unless explicitly supplied.

---

## 5) Requirements & Dockerfile

```txt
# jellyseerr-mcp-server/requirements.txt
fastapi==0.111.0
httpx==0.27.0
uvicorn[standard]==0.30.1
```

```dockerfile
# jellyseerr-mcp-server/Dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
RUN useradd -r -u 10006 jellyseerr-mcp && chown -R jellyseerr-mcp:jellyseerr-mcp /app
USER jellyseerr-mcp
EXPOSE 8080
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8080"]
```

---

## 6) Gateway wiring (client adapter is generic HTTP; reuse your existing adapter)

```python
# gateway/adapters/jellyseerr_mcp.py
import os, httpx
from typing import Any, Dict

BASE = os.getenv("JELLYSEERR_MCP_BASE","http://jellyseerr-mcp:8080")
READ=6.0; WRITE=20.0

class ToolError(Exception): ...

def call(fn: str, args: Dict[str, Any], mutating: bool=False):
    t = WRITE if mutating else READ
    r = httpx.post(f"{BASE}/tools/{fn}", json=args, timeout=t)
    if r.status_code >= 400:
        raise ToolError(f"jellyseerr {fn} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {"ok": True}
```

---

## 7) Testing & Smoke Checks

```bash
# Build & run
docker build -t yourorg/jellyseerr-mcp-server:latest ./jellyseerr-mcp-server/

# Put API key into secrets
mkdir -p secrets && echo "<YOUR_API_KEY>" > secrets/jellyseerr_api_key.txt

# Health
curl -fsS http://localhost:8080/health

# Search (direct)
curl -sX POST http://localhost:8080/tools/search_media \
  -H 'content-type: application/json' \
  -d '{"query":"Dune","mediaType":"movie"}' | jq .

# Request movie (via gateway)
curl -sX POST http://<gateway-host>/chat/tool \
  -H 'content-type: application/json' \
  -d '{"tool":"jellyseerr_request_movie","args":{"tmdbId":438631}}'
```

---

## 8) UX Flow (how it will feel to users)

* **"Request The Martian in 4K"** → model calls `search_media` → presents result → proposes `request_movie{tmdbId,is4k:true}` → **Action Card** → on approve, request created; assistant confirms.
* **"What did we request this week?"** → `get_requests` (read‑only) → friendly summary with statuses.
* **"Approve Alice’s request"** (admin) → `approve_request{id}` (approval required + RBAC) → success.

---

## 9) Notes & Gotchas

* RBAC: keep `approve/delete` admin‑only in `policy.yaml`.
* Cooldowns: 60s per TMDB id avoids duplicate spam.
* International results: pass `language`/`region` in `search_media` if you need localized titles; add to schema later.
* Privacy: requests may include usernames/emails; redact before echoing to chat history if you share transcripts.

---

## 10) Benefits

* **Single place** for requests (Jellyseerr) with safe, explainable actions through your assistant.
* **Consistent approvals** with your Docker/ARR/Jellyfin flows.
* **Easy to extend**: add tools for request updates, partial season selection UIs, or notifications (e.g., Gotify) when items become available.
