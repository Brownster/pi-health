from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class MCPHTTPError(Exception):
    def __init__(self, message: str, status_code: int = 502, payload: Dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload or {"error": message}


def register_exception_handler(app: FastAPI) -> None:
    @app.exception_handler(MCPHTTPError)
    async def _mcp_http_error_handler(request: Request, exc: MCPHTTPError) -> JSONResponse:  # pragma: no cover - FastAPI glue
        return JSONResponse(status_code=exc.status_code, content=exc.payload)
