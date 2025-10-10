"""
Pi Deployment MCP Service Definition
Intelligent Pi setup orchestration with AI-driven deployment workflows.
"""

from app.services.mcp_manager import MCPServiceInfo, MCPServiceStatus


def get_service_info():
    """Return service information for Pi Deployment MCP server."""
    return MCPServiceInfo(
        id="pi-deployment",
        name="Pi Deployment Assistant",
        description="Intelligent Pi setup and deployment orchestration with AI-driven workflows",
        port=8020,
        url="http://localhost:8020",
        status=MCPServiceStatus.STOPPED,
        auto_start=True,
        config_required=[],
        health_endpoint="/health"
    )