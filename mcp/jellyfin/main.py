from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI

from mcp.common.api import register_exception_handler
from mcp.common.jellyfin import JellyfinClient

app = FastAPI(title="Jellyfin MCP Server", version="0.1.0")
register_exception_handler(app)


def _client() -> JellyfinClient:
    return JellyfinClient()


@app.get("/health")
def health() -> Dict[str, Any]:
    info = _client().system_info()
    version = info.get("Version") or info.get("version")
    return {"status": "healthy", "version": version}


@app.post("/tools/get_system_info")
def get_system_info() -> Dict[str, Any]:
    return _client().system_info()


@app.post("/tools/get_libraries")
def get_libraries() -> Dict[str, Any]:
    return _client().libraries()


@app.post("/tools/get_sessions")
def get_sessions() -> Dict[str, Any]:
    return _client().sessions()


@app.post("/tools/get_scheduled_tasks")
def get_scheduled_tasks() -> Dict[str, Any]:
    return _client().scheduled_tasks()


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Jellyfin MCP Service")
    parser.add_argument("--port", type=int, default=8080, help="Port to run on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)
