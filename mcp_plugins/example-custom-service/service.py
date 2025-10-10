"""
Example MCP Plugin Service Definition

This file defines your custom MCP service that will be auto-discovered by Pi-Health.
Copy this template to create your own MCP services.
"""

from app.services.mcp_manager import MCPServiceInfo, MCPServiceStatus


def get_service_info() -> MCPServiceInfo:
    """
    Return service information for auto-discovery.

    This function is called by the MCP manager to register your service.
    Customize the values below for your specific service.
    """
    return MCPServiceInfo(
        id="example-custom",  # Unique identifier (no spaces, use dashes)
        name="Example Custom Service",  # Display name
        description="A template for creating custom MCP services",  # Brief description
        port=8050,  # Unique port number (avoid conflicts with built-in services)
        url="http://localhost:8050",  # Service URL
        status=MCPServiceStatus.STOPPED,  # Initial status
        auto_start=True,  # Whether to enable auto-start/stop
        config_required=[  # Environment variables needed
            "EXAMPLE_API_KEY",
            "EXAMPLE_BASE_URL"
        ],
        health_endpoint="/health"  # Health check endpoint
    )