# SABnzbd MCP Integration Guide

This guide extends your *arr MCP pattern to include SABnzbd management. SABnzbd has unique download management capabilities that require specialized tools for queue management, speed control, and troubleshooting stalled downloads.

Expose `SABNZBD_MCP_BASE_URL` in the Pi-Health environment (sharing the global `MCP_*_TIMEOUT` values if desired) to enable the built-in `sabnzbd_status` tool. Ops-Copilot will then summarise queue size, speeds, and warnings inside chat responses whenever SABnzbd is mentioned.

Quick test loop:

1. Deploy the SABnzbd MCP server and confirm `curl http://sabnzbd-mcp:8080/health` returns `healthy`.
2. Set `SABNZBD_MCP_BASE_URL=http://sabnzbd-mcp:8080` for the Flask app, restart it, and open the Ops-Copilot UI.
3. Ask “What’s SABnzbd doing?” – the assistant echoes the live download speed, queue size, and top warnings. Clearing the env var reverts to the pre-MCP behaviour without restarting the MCP stack.

---

## 1) Extended Docker Compose

```yaml
version: "3.9"

services:
  # Existing services (docker-mcp, sonarr-mcp, radarr-mcp)...

  # NEW: SABnzbd MCP Server
  sabnzbd-mcp:
    image: yourorg/sabnzbd-mcp-server:latest
    container_name: mcp-sabnzbd
    user: "10004:10004"
    environment:
      LOG_LEVEL: INFO
      SABNZBD_BASE_URL: http://sabnzbd:8080
      SABNZBD_API_KEY_FILE: /run/secrets/sabnzbd_api_key
      RATE_LIMIT_RPM: 60  # SABnzbd can handle more frequent requests
      MAX_SPEED_LIMIT: 50000  # 50MB/s max speed limit for safety
    secrets:
      - sabnzbd_api_key
    networks: [ops_net]
    restart: unless-stopped
    read_only: true
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.25'
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3

networks:
  ops_net:
    driver: bridge

secrets:
  sabnzbd_api_key:
    file: ./secrets/sabnzbd_api_key.txt
```

---

## 2) SABnzbd Tool Registry

```yaml
services:
  sabnzbd-mcp:
    base_url: http://sabnzbd-mcp:8080
    transport: http
    auth: none

tools:
  # --- SABNZBD READ-ONLY TOOLS ---
  sabnzbd_status:
    mcp: { service: sabnzbd-mcp, fn: get_status }
    mutating: false
    summary: "Get SABnzbd status, speed, and queue info"

  sabnzbd_queue:
    mcp: { service: sabnzbd-mcp, fn: get_queue }
    mutating: false
    summary: "Show active download queue with progress"

  sabnzbd_history:
    mcp: { service: sabnzbd-mcp, fn: get_history }
    mutating: false
    summary: "Show recent download history (last 50 items)"

  sabnzbd_warnings:
    mcp: { service: sabnzbd-mcp, fn: get_warnings }
    mutating: false
    summary: "Get current warnings and errors"

  sabnzbd_server_stats:
    mcp: { service: sabnzbd-mcp, fn: get_server_stats }
    mutating: false
    summary: "Show Usenet server connection statistics"

  sabnzbd_disk_space:
    mcp: { service: sabnzbd-mcp, fn: get_disk_space }
    mutating: false
    summary: "Check available disk space for downloads"

  sabnzbd_version:
    mcp: { service: sabnzbd-mcp, fn: get_version }
    mutating: false
    summary: "Get SABnzbd version and system info"

  # --- SABNZBD MUTATING TOOLS ---
  sabnzbd_pause:
    mcp: { service: sabnzbd-mcp, fn: pause_queue }
    mutating: true
    approval: required
    summary: "Pause all downloads"

  sabnzbd_resume:
    mcp: { service: sabnzbd-mcp, fn: resume_queue }
    mutating: true
    approval: required
    summary: "Resume paused downloads"

  sabnzbd_set_speed_limit:
    mcp: { service: sabnzbd-mcp, fn: set_speed_limit }
    mutating: true
    approval: required
    cooldown: { seconds: 60 }
    summary: "Set download speed limit (KB/s)"

  sabnzbd_remove_speed_limit:
    mcp: { service: sabnzbd-mcp, fn: remove_speed_limit }
    mutating: true
    approval: required
    summary: "Remove download speed limit"

  sabnzbd_delete_item:
    mcp: { service: sabnzbd-mcp, fn: delete_queue_item }
    mutating: true
    approval: required
    summary: "Delete item from download queue"

  sabnzbd_delete_history:
    mcp: { service: sabnzbd-mcp, fn: delete_history_item }
    mutating: true
    approval: required
    summary: "Delete item from download history"

  sabnzbd_retry_failed:
    mcp: { service: sabnzbd-mcp, fn: retry_failed }
    mutating: true
    approval: required
    cooldown: { seconds: 300 }
    summary: "Retry failed download"

  sabnzbd_clear_warnings:
    mcp: { service: sabnzbd-mcp, fn: clear_warnings }
    mutating: true
    approval: required
    summary: "Clear all current warnings"

  sabnzbd_shutdown:
    mcp: { service: sabnzbd-mcp, fn: shutdown }
    mutating: true
    approval: required
    roles: [admin]
    summary: "Gracefully shutdown SABnzbd"

  sabnzbd_restart:
    mcp: { service: sabnzbd-mcp, fn: restart }
    mutating: true
    approval: required
    roles: [admin]
    cooldown: { seconds: 600 }
    summary: "Restart SABnzbd service"
```

