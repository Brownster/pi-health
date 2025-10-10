#!/usr/bin/env python3
"""
Pi Deployment MCP Server
Intelligent Pi setup and deployment orchestration.

This MCP server provides AI-friendly tools for:
- System preparation and optimization
- USB detection and mounting
- Network setup (VPN, Tailscale)
- Docker deployment orchestration
- Error recovery and rollback
"""

import argparse
import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Import our modular components
from modules.system_prep import SystemPrep
from modules.usb_manager import USBManager
from modules.network_setup import NetworkSetup
from modules.docker_orchestrator import DockerOrchestrator
from modules.pi_optimizer import PiOptimizer
from utils.deployment_logger import DeploymentLogger
from utils.error_recovery import ErrorRecovery

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PiDeploymentServer:
    """Main Pi Deployment MCP server class."""

    def __init__(self):
        self.app = FastAPI(
            title="Pi Deployment MCP",
            description="Intelligent Pi setup and deployment orchestration",
            version="1.0.0"
        )

        # Initialize components
        self.system_prep = SystemPrep()
        self.usb_manager = USBManager()
        self.network_setup = NetworkSetup()
        self.docker_orchestrator = DockerOrchestrator()
        self.pi_optimizer = PiOptimizer()
        self.deployment_logger = DeploymentLogger()
        self.error_recovery = ErrorRecovery()

        # Setup CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Register routes
        self._register_routes()

    def _register_routes(self):
        """Register API routes."""

        @self.app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {"status": "healthy", "service": "pi-deployment"}

        # System Preparation Tools
        @self.app.post("/api/system/prepare")
        async def prepare_system(config: Dict[str, Any]):
            """Prepare Pi system for deployment."""
            try:
                result = await self.system_prep.prepare_system(config)
                self.deployment_logger.log_action("system_prepare", result)
                return {"success": True, "result": result}
            except Exception as e:
                logger.error(f"System preparation failed: {e}")
                return {"success": False, "error": str(e)}

        @self.app.get("/api/system/info")
        async def get_system_info():
            """Get comprehensive Pi system information."""
            try:
                info = await self.system_prep.get_system_info()
                return {"success": True, "info": info}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # USB Management Tools
        @self.app.get("/api/usb/detect")
        async def detect_usb_devices():
            """Detect available USB storage devices."""
            try:
                devices = await self.usb_manager.detect_devices()
                return {"success": True, "devices": devices}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @self.app.post("/api/usb/mount")
        async def mount_usb_device(request: Dict[str, Any]):
            """Intelligently mount USB device with optimal settings."""
            try:
                device = request.get("device")
                mount_point = request.get("mount_point")
                options = request.get("options", {})

                result = await self.usb_manager.smart_mount(device, mount_point, options)
                self.deployment_logger.log_action("usb_mount", result)
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @self.app.get("/api/usb/status")
        async def get_usb_status():
            """Get status of all mounted USB devices."""
            try:
                status = await self.usb_manager.get_mount_status()
                return {"success": True, "status": status}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Network Setup Tools
        @self.app.post("/api/network/setup-vpn")
        async def setup_vpn(config: Dict[str, Any]):
            """Setup VPN with intelligent provider detection."""
            try:
                result = await self.network_setup.setup_vpn(config)
                self.deployment_logger.log_action("vpn_setup", result)
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @self.app.post("/api/network/setup-tailscale")
        async def setup_tailscale(config: Dict[str, Any]):
            """Setup Tailscale mesh networking."""
            try:
                result = await self.network_setup.setup_tailscale(config)
                self.deployment_logger.log_action("tailscale_setup", result)
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @self.app.get("/api/network/status")
        async def get_network_status():
            """Get comprehensive network status."""
            try:
                status = await self.network_setup.get_network_status()
                return {"success": True, "status": status}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Docker Deployment Tools
        @self.app.post("/api/docker/deploy-stack")
        async def deploy_docker_stack(config: Dict[str, Any]):
            """Deploy complete Docker stack with intelligent orchestration."""
            try:
                stack_type = config.get("type", "arr-stack")
                result = await self.docker_orchestrator.deploy_stack(stack_type, config)
                self.deployment_logger.log_action("docker_deploy", result)
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @self.app.get("/api/docker/stacks")
        async def get_available_stacks():
            """Get list of available deployment stacks."""
            try:
                stacks = await self.docker_orchestrator.get_available_stacks()
                return {"success": True, "stacks": stacks}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @self.app.get("/api/docker/status")
        async def get_docker_status():
            """Get Docker deployment status."""
            try:
                status = await self.docker_orchestrator.get_deployment_status()
                return {"success": True, "status": status}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Pi Optimization Tools
        @self.app.post("/api/pi/optimize")
        async def optimize_pi(config: Dict[str, Any]):
            """Optimize Pi system for specific workloads."""
            try:
                result = await self.pi_optimizer.optimize_system(config)
                self.deployment_logger.log_action("pi_optimize", result)
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @self.app.get("/api/pi/recommendations")
        async def get_optimization_recommendations():
            """Get AI-driven optimization recommendations."""
            try:
                recommendations = await self.pi_optimizer.get_recommendations()
                return {"success": True, "recommendations": recommendations}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Deployment Workflow Tools
        @self.app.post("/api/deploy/complete-setup")
        async def complete_pi_setup(config: Dict[str, Any]):
            """Execute complete Pi setup workflow."""
            try:
                workflow_id = config.get("workflow_id", "default")
                result = await self._execute_complete_workflow(workflow_id, config)
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @self.app.get("/api/deploy/workflows")
        async def get_available_workflows():
            """Get available deployment workflows."""
            try:
                workflows = await self._get_deployment_workflows()
                return {"success": True, "workflows": workflows}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @self.app.get("/api/deploy/status/{workflow_id}")
        async def get_workflow_status(workflow_id: str):
            """Get deployment workflow status."""
            try:
                status = await self._get_workflow_status(workflow_id)
                return {"success": True, "status": status}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Error Recovery Tools
        @self.app.post("/api/recovery/rollback")
        async def rollback_deployment(request: Dict[str, Any]):
            """Rollback failed deployment."""
            try:
                deployment_id = request.get("deployment_id")
                result = await self.error_recovery.rollback(deployment_id)
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @self.app.get("/api/recovery/snapshots")
        async def get_recovery_snapshots():
            """Get available recovery snapshots."""
            try:
                snapshots = await self.error_recovery.get_snapshots()
                return {"success": True, "snapshots": snapshots}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Logging and Monitoring
        @self.app.get("/api/logs/deployment/{deployment_id}")
        async def get_deployment_logs(deployment_id: str):
            """Get logs for specific deployment."""
            try:
                logs = await self.deployment_logger.get_logs(deployment_id)
                return {"success": True, "logs": logs}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @self.app.get("/api/logs/recent")
        async def get_recent_logs():
            """Get recent deployment activity."""
            try:
                logs = await self.deployment_logger.get_recent_logs()
                return {"success": True, "logs": logs}
            except Exception as e:
                return {"success": False, "error": str(e)}

    async def _execute_complete_workflow(self, workflow_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a complete Pi setup workflow."""
        logger.info(f"Starting complete Pi setup workflow: {workflow_id}")

        workflow_status = {
            "workflow_id": workflow_id,
            "status": "running",
            "steps": [],
            "current_step": None
        }

        try:
            # Step 1: System preparation
            workflow_status["current_step"] = "system_prep"
            logger.info("Step 1: Preparing system...")
            system_result = await self.system_prep.prepare_system(config)
            workflow_status["steps"].append({
                "step": "system_prep",
                "status": "completed",
                "result": system_result
            })

            # Step 2: USB setup if configured
            if config.get("setup_usb", False):
                workflow_status["current_step"] = "usb_setup"
                logger.info("Step 2: Setting up USB storage...")
                usb_result = await self.usb_manager.auto_setup(config.get("usb_config", {}))
                workflow_status["steps"].append({
                    "step": "usb_setup",
                    "status": "completed",
                    "result": usb_result
                })

            # Step 3: Network setup
            workflow_status["current_step"] = "network_setup"
            logger.info("Step 3: Configuring network...")
            network_result = await self.network_setup.setup_complete_network(config.get("network_config", {}))
            workflow_status["steps"].append({
                "step": "network_setup",
                "status": "completed",
                "result": network_result
            })

            # Step 4: Docker stack deployment
            workflow_status["current_step"] = "docker_deployment"
            logger.info("Step 4: Deploying Docker stack...")
            docker_result = await self.docker_orchestrator.deploy_stack(
                config.get("stack_type", "arr-stack"),
                config.get("docker_config", {})
            )
            workflow_status["steps"].append({
                "step": "docker_deployment",
                "status": "completed",
                "result": docker_result
            })

            # Step 5: Pi optimization
            workflow_status["current_step"] = "pi_optimization"
            logger.info("Step 5: Optimizing Pi system...")
            optimization_result = await self.pi_optimizer.optimize_system(config.get("optimization_config", {}))
            workflow_status["steps"].append({
                "step": "pi_optimization",
                "status": "completed",
                "result": optimization_result
            })

            workflow_status["status"] = "completed"
            workflow_status["current_step"] = None

            logger.info(f"Pi setup workflow {workflow_id} completed successfully")
            self.deployment_logger.log_workflow(workflow_id, workflow_status)

            return workflow_status

        except Exception as e:
            logger.error(f"Workflow {workflow_id} failed at step {workflow_status['current_step']}: {e}")
            workflow_status["status"] = "failed"
            workflow_status["error"] = str(e)

            # Attempt recovery
            recovery_result = await self.error_recovery.handle_workflow_failure(workflow_id, workflow_status)
            workflow_status["recovery"] = recovery_result

            return workflow_status

    async def _get_deployment_workflows(self) -> List[Dict[str, Any]]:
        """Get available deployment workflows."""
        return [
            {
                "id": "minimal-setup",
                "name": "Minimal Pi Setup",
                "description": "Basic Pi preparation with essential tools",
                "estimated_time": "5-10 minutes",
                "requirements": ["Pi 4", "8GB+ SD card"]
            },
            {
                "id": "media-server",
                "name": "Complete Media Server",
                "description": "Full Arr stack with VPN and optimization",
                "estimated_time": "15-30 minutes",
                "requirements": ["Pi 4", "32GB+ storage", "VPN subscription"]
            },
            {
                "id": "development-stack",
                "name": "Development Environment",
                "description": "Pi setup optimized for development work",
                "estimated_time": "10-20 minutes",
                "requirements": ["Pi 4", "16GB+ storage"]
            },
            {
                "id": "custom-workflow",
                "name": "Custom Workflow",
                "description": "User-defined deployment workflow",
                "estimated_time": "Variable",
                "requirements": ["Custom configuration"]
            }
        ]

    async def _get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status from deployment logger."""
        return await self.deployment_logger.get_workflow_status(workflow_id)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Pi Deployment MCP Server")
    parser.add_argument("--port", type=int, default=8020, help="Port to run on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")

    args = parser.parse_args()

    # Initialize server
    server = PiDeploymentServer()

    # Configure logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Run server
    logger.info(f"Starting Pi Deployment MCP server on {args.host}:{args.port}")
    uvicorn.run(
        server.app,
        host=args.host,
        port=args.port,
        log_level="info" if not args.debug else "debug"
    )


if __name__ == "__main__":
    main()