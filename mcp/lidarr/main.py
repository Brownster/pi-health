from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI
from pydantic import BaseModel, Field

from mcp.common.api import register_exception_handler
from mcp.common.arr import ArrClient

app = FastAPI(title="Lidarr MCP Server", version="0.1.0")
register_exception_handler(app)


def _client() -> ArrClient:
    return ArrClient(
        base_env="LIDARR_BASE_URL",
        default_base="http://lidarr:8686/api/v1",
        api_key_env="LIDARR_API_KEY",
        timeout_env="LIDARR_HTTP_TIMEOUT",
    )


class PagedRequest(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, alias="pageSize")

    class Config:
        allow_population_by_field_name = True
        extra = "forbid"

    def params(self) -> Dict[str, int]:
        return {"page": self.page, "pageSize": self.page_size}


@app.get("/health")
def health() -> Dict[str, Any]:
    status = _client().get("/system/status")
    return {"status": "healthy", "version": status.get("version")}


@app.post("/tools/get_system_status")
def get_system_status() -> Dict[str, Any]:
    return _client().get("/system/status")


@app.post("/tools/get_queue")
def get_queue(request: PagedRequest) -> Dict[str, Any]:
    return _client().get("/queue", params=request.params())


@app.post("/tools/get_health")
def get_health() -> Dict[str, Any]:
    return _client().get("/system/health")


@app.post("/tools/get_wanted_missing")
def get_wanted_missing(request: PagedRequest) -> Dict[str, Any]:
    return _client().get("/wanted/missing", params=request.params())


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Lidarr MCP Service")
    parser.add_argument("--port", type=int, default=8080, help="Port to run on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)
