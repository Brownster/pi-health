#!/usr/bin/env python3
"""
Simple test script to verify MCP service endpoints work properly.
"""

import json
import requests
import time
from typing import Dict, List


def test_endpoint(name: str, url: str) -> Dict[str, str]:
    """Test a single MCP endpoint and return status."""
    try:
        response = requests.get(f"{url}/health", timeout=5)
        if response.status_code == 200:
            return {"name": name, "status": "✅ HEALTHY", "url": url}
        else:
            return {"name": name, "status": f"❌ HTTP {response.status_code}", "url": url}
    except requests.exceptions.ConnectionError:
        return {"name": name, "status": "🔴 UNAVAILABLE", "url": url}
    except requests.exceptions.Timeout:
        return {"name": name, "status": "⏱️ TIMEOUT", "url": url}
    except Exception as e:
        return {"name": name, "status": f"❌ ERROR: {str(e)[:50]}", "url": url}


def test_main_app() -> Dict[str, str]:
    """Test the main Flask application endpoints."""
    endpoints = [
        ("System Stats", "http://localhost:8100/api/system-stats"),
        ("Containers", "http://localhost:8100/api/containers"),
        ("Ops-Copilot Chat", "http://localhost:8100/api/ops-copilot/chat"),
        ("Frontend", "http://localhost:8100/"),
    ]

    results = []
    for name, url in endpoints:
        try:
            if "chat" in url:
                # Test POST endpoint
                response = requests.post(url, json={"message": "test"}, timeout=5)
            else:
                response = requests.get(url, timeout=5)

            if response.status_code == 200:
                results.append({"name": name, "status": "✅ HEALTHY", "url": url})
            else:
                results.append({"name": name, "status": f"❌ HTTP {response.status_code}", "url": url})
        except Exception as e:
            results.append({"name": name, "status": f"❌ ERROR: {str(e)[:50]}", "url": url})

    return results


def main():
    """Run all MCP and application tests."""
    print("🔍 Testing Pi-Health AI Assistant Application")
    print("=" * 50)

    # Test main application
    print("\n📱 Main Application Endpoints:")
    app_results = test_main_app()
    for result in app_results:
        print(f"  {result['status']} {result['name']}")

    # Test MCP services (from .env configuration)
    print("\n🔧 MCP Service Endpoints:")
    mcp_services = [
        ("Docker MCP", "http://localhost:8001"),
        ("Sonarr MCP", "http://localhost:8002"),
        ("Radarr MCP", "http://localhost:8003"),
        ("Lidarr MCP", "http://localhost:8004"),
        ("SABnzbd MCP", "http://localhost:8005"),
        ("Jellyfin MCP", "http://localhost:8006"),
        ("Jellyseerr MCP", "http://localhost:8007"),
    ]

    mcp_results = []
    for name, url in mcp_services:
        result = test_endpoint(name, url)
        mcp_results.append(result)
        print(f"  {result['status']} {result['name']}")

    # Summary
    print("\n📊 Test Summary:")
    healthy_app = sum(1 for r in app_results if "✅" in r["status"])
    total_app = len(app_results)
    healthy_mcp = sum(1 for r in mcp_results if "✅" in r["status"])
    total_mcp = len(mcp_results)

    print(f"  Main Application: {healthy_app}/{total_app} endpoints healthy")
    print(f"  MCP Services: {healthy_mcp}/{total_mcp} services healthy")

    if healthy_app == total_app and healthy_mcp > 0:
        print("\n🎉 Application is ready for production!")
    elif healthy_app == total_app:
        print("\n✅ Main application is working (MCP services optional)")
    else:
        print("\n⚠️ Some core services need attention")
        print("\nTo start MCP services, run individual service main.py files:")
        for result in mcp_results:
            if "🔴" in result["status"]:
                service_name = result["name"].replace(" MCP", "").lower()
                print(f"  python mcp/{service_name}/main.py")


if __name__ == "__main__":
    main()