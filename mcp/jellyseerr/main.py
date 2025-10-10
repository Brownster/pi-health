from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI

from mcp.common.api import register_exception_handler
from mcp.common.jellyseerr import JellyseerrClient

app = FastAPI(title="Jellyseerr MCP Server", version="0.1.0")
register_exception_handler(app)


def _client() -> JellyseerrClient:
    return JellyseerrClient()


@app.get("/health")
def health() -> Dict[str, Any]:
    status = _client().status()
    return {"status": "healthy", "version": status.get("version")}


@app.post("/tools/get_status")
def get_status() -> Dict[str, Any]:
    return _client().status()


@app.post("/tools/get_requests")
def get_requests() -> Dict[str, Any]:
    return _client().requests()


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Jellyseerr MCP Service")
    parser.add_argument("--port", type=int, default=8080, help="Port to run on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)
