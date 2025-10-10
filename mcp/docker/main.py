from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List, Optional

import docker
from docker.errors import DockerException
from fastapi import FastAPI
from pydantic import BaseModel, Field, root_validator

from mcp.common.api import MCPHTTPError, register_exception_handler


class DockerMCPError(MCPHTTPError):
    ...


class ContainerSummary(BaseModel):
    id: str
    name: str
    image: str
    status: str
    labels: Dict[str, Any] = Field(default_factory=dict)


class DockerPSResponse(BaseModel):
    containers: List[ContainerSummary]


class ComposeService(BaseModel):
    name: Optional[str] = None
    service: Optional[str] = None
    state: Optional[str] = None
    status: Optional[str] = None
    id: Optional[str] = None

    class Config:
        extra = "allow"


class ComposePSResponse(BaseModel):
    services: List[ComposeService]


class ComposeActionRequest(BaseModel):
    service: str = Field(..., min_length=1)

    class Config:
        anystr_strip_whitespace = True
        extra = "allow"

    @root_validator(pre=True)
    def populate_service(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if "service" not in values and "container" in values:
            values["service"] = values["container"]
        return values


class ComposeActionResponse(BaseModel):
    status: str
    action: str
    service: str
    output: Optional[str] = None


app = FastAPI(title="Docker MCP Server", version="0.1.0")
register_exception_handler(app)

_COMPOSE_FILE = os.getenv("COMPOSE_FILE")
_DOCKER_CLIENT = docker.from_env()


def _compose_args() -> List[str]:
    args = ["docker", "compose"]
    if _COMPOSE_FILE:
        args.extend(["-f", _COMPOSE_FILE])
    return args


def _run_compose(args: List[str]) -> subprocess.CompletedProcess[str]:
    cmd = _compose_args() + args
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise DockerMCPError(detail)


@app.get("/health")
def health() -> Dict[str, str]:
    try:
        _DOCKER_CLIENT.ping()
    except DockerException as exc:
        raise DockerMCPError(str(exc), status_code=503) from exc
    return {"status": "healthy"}


@app.post("/tools/docker_ps", response_model=DockerPSResponse)
def docker_ps() -> DockerPSResponse:
    try:
        containers = _DOCKER_CLIENT.containers.list(all=True)
    except DockerException as exc:
        raise DockerMCPError(str(exc)) from exc

    payload = [
        ContainerSummary(
            id=container.id[:12],
            name=container.name,
            image=container.image.tags[0] if container.image.tags else container.image.short_id,
            status=container.status,
            labels=container.labels,
        )
        for container in containers
    ]
    return DockerPSResponse(containers=payload)


@app.post("/tools/compose_ps", response_model=ComposePSResponse)
def compose_ps() -> ComposePSResponse:
    result = _run_compose(["ps", "--format", "json"])
    output = result.stdout.strip()
    if not output:
        return ComposePSResponse(services=[])
    try:
        services_raw = json.loads(output)
    except json.JSONDecodeError as exc:
        raise DockerMCPError(f"Failed to parse compose output: {exc}") from exc
    services = [ComposeService.parse_obj(item) for item in services_raw]
    return ComposePSResponse(services=services)


def _compose_action(action: str, payload: ComposeActionRequest) -> ComposeActionResponse:
    completed = _run_compose([action, payload.service])
    stdout = completed.stdout.strip() or None
    return ComposeActionResponse(status="ok", action=action, service=payload.service, output=stdout)


@app.post("/tools/compose_restart", response_model=ComposeActionResponse)
def compose_restart(body: ComposeActionRequest) -> ComposeActionResponse:
    return _compose_action("restart", body)


@app.post("/tools/compose_start", response_model=ComposeActionResponse)
def compose_start(body: ComposeActionRequest) -> ComposeActionResponse:
    return _compose_action("start", body)


@app.post("/tools/compose_stop", response_model=ComposeActionResponse)
def compose_stop(body: ComposeActionRequest) -> ComposeActionResponse:
    return _compose_action("stop", body)


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Docker MCP Service")
    parser.add_argument("--port", type=int, default=8080, help="Port to run on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)