---

## 3) Schema Validation

```yaml
# policy.yaml additions
schemas:
  sabnzbd_get_history:
    type: object
    properties:
      limit: { type: integer, minimum: 1, maximum: 100, default: 50 }
    additionalProperties: false

  sabnzbd_set_speed_limit:
    type: object
    properties:
      speed: { type: integer, minimum: 100, maximum: 50000 }  # 100KB/s to 50MB/s
    required: [speed]
    additionalProperties: false

  sabnzbd_delete_item:
    type: object
    properties:
      nzo_id: { type: string, pattern: "^SABnzbd_nzo_[a-zA-Z0-9]+$" }
      del_files: { type: boolean, default: false }
    required: [nzo_id]
    additionalProperties: false

  sabnzbd_delete_history_item:
    type: object
    properties:
      job_id: { type: string, pattern: "^[a-zA-Z0-9_]+$" }
      del_files: { type: boolean, default: false }
    required: [job_id]
    additionalProperties: false

  sabnzbd_retry_failed:
    type: object
    properties:
      job_id: { type: string, pattern: "^[a-zA-Z0-9_]+$" }
    required: [job_id]
    additionalProperties: false

# Extended cooldowns
cooldowns:
  sabnzbd_set_speed_limit: { seconds: 60 }
  sabnzbd_retry_failed: { seconds: 300 }
  sabnzbd_restart: { seconds: 600 }
```

---

## 4) SABnzbd MCP Server Implementation

```python
# sabnzbd-mcp-server/main.py
from fastapi import FastAPI, HTTPException
import httpx
import os
import json
from typing import Dict, Any, Optional

app = FastAPI()

SABNZBD_BASE = os.getenv("SABNZBD_BASE_URL", "http://sabnzbd:8080")
API_KEY = open(os.getenv("SABNZBD_API_KEY_FILE")).read().strip()
MAX_SPEED_LIMIT = int(os.getenv("MAX_SPEED_LIMIT", "50000"))

class SABnzbdClient:
    def __init__(self):
        self.base = f"{SABNZBD_BASE}/api"
        self.api_key = API_KEY
    
    def _call(self, mode: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make API call to SABnzbd"""
        call_params = {"mode": mode, "apikey": self.api_key, "output": "json"}
        if params:
            call_params.update(params)
        
        try:
            response = httpx.get(self.base, params=call_params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            if not data or "error" in data:
                raise HTTPException(500, f"SABnzbd API error: {data.get('error', 'Unknown error')}")
            
            return data
        except httpx.TimeoutException:
            raise HTTPException(504, "SABnzbd API timeout")
        except httpx.HTTPStatusError as e:
            raise HTTPException(502, f"SABnzbd API HTTP error: {e.response.status_code}")
        except json.JSONDecodeError:
            raise HTTPException(500, "SABnzbd returned invalid JSON")

sabnzbd = SABnzbdClient()

@app.get("/health")
def health():
    try:
        result = sabnzbd._call("version")
        return {"status": "healthy", "version": result.get("version", "unknown")}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

# --- READ-ONLY ENDPOINTS ---

@app.post("/tools/get_status")
def get_status(args: dict):
    """Get current SABnzbd status, speed, and basic queue info"""
    return sabnzbd._call("qstatus")

@app.post("/tools/get_queue")
def get_queue(args: dict):
    """Get detailed queue information"""
    return sabnzbd._call("queue")

@app.post("/tools/get_history")
def get_history(args: dict):
    """Get download history"""
    limit = args.get("limit", 50)
    return sabnzbd._call("history", {"limit": limit})

@app.post("/tools/get_warnings")
def get_warnings(args: dict):
    """Get current warnings and errors"""
    return sabnzbd._call("warnings")

@app.post("/tools/get_server_stats")
def get_server_stats(args: dict):
    """Get Usenet server statistics"""
    return sabnzbd._call("server_stats")

@app.post("/tools/get_disk_space")
def get_disk_space(args: dict):
    """Check available disk space"""
    status = sabnzbd._call("qstatus")
    return {
        "diskspace1": status.get("diskspace1", "unknown"),
        "diskspace2": status.get("diskspace2", "unknown"),
        "diskspacetotal1": status.get("diskspacetotal1", "unknown"),
        "diskspacetotal2": status.get("diskspacetotal2", "unknown")
    }

@app.post("/tools/get_version")
def get_version(args: dict):
    """Get SABnzbd version and system info"""
    return sabnzbd._call("version")

# --- MUTATING ENDPOINTS ---

@app.post("/tools/pause_queue")
def pause_queue(args: dict):
    """Pause all downloads"""
    return sabnzbd._call("pause")

@app.post("/tools/resume_queue")
def resume_queue(args: dict):
    """Resume paused downloads"""
    return sabnzbd._call("resume")

@app.post("/tools/set_speed_limit")
def set_speed_limit(args: dict):
    """Set download speed limit in KB/s"""
    speed = args["speed"]
    
    # Safety check against environment variable
    if speed > MAX_SPEED_LIMIT:
        raise HTTPException(400, f"Speed limit {speed} KB/s exceeds maximum allowed {MAX_SPEED_LIMIT} KB/s")
    
    return sabnzbd._call("config", {"name": "speedlimit", "value": str(speed)})

@app.post("/tools/remove_speed_limit")
def remove_speed_limit(args: dict):
    """Remove download speed limit"""
    return sabnzbd._call("config", {"name": "speedlimit", "value": "0"})

@app.post("/tools/delete_queue_item")
def delete_queue_item(args: dict):
    """Delete item from download queue"""
    nzo_id = args["nzo_id"]
    del_files = args.get("del_files", False)
    
    params = {"name": "delete", "value": nzo_id}
    if del_files:
        params["del_files"] = "1"
    
    return sabnzbd._call("queue", params)

@app.post("/tools/delete_history_item")
def delete_history_item(args: dict):
    """Delete item from download history"""
    job_id = args["job_id"]
    del_files = args.get("del_files", False)
    
    params = {"name": "delete", "value": job_id}
    if del_files:
        params["del_files"] = "1"
    
    return sabnzbd._call("history", params)

@app.post("/tools/retry_failed")
def retry_failed(args: dict):
    """Retry a failed download"""
    job_id = args["job_id"]
    return sabnzbd._call("retry", {"value": job_id})

@app.post("/tools/clear_warnings")
def clear_warnings(args: dict):
    """Clear all current warnings"""
    return sabnzbd._call("clear_warnings")

@app.post("/tools/shutdown")
def shutdown(args: dict):
    """Gracefully shutdown SABnzbd"""
    return sabnzbd._call("shutdown")

@app.post("/tools/restart")
def restart(args: dict):
    """Restart SABnzbd service"""
    return sabnzbd._call("restart")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

---

## 5) Requirements and Dockerfile

```txt
# sabnzbd-mcp-server/requirements.txt
fastapi==0.104.1
httpx==0.25.2
uvicorn[standard]==0.24.0
```

```dockerfile
# sabnzbd-mcp-server/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Create non-root user
RUN useradd -r -u 10004 sabnzbd-mcp && \
    chown -R sabnzbd-mcp:sabnzbd-mcp /app

