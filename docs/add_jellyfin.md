# Jellyfin MCP Integration Guide

This guide extends your media server MCP pattern to include Jellyfin management. Jellyfin has unique streaming, library management, and user administration capabilities that require specialized tools for content scanning, transcoding management, and user experience optimization.

---

## 1) Extended Docker Compose

```yaml
version: "3.9"

services:
  # Existing services (docker-mcp, *arr-mcp, sabnzbd-mcp)...

  # NEW: Jellyfin MCP Server
  jellyfin-mcp:
    image: yourorg/jellyfin-mcp-server:latest
    container_name: mcp-jellyfin
    user: "10005:10005"
    environment:
      LOG_LEVEL: INFO
      JELLYFIN_BASE_URL: http://jellyfin:8096
      JELLYFIN_API_KEY_FILE: /run/secrets/jellyfin_api_key
      JELLYFIN_USER_ID_FILE: /run/secrets/jellyfin_user_id  # Admin user ID
      RATE_LIMIT_RPM: 30  # Conservative for transcoding load
      MAX_CONCURRENT_SCANS: 2  # Prevent Pi overload
    secrets:
      - jellyfin_api_key
      - jellyfin_user_id
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
      timeout: 10s  # Jellyfin can be slow to respond
      retries: 3

networks:
  ops_net:
    driver: bridge

secrets:
  jellyfin_api_key:
    file: ./secrets/jellyfin_api_key.txt
  jellyfin_user_id:
    file: ./secrets/jellyfin_user_id.txt
```

---

## 2) Pi-Health Integration Steps

1. Deploy the Jellyfin MCP server alongside the services above (see the repository outlined earlier).
2. Set the following environment variable before restarting Pi-Health:

   ```bash
   JELLYFIN_MCP_BASE_URL=http://jellyfin-mcp:8080
   ```

   (Optional) override `MCP_READ_TIMEOUT`/`MCP_WRITE_TIMEOUT` if the default 5s/30s windows need tuning.

3. Restart the Flask app (`docker compose restart pi-health-dashboard`, `systemctl restart`, etc.).
4. Visit Ops-Copilot and ask “Who is streaming right now?” — the response should include active session counts and failing tasks sourced from the MCP server. If the environment variable is absent, the assistant falls back to its static response.

---

## 3) Jellyfin Tool Registry

