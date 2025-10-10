from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI

from mcp.common.api import register_exception_handler
from mcp.common.sabnzbd import SabnzbdClient

app = FastAPI(title="SABnzbd MCP Server", version="0.1.0")
register_exception_handler(app)


def _client() -> SabnzbdClient:
    return SabnzbdClient()


@app.get("/health")
def health() -> Dict[str, Any]:
    status = _client().status()
    return {"status": "healthy", "speed": status.get("kbpersec")}


@app.post("/tools/get_status")
def get_status() -> Dict[str, Any]:
    return _client().status()


@app.post("/tools/get_queue")
def get_queue() -> Dict[str, Any]:
    return _client().queue()


@app.post("/tools/get_warnings")
def get_warnings() -> Dict[str, Any]:
    return _client().warnings()


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="SABnzbd MCP Service")
    parser.add_argument("--port", type=int, default=8080, help="Port to run on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)
