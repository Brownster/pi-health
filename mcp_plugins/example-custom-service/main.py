#!/usr/bin/env python3
"""
Example MCP Service Implementation

This is a template FastAPI application that implements a custom MCP service.
Copy and modify this to create your own MCP services.

Required endpoints:
- GET /health - Health check endpoint
- Your custom endpoints for the AI agent to interact with
"""

import argparse
import os
from typing import Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn


# Custom service implementation
class ExampleService:
    """Your custom service implementation."""

    def __init__(self):
        # Initialize your service here
        self.api_key = os.getenv("EXAMPLE_API_KEY")
        self.base_url = os.getenv("EXAMPLE_BASE_URL", "http://localhost:8080")

        if not self.api_key:
            print("Warning: EXAMPLE_API_KEY not set")

    def get_status(self) -> Dict[str, Any]:
        """Get service status."""
        return {
            "service": "example-custom",
            "status": "healthy" if self.api_key else "configuration_missing",
            "config": {
                "api_key_configured": bool(self.api_key),
                "base_url": self.base_url
            }
        }

    def do_custom_action(self, action_data: Dict[str, Any]) -> Dict[str, Any]:
        """Perform a custom action - implement your logic here."""
        # Example implementation
        return {
            "success": True,
            "message": f"Custom action completed with data: {action_data}",
            "result": "example_result"
        }


# FastAPI app setup
app = FastAPI(
    title="Example Custom MCP Service",
    description="Template for custom MCP services in Pi-Health",
    version="1.0.0"
)

service = ExampleService()


# Required health endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint - required for all MCP services."""
    status = service.get_status()
    return {"status": "ok", **status}


# Custom endpoints - implement your API here
@app.get("/status")
async def get_status():
    """Get detailed service status."""
    return service.get_status()


class CustomActionRequest(BaseModel):
    action: str
    parameters: Dict[str, Any] = {}


@app.post("/custom-action")
async def custom_action(request: CustomActionRequest):
    """Example custom action endpoint."""
    try:
        result = service.do_custom_action({
            "action": request.action,
            "parameters": request.parameters
        })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/data")
async def get_data():
    """Example data endpoint."""
    # Implement your data retrieval logic here
    return {
        "data": [
            {"id": 1, "name": "Example Item 1", "value": 42},
            {"id": 2, "name": "Example Item 2", "value": 24}
        ],
        "total": 2,
        "timestamp": "2024-01-01T12:00:00Z"
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Example Custom MCP Service")
    parser.add_argument("--port", type=int, default=8050, help="Port to run on")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    args = parser.parse_args()

    print(f"Starting Example Custom MCP Service on {args.host}:{args.port}")

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info"
    )