```yaml
services:
  jellyfin-mcp:
    base_url: http://jellyfin-mcp:8080
    transport: http
    auth: none

tools:
  # --- JELLYFIN READ-ONLY TOOLS ---
  jellyfin_system_info:
    mcp: { service: jellyfin-mcp, fn: get_system_info }
    mutating: false
    summary: "Get Jellyfin system info, version, and health"

  jellyfin_libraries:
    mcp: { service: jellyfin-mcp, fn: get_libraries }
    mutating: false
    summary: "List all media libraries and their status"

  jellyfin_active_sessions:
    mcp: { service: jellyfin-mcp, fn: get_sessions }
    mutating: false
    summary: "Show active streaming sessions and transcoding"

  jellyfin_recent_items:
    mcp: { service: jellyfin-mcp, fn: get_recent_items }
    mutating: false
    summary: "Show recently added movies and episodes"

  jellyfin_library_stats:
    mcp: { service: jellyfin-mcp, fn: get_library_stats }
    mutating: false
    summary: "Get library statistics (counts, sizes, etc.)"

  jellyfin_scheduled_tasks:
    mcp: { service: jellyfin-mcp, fn: get_scheduled_tasks }
    mutating: false
    summary: "Show status of scheduled tasks (scanning, cleanup)"

  jellyfin_activity_log:
    mcp: { service: jellyfin-mcp, fn: get_activity_log }
    mutating: false
    summary: "Get recent activity log entries"

  jellyfin_transcode_settings:
    mcp: { service: jellyfin-mcp, fn: get_transcode_settings }
    mutating: false
    summary: "Show current transcoding configuration"

  jellyfin_users:
    mcp: { service: jellyfin-mcp, fn: get_users }
    mutating: false
    summary: "List users and their last activity"

  jellyfin_plugins:
    mcp: { service: jellyfin-mcp, fn: get_plugins }
    mutating: false
    summary: "Show installed plugins and their status"

  # --- JELLYFIN MUTATING TOOLS ---
  jellyfin_scan_library:
    mcp: { service: jellyfin-mcp, fn: scan_library }
    mutating: true
    approval: required
    cooldown: { seconds: 300, key_by: library_id }
    summary: "Trigger library scan for new content"

  jellyfin_refresh_metadata:
    mcp: { service: jellyfin-mcp, fn: refresh_metadata }
    mutating: true
    approval: required
    cooldown: { seconds: 600, key_by: item_id }
    summary: "Refresh metadata for specific item"

  jellyfin_cancel_task:
    mcp: { service: jellyfin-mcp, fn: cancel_task }
    mutating: true
    approval: required
    summary: "Cancel running scheduled task"

  jellyfin_restart_service:
    mcp: { service: jellyfin-mcp, fn: restart_service }
    mutating: true
    approval: required
    roles: [admin]
    cooldown: { seconds: 600 }
    summary: "Restart Jellyfin service"

  jellyfin_shutdown_service:
    mcp: { service: jellyfin-mcp, fn: shutdown_service }
    mutating: true
    approval: required
    roles: [admin]
    summary: "Gracefully shutdown Jellyfin"

  jellyfin_clear_cache:
    mcp: { service: jellyfin-mcp, fn: clear_cache }
    mutating: true
    approval: required
    summary: "Clear Jellyfin image and metadata cache"

  jellyfin_optimize_database:
    mcp: { service: jellyfin-mcp, fn: optimize_database }
    mutating: true
    approval: required
    roles: [admin]
    cooldown: { seconds: 3600 }
    summary: "Optimize Jellyfin database (may cause brief downtime)"

  jellyfin_enable_plugin:
    mcp: { service: jellyfin-mcp, fn: enable_plugin }
    mutating: true
    approval: required
    roles: [admin]
    summary: "Enable a disabled plugin"

  jellyfin_disable_plugin:
    mcp: { service: jellyfin-mcp, fn: disable_plugin }
    mutating: true
    approval: required
    roles: [admin]
    summary: "Disable an active plugin"
```

---

## 3) Schema Validation

```yaml
# policy.yaml additions
schemas:
  jellyfin_scan_library:
    type: object
    properties:
      library_id: { type: string, pattern: "^[a-f0-9]{32}$" }  # Jellyfin GUID format
    required: [library_id]
    additionalProperties: false

  jellyfin_refresh_metadata:
    type: object
    properties:
      item_id: { type: string, pattern: "^[a-f0-9]{32}$" }
      replace_all_metadata: { type: boolean, default: false }
      replace_all_images: { type: boolean, default: false }
    required: [item_id]
    additionalProperties: false

  jellyfin_cancel_task:
    type: object
    properties:
      task_id: { type: string, pattern: "^[a-f0-9]{32}$" }
    required: [task_id]
    additionalProperties: false

  jellyfin_get_recent_items:
    type: object
    properties:
      limit: { type: integer, minimum: 1, maximum: 100, default: 20 }
      user_id: { type: string, pattern: "^[a-f0-9]{32}$" }
    additionalProperties: false

  jellyfin_get_activity_log:
    type: object
    properties:
      start_index: { type: integer, minimum: 0, default: 0 }
      limit: { type: integer, minimum: 1, maximum: 100, default: 50 }
      min_date: { type: string, format: "date-time" }
    additionalProperties: false

  jellyfin_enable_plugin:
    type: object
    properties:
      plugin_id: { type: string, pattern: "^[a-zA-Z0-9._-]+$" }
      version: { type: string, pattern: "^\\d+\\.\\d+\\.\\d+$" }
    required: [plugin_id]
    additionalProperties: false

  jellyfin_disable_plugin:
    type: object
    properties:
      plugin_id: { type: string, pattern: "^[a-zA-Z0-9._-]+$" }
    required: [plugin_id]
    additionalProperties: false

# Extended cooldowns
cooldowns:
  jellyfin_scan_library: { seconds: 300, key: "library_id" }
  jellyfin_refresh_metadata: { seconds: 600, key: "item_id" }
  jellyfin_restart_service: { seconds: 600 }
  jellyfin_optimize_database: { seconds: 3600 }
```