USER sabnzbd-mcp

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

---

## 6) Common AI Prompt Examples

Your AI can now handle SABnzbd queries like:

**Status & Monitoring:**
- "What's SABnzbd doing right now?"
- "Show me the download queue"
- "Check SABnzbd disk space"
- "Are there any SABnzbd warnings?"

**Queue Management:**
- "Pause downloads for 30 minutes" 
- "Remove that stuck download"
- "Retry the failed download"
- "Set download speed to 5MB/s"

**Troubleshooting:**
- "Why are downloads slow?"
- "Clear SABnzbd warnings"
- "Show recent download history"
- "Check Usenet server connections"

---

## 7) Testing Commands

```bash
# Build the SABnzbd MCP server
docker build -t yourorg/sabnzbd-mcp-server:latest ./sabnzbd-mcp-server/

# Get SABnzbd API key
echo "your_sabnzbd_api_key" > ./secrets/sabnzbd_api_key.txt

# Test health endpoint
curl -f http://localhost:8082/health

# Test basic status
curl -X POST http://localhost:8082/tools/get_status \
     -H "Content-Type: application/json" -d '{}'

# Test via gateway
curl -X POST http://localhost:3000/chat/tool \
     -H "Content-Type: application/json" \
     -d '{"tool":"sabnzbd_status","args":{}}'
```

---

## 8) Key SABnzbd-Specific Features

**Download Management:**
- Real-time queue monitoring with ETA and progress
- Pause/resume functionality for bandwidth management
- Speed limiting for network-friendly downloading

**Error Handling:**
- Failed download retry mechanisms
- Warning and error reporting
- Server connection statistics

**Safety Features:**
- Speed limit enforcement (prevents network flooding)
- Confirmation required for destructive operations
- File deletion options with explicit approval

**Integration Benefits:**
- Works seamlessly with *arr applications
- Provides missing link between search and download
- Enables end-to-end media acquisition troubleshooting

This SABnzbd integration completes your media server management triangle: *arr apps find content → SABnzbd downloads it → Docker manages the containers. Your daughters now have full visibility and safe control over the entire pipeline!