---

## 4) Jellyfin MCP Server Implementation

```python
# jellyfin-mcp-server/main.py
from fastapi import FastAPI, HTTPException
import httpx
import os
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

app = FastAPI()

JELLYFIN_BASE = os.getenv("JELLYFIN_BASE_URL", "http://jellyfin:8096")
API_KEY = open(os.getenv("JELLYFIN_API_KEY_FILE")).read().strip()
USER_ID = open(os.getenv("JELLYFIN_USER_ID_FILE")).read().strip()
MAX_CONCURRENT_SCANS = int(os.getenv("MAX_CONCURRENT_SCANS", "2"))

class JellyfinClient:
    def __init__(self):
        self.base = JELLYFIN_BASE
        self.headers = {
            "X-Emby-Token": API_KEY,
            "X-MediaBrowser-Token": API_KEY,  # Alternative header for compatibility
            "Content-Type": "application/json"
        }
    
    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make GET request to Jellyfin API"""
        url = f"{self.base}/{endpoint.lstrip('/')}"
        try:
            response = httpx.get(url, headers=self.headers, params=params or {}, timeout=20)
            response.raise_for_status()
            return response.json() if response.content else {}
        except httpx.TimeoutException:
            raise HTTPException(504, f"Jellyfin API timeout for {endpoint}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise HTTPException(401, "Jellyfin API authentication failed")
            elif e.response.status_code == 404:
                raise HTTPException(404, f"Jellyfin endpoint not found: {endpoint}")
            raise HTTPException(502, f"Jellyfin API error: {e.response.status_code}")
        except json.JSONDecodeError:
            raise HTTPException(500, "Jellyfin returned invalid JSON")
    
    def _post(self, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make POST request to Jellyfin API"""
        url = f"{self.base}/{endpoint.lstrip('/')}"
        try:
            response = httpx.post(
                url, 
                headers=self.headers, 
                json=data or {}, 
                params=params or {},
                timeout=30
            )
            response.raise_for_status()
            return response.json() if response.content else {"success": True}
        except httpx.HTTPStatusError as e:
            raise HTTPException(502, f"Jellyfin API error: {e.response.status_code}")

jellyfin = JellyfinClient()

@app.get("/health")
def health():
    try:
        result = jellyfin._get("System/Info/Public")
        return {
            "status": "healthy", 
            "version": result.get("Version", "unknown"),
            "server_name": result.get("ServerName", "Jellyfin")
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

# --- READ-ONLY ENDPOINTS ---

@app.post("/tools/get_system_info")
def get_system_info(args: dict):
    """Get comprehensive Jellyfin system information"""
    info = jellyfin._get("System/Info")
    return {
        "version": info.get("Version"),
        "operating_system": info.get("OperatingSystem"),
        "server_name": info.get("ServerName"),
        "local_address": info.get("LocalAddress"),
        "wan_address": info.get("WanAddress"),
        "has_pending_restart": info.get("HasPendingRestart", False),
        "is_shutting_down": info.get("IsShuttingDown", False),
        "cache_path": info.get("CachePath"),
        "log_path": info.get("LogPath")
    }

@app.post("/tools/get_libraries")
def get_libraries(args: dict):
    """Get all media libraries and their basic info"""
    libraries = jellyfin._get(f"Users/{USER_ID}/Views")
    
    result = []
    for lib in libraries.get("Items", []):
        if lib.get("CollectionType") in ["movies", "tvshows", "music"]:
            result.append({
                "id": lib.get("Id"),
                "name": lib.get("Name"),
                "type": lib.get("CollectionType"),
                "path": lib.get("Path"),
                "item_count": lib.get("ChildCount", 0)
            })
    
    return {"libraries": result}

@app.post("/tools/get_sessions")
def get_sessions(args: dict):
    """Get active streaming sessions"""
    sessions = jellyfin._get("Sessions")
    
    active_sessions = []
    for session in sessions:
        if session.get("NowPlayingItem"):
            active_sessions.append({
                "user_name": session.get("UserName"),
                "client": session.get("Client"),
                "device_name": session.get("DeviceName"),
                "now_playing": session.get("NowPlayingItem", {}).get("Name"),
                "play_state": session.get("PlayState", {}),
                "transcode_info": session.get("TranscodingInfo")
            })
    
    return {"active_sessions": active_sessions, "total_count": len(sessions)}

@app.post("/tools/get_recent_items")
def get_recent_items(args: dict):
    """Get recently added items"""
    limit = args.get("limit", 20)
    user_id = args.get("user_id", USER_ID)
    
    recent = jellyfin._get(f"Users/{user_id}/Items/Latest", {
        "Limit": limit,
        "Fields": "DateCreated,Overview,Genres,RunTimeTicks",
        "EnableImageTypes": "Primary,Backdrop,Thumb"
    })
    
    items = []
    for item in recent:
        items.append({
            "id": item.get("Id"),
            "name": item.get("Name"),
            "type": item.get("Type"),
            "year": item.get("ProductionYear"),
            "date_added": item.get("DateCreated"),
            "overview": item.get("Overview", "")[:200] + "..." if len(item.get("Overview", "")) > 200 else item.get("Overview", ""),
            "genres": item.get("Genres", [])
        })
    
    return {"recent_items": items}

@app.post("/tools/get_library_stats")
def get_library_stats(args: dict):
    """Get library statistics"""
    stats = []
    libraries = jellyfin._get(f"Users/{USER_ID}/Views")
    
    for lib in libraries.get("Items", []):
        if lib.get("CollectionType") in ["movies", "tvshows", "music"]:
            lib_stats = jellyfin._get(f"Users/{USER_ID}/Items", {
                "ParentId": lib.get("Id"),
                "Recursive": True,
                "Fields": "DateCreated"
            })
            
            stats.append({
                "library_name": lib.get("Name"),
                "library_type": lib.get("CollectionType"),
                "total_items": lib_stats.get("TotalRecordCount", 0),
                "library_id": lib.get("Id")
            })
    
    return {"library_stats": stats}

@app.post("/tools/get_scheduled_tasks")
def get_scheduled_tasks(args: dict):
    """Get status of scheduled tasks"""
    tasks = jellyfin._get("ScheduledTasks")
    
    task_info = []
    for task in tasks:
        task_info.append({
            "id": task.get("Id"),
            "name": task.get("Name"),
            "state": task.get("State"),
            "current_progress": task.get("CurrentProgressPercentage"),
            "last_execution_result": task.get("LastExecutionResult", {}),
            "next_run_time": task.get("NextRunTime")
        })
    
    return {"scheduled_tasks": task_info}

@app.post("/tools/get_activity_log")
def get_activity_log(args: dict):
    """Get recent activity log entries"""
    start_index = args.get("start_index", 0)
    limit = args.get("limit", 50)
    min_date = args.get("min_date")
    
    params = {
        "StartIndex": start_index,
        "Limit": limit
    }
    if min_date:
        params["MinDate"] = min_date
    
    log_entries = jellyfin._get("System/ActivityLog/Entries", params)
    
    return {
        "entries": log_entries.get("Items", []),
        "total_count": log_entries.get("TotalRecordCount", 0)
    }

@app.post("/tools/get_transcode_settings")
def get_transcode_settings(args: dict):
    """Get current transcoding configuration"""
    config = jellyfin._get("System/Configuration/encoding")
    
    return {
        "transcoding_temp_path": config.get("TranscodingTempPath"),
        "hardware_acceleration": config.get("HardwareAccelerationType"),
        "enable_hardware_encoding": config.get("EnableHardwareEncoding", False),
        "max_muxing_queue_size": config.get("MaxMuxingQueueSize"),
        "enable_throttling": config.get("EnableThrottling", False)
    }

@app.post("/tools/get_users")
def get_users(args: dict):
    """Get all users and their info"""
    users = jellyfin._get("Users")
    
    user_info = []
    for user in users:
        user_info.append({
            "id": user.get("Id"),
            "name": user.get("Name"),
            "last_login_date": user.get("LastLoginDate"),
            "last_activity_date": user.get("LastActivityDate"),
            "is_administrator": user.get("Policy", {}).get("IsAdministrator", False),
            "is_disabled": user.get("Policy", {}).get("IsDisabled", False)
        })
    
    return {"users": user_info}

@app.post("/tools/get_plugins")
def get_plugins(args: dict):
    """Get installed plugins"""
    plugins = jellyfin._get("Plugins")
    
    plugin_info = []
    for plugin in plugins:
        plugin_info.append({
            "id": plugin.get("Id"),
            "name": plugin.get("Name"),
            "version": plugin.get("Version"),
            "status": "Active" if plugin.get("Status") == 1 else "Inactive",
            "description": plugin.get("Description")
        })
    
    return {"plugins": plugin_info}

# --- MUTATING ENDPOINTS ---

@app.post("/tools/scan_library")
def scan_library(args: dict):
    """Trigger library scan"""
    library_id = args["library_id"]
    
    # Check current running scans to prevent overload
    tasks = jellyfin._get("ScheduledTasks")
    running_scans = sum(1 for task in tasks if task.get("State") == "Running" and "Scan" in task.get("Name", ""))
    
    if running_scans >= MAX_CONCURRENT_SCANS:
        raise HTTPException(429, f"Too many concurrent scans running ({running_scans}/{MAX_CONCURRENT_SCANS})")
    
    return jellyfin._post(f"Library/Media/Updated", params={"tvdbId": library_id})

@app.post("/tools/refresh_metadata")
def refresh_metadata(args: dict):
    """Refresh metadata for specific item"""
    item_id = args["item_id"]
    replace_all_metadata = args.get("replace_all_metadata", False)
    replace_all_images = args.get("replace_all_images", False)
    
    params = {
        "Recursive": True,
        "MetadataRefreshMode": "FullRefresh" if replace_all_metadata else "Default",
        "ImageRefreshMode": "FullRefresh" if replace_all_images else "Default"
    }
    
    return jellyfin._post(f"Items/{item_id}/Refresh", params=params)

@app.post("/tools/cancel_task")
def cancel_task(args: dict):
    """Cancel a running scheduled task"""
    task_id = args["task_id"]
    return jellyfin._delete(f"ScheduledTasks/Running/{task_id}")

@app.post("/tools/restart_service")
def restart_service(args: dict):
    """Restart Jellyfin service"""
    return jellyfin._post("System/Restart")

@app.post("/tools/shutdown_service")
def shutdown_service(args: dict):
    """Gracefully shutdown Jellyfin"""
    return jellyfin._post("System/Shutdown")

@app.post("/tools/clear_cache")
def clear_cache(args: dict):
    """Clear Jellyfin cache"""
    # Clear image cache
    jellyfin._post("Images/Cache/Delete")
    
    return {"message": "Cache cleared successfully"}

@app.post("/tools/optimize_database")
def optimize_database(args: dict):
    """Optimize Jellyfin database"""
    return jellyfin._post("System/Tasks/OptimizeDatabase")

@app.post("/tools/enable_plugin")
def enable_plugin(args: dict):
    """Enable a plugin"""
    plugin_id = args["plugin_id"]
    version = args.get("version", "")
    
    return jellyfin._post(f"Plugins/{plugin_id}/{version}/Enable")

@app.post("/tools/disable_plugin")
def disable_plugin(args: dict):
    """Disable a plugin"""
    plugin_id = args["plugin_id"]
    
    return jellyfin._post(f"Plugins/{plugin_id}/Disable")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

---

## 5) Requirements and Dockerfile

```txt
# jellyfin-mcp-server/requirements.txt
fastapi==0.104.1
httpx==0.25.2
uvicorn[standard]==0.24.0
python-dateutil==2.8.2
```

```dockerfile
# jellyfin-mcp-server/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Create non-root user
RUN useradd -r -u 10005 jellyfin-mcp && \
    chown -R jellyfin-mcp:jellyfin-mcp /app

USER jellyfin-mcp

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

---

## 6) API Key Setup Script

```bash
#!/bin/bash
# get-jellyfin-credentials.sh

echo "=== Jellyfin API Key Setup ==="
echo "1. Open Jellyfin web interface (usually http://your-pi:8096)"
echo "2. Log in as admin user"
echo "3. Go to Dashboard > API Keys"
echo "4. Click 'Create API Key'"
echo "5. Give it a name like 'Ops-Copilot'"
echo "6. Copy the generated API key"
echo ""
echo "Enter the API key:"
read -s api_key
echo "$api_key" > ./secrets/jellyfin_api_key.txt

echo ""
echo "Now we need your admin user ID..."
echo "Enter admin username:"
read username

# Try to get user ID using the API key
USER_ID=$(curl -s "http://localhost:8096/Users" \
  -H "X-Emby-Token: $api_key" | \
  jq -r ".[] | select(.Name==\"$username\") | .Id")

if [ -n "$USER_ID" ]; then
    echo "$USER_ID" > ./secrets/jellyfin_user_id.txt
    echo "✅ Credentials saved successfully!"
else
    echo "❌ Could not retrieve user ID. Please check your API key and username."
    echo "You can manually add the user ID to ./secrets/jellyfin_user_id.txt"
fi
```

---

## 7) Common AI Prompt Examples

Your AI can now handle Jellyfin queries like:

**System Status:**
- "How is Jellyfin running?"
- "Are there any active streams?"
- "Show me system information"
- "Check for pending restarts"

**Library Management:**
- "Scan the Movies library for new content"
- "Show me recently added movies"
- "What's in my TV Shows library?"
- "Refresh metadata for this broken show"

**Performance & Troubleshooting:**
- "Why is streaming so slow?"
- "Cancel that stuck library scan"
- "Clear Jellyfin cache"
- "Show me transcoding settings"

**User Management:**
- "Who's currently watching something?"
- "Show me all users"
- "Check recent user activity"

---

## 8) Testing Commands

```bash
# Build the Jellyfin MCP server
docker build -t yourorg/jellyfin-mcp-server:latest ./jellyfin-mcp-server/

# Set up credentials
chmod +x get-jellyfin-credentials.sh
./get-jellyfin-credentials.sh

# Test health endpoint
curl -f http://localhost:8083/health

# Test system info
curl -X POST http://localhost:8083/tools/get_system_info \
     -H "Content-Type: application/json" -d '{}'

# Test via gateway
curl -X POST http://localhost:3000/chat/tool \
     -H "Content-Type: application/json" \
     -d '{"tool":"jellyfin_system_info","args":{}}'
```

---

## 9) Key Jellyfin-Specific Features

**Library Management:**
- Automated scanning with concurrency limits
- Metadata refresh for corrupted entries
- Library statistics and health monitoring

**Streaming Optimization:**
- Active session monitoring
- Transcoding status and settings
- Performance bottleneck identification

**System Administration:**
- Safe restart and shutdown procedures
- Database optimization for performance
- Plugin management and troubleshooting

**User Experience:**
- Recent content visibility
- Activity logging for troubleshooting
- Cache management for performance

---

## 10) Integration Benefits

**Complete Media Pipeline:**
- *arr apps manage acquisition → SABnzbd downloads → Jellyfin serves
- AI can trace issues end-to-end: "Why can't I watch this show?"
- Automated library scanning when downloads complete

**Family-Friendly Management:**
- Safe operations with approval workflows
- Clear explanations of what each action does
- User activity monitoring without privacy invasion

**Performance Optimization:**
- Intelligent transcoding management
- Cache clearing for troubleshooting
- Database optimization scheduling

This completes your comprehensive media server ops-copilot! Your daughters now have intelligent, safe access to manage every aspect of their media server: containers, indexing, downloading, and streaming.
