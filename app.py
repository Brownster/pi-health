from flask import Flask, jsonify, send_from_directory, request
import psutil
import os
import docker
from uuid import uuid4
from compose_editor import compose_editor

# Initialize Flask
app = Flask(__name__, static_folder='static')

# Initialize Docker client with graceful fallback
try:
    docker_client = docker.from_env()
    docker_available = True
except Exception as e:
    print(f"Warning: Could not connect to Docker: {e}")
    print("Docker functionality will be disabled")
    docker_client = None
    docker_available = False

# Register the compose editor blueprint
app.register_blueprint(compose_editor)

# Track update status for containers
container_updates = {}


def calculate_cpu_usage(cpu_line):
    """Calculate CPU usage based on /proc/stat values."""
    user, nice, system, idle, iowait, irq, softirq, steal = map(int, cpu_line[1:9])
    total_time = user + nice + system + idle + iowait + irq + softirq + steal
    idle_time = idle + iowait
    usage_percent = 100 * (total_time - idle_time) / total_time
    return usage_percent


def get_system_stats():
    """Gather system statistics including CPU, memory, disk, and network."""
    # CPU usage
    try:
        with open('/host_proc/stat', 'r') as f:
            cpu_line = f.readline().split()
            cpu_usage = calculate_cpu_usage(cpu_line)
    except Exception:
        cpu_usage = None

    # Memory usage
    memory = psutil.virtual_memory()
    memory_usage = {
        "total": memory.total,
        "used": memory.used,
        "free": memory.available,
        "percent": memory.percent,
    }

    # Disk usage (with configurable path)
    disk_path = os.getenv('DISK_PATH', '/')
    try:
        disk = psutil.disk_usage(disk_path)
        disk_usage = {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
        }
    except Exception:
        disk_usage = None

    # Second Disk Usage
    disk_path_2 = os.getenv('DISK_PATH_2', '/mnt/backup')
    try:
        disk_2 = psutil.disk_usage(disk_path_2)
        disk_usage_2 = {
            "total": disk_2.total,
            "used": disk_2.used,
            "free": disk_2.free,
            "percent": disk_2.percent,
        }
    except Exception:
        disk_usage_2 = None
    
    # Temperature (specific to Raspberry Pi)
    if os.path.exists('/usr/bin/vcgencmd'):
        try:
            temp_output = os.popen("vcgencmd measure_temp").readline()
            temperature = float(temp_output.replace("temp=", "").replace("'C\n", ""))
        except Exception:
            temperature = None
    else:
        temperature = None

    # Network I/O
    net_io = psutil.net_io_counters()
    network_usage = {
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
    }

    # Combine all stats
    return {
        "cpu_usage_percent": cpu_usage,
        "memory_usage": memory_usage,
        "disk_usage": disk_usage,
        "disk_usage_2": disk_usage_2,
        "temperature_celsius": temperature,
        "network_usage": network_usage,
    }


def list_containers():
    """List all Docker containers with their status."""
    if not docker_available:
        return [
            {
                "id": "docker-not-available",
                "name": "Docker Not Available",
                "status": "unavailable",
                "image": "N/A",
            }
        ]
    
    try:
        containers = docker_client.containers.list(all=True)
        return [
            {
                "id": container.id[:12],
                "name": container.name,
                "status": container.status,
                "image": container.image.tags[0] if container.image.tags else "unknown",
                "update_available": container_updates.get(container.id[:12], False),
            }
            for container in containers
        ]
    except Exception as e:
        print(f"Error listing containers: {e}")
        return [
            {
                "id": "error-listing",
                "name": "Error Listing Containers",
                "status": "error",
                "image": str(e)[:30] + "..." if len(str(e)) > 30 else str(e),
            }
        ]


def check_container_update(container):
    """Check if an update is available for the container's image."""
    try:
        if not container.image.tags:
            return {"error": "Container image has no tag"}
        tag = container.image.tags[0]
        current_id = container.image.id
        pulled = docker_client.images.pull(tag)
        update = pulled.id != current_id
        container_updates[container.id[:12]] = update
        return {"update_available": update}
    except Exception as e:
        return {"error": str(e)}


def update_container(container):
    """Pull the latest image and recreate the service using docker compose."""
    try:
        if not container.image.tags:
            return {"error": "Container image has no tag"}
        tag = container.image.tags[0]
        docker_client.images.pull(tag)
        import subprocess
        subprocess.run(["docker", "compose", "up", "-d", container.name], check=False)
        container_updates[container.id[:12]] = False
        return {"status": "Container updated"}
    except Exception as e:
        return {"error": str(e)}

def control_container(container_id, action):
    """Start, stop, or restart a container by ID."""
    if not docker_available:
        return {"error": "Docker is not available"}
    
    try:
        container = docker_client.containers.get(container_id)
        if action == "start":
            container.start()
        elif action == "stop":
            container.stop()
        elif action == "restart":
            container.restart()
        elif action == "check_update":
            return check_container_update(container)
        elif action == "update":
            return update_container(container)
        else:
            return {"error": "Invalid action"}
        return {"status": f"Container {action}ed successfully"}
    except Exception as e:
        return {"error": str(e)}


def system_action(action):
    """Perform system actions like shutdown or reboot."""
    try:
        if action == "shutdown":
            # Use subprocess to run shutdown command
            import subprocess
            subprocess.Popen(['sudo', 'shutdown', '-h', 'now'])
            return {"status": "Shutdown initiated"}
        elif action == "reboot":
            # Use subprocess to run reboot command
            import subprocess
            subprocess.Popen(['sudo', 'reboot'])
            return {"status": "Reboot initiated"}
        else:
            return {"error": "Invalid system action"}
    except Exception as e:
        return {"error": str(e)}


def build_suggestion(action_id, description, command, impact, cta_label="Apply Fix"):
    """Create a structured suggestion payload for the Ops-Copilot UI."""
    return {
        "id": action_id,
        "description": description,
        "command": command,
        "impact": impact,
        "ctaLabel": cta_label,
    }


def assistant_message(content, suggestion=None):
    """Return a chat message formatted for the Ops-Copilot frontend."""
    message = {
        "id": f"assistant-{uuid4().hex}",
        "role": "assistant",
        "content": content,
    }
    if suggestion:
        message["suggestion"] = suggestion
    return message


def generate_mock_chat_response(message_text):
    """Generate a mocked AI response for the Ops-Copilot chat endpoint."""
    lower = message_text.lower()

    if any(keyword in lower for keyword in ["wrong", "problem", "issue", "stalled", "stuck"]):
        suggestion = build_suggestion(
            action_id="restart_sonarr",
            description="Restart the Sonarr container to clear the stalled download queue.",
            command="docker restart sonarr",
            impact="Expected downtime: ~30 seconds. Action will be logged for audit.",
            cta_label="Apply Fix",
        )
        content = (
            "<p class='font-semibold text-blue-100'>🔍 System analysis complete</p>"
            "<p class='mt-2 text-blue-100/80'>Sonarr's download queue has been idle for 3 hours and is reporting stalled items.</p>"
            "<ul class='mt-3 list-disc space-y-1 pl-5 text-blue-100/80'>"
            "<li>Queue depth: 4 releases waiting</li>"
            "<li>Last successful import: 3h 12m ago</li>"
            "<li>No network errors detected, container uptime 3d</li>"
            "</ul>"
            "<p class='mt-4 text-blue-100/80'>I recommend restarting the Sonarr container to clear the queue state.</p>"
        )
        return [assistant_message(content, suggestion)]

    if "health" in lower or "system" in lower:
        content = (
            "<p class='font-semibold text-blue-100'>🩺 System health snapshot</p>"
            "<ul class='mt-3 list-disc space-y-1 pl-5 text-blue-100/80'>"
            "<li>CPU load averaging 41% over the last minute</li>"
            "<li>Memory usage holding at 62% (no swap pressure)</li>"
            "<li>Disks healthy with 46% free on media volume</li>"
            "<li>No recent critical events in syslog</li>"
            "</ul>"
            "<p class='mt-4 text-blue-100/70'>Let me know if you want to drill into any specific service.</p>"
        )
        return [assistant_message(content)]

    if "radarr" in lower:
        content = (
            "<p class='font-semibold text-blue-100'>🎬 Radarr status</p>"
            "<ul class='mt-3 list-disc space-y-1 pl-5 text-blue-100/80'>"
            "<li>Service is up with normal response times</li>"
            "<li>Download queue: 3 active, 1 completed in the last hour</li>"
            "<li>Free disk space on media volume: 847 GB</li>"
            "<li>Last indexer sync completed 4 minutes ago</li>"
            "</ul>"
            "<p class='mt-4 text-emerald-300/80'>Everything looks healthy for Radarr.</p>"
        )
        return [assistant_message(content)]

    if "disk" in lower or "space" in lower:
        content = (
            "<p class='font-semibold text-blue-100'>💾 Disk utilisation</p>"
            "<ul class='mt-3 list-disc space-y-1 pl-5 text-blue-100/80'>"
            "<li>Media array: 2.1 TB used of 4 TB (47% free)</li>"
            "<li>System drive: 28 GB used of 64 GB (56% free)</li>"
            "<li>Download cache: 156 GB used of 200 GB (22% headroom)</li>"
            "</ul>"
            "<p class='mt-4 text-blue-100/70'>Consider purging the download cache when convenient to reclaim space.</p>"
        )
        return [assistant_message(content)]

    if "log" in lower:
        content = (
            "<p class='font-semibold text-blue-100'>🗒️ Recent log highlights</p>"
            "<ul class='mt-3 list-disc space-y-1 pl-5 text-blue-100/80'>"
            "<li>Radarr: No warnings in the past 60 minutes</li>"
            "<li>Sonarr: Queue stalled warning recorded at 14:32</li>"
            "<li>Jellyfin: Transcoding job completed successfully</li>"
            "</ul>"
            "<p class='mt-4 text-blue-100/70'>No critical alerts detected. The Sonarr stall matches the queue issue we can remediate.</p>"
        )
        return [assistant_message(content)]

    if "queue" in lower:
        content = (
            "<p class='font-semibold text-blue-100'>📥 Download queue status</p>"
            "<ul class='mt-3 list-disc space-y-1 pl-5 text-blue-100/80'>"
            "<li>Sonarr: 4 episodes queued, none importing</li>"
            "<li>Radarr: 2 films downloading, ETA 18 minutes</li>"
            "<li>SABnzbd: Bandwidth steady at 38 MB/s</li>"
            "</ul>"
            "<p class='mt-4 text-blue-100/70'>The stalled Sonarr queue can be cleared with a container restart if you approve.</p>"
        )
        suggestion = build_suggestion(
            action_id="restart_sonarr",
            description="Restart the Sonarr container to resume queue processing.",
            command="docker restart sonarr",
            impact="Service interruption ~30 seconds. Audit trail entry will be created.",
            cta_label="Apply Fix",
        )
        return [assistant_message(content, suggestion)]

    content = (
        "<p class='font-semibold text-blue-100'>🤖 Ops-Copilot capabilities</p>"
        "<ul class='mt-3 list-disc space-y-1 pl-5 text-blue-100/80'>"
        "<li>Check service health and container status</li>"
        "<li>Summarise logs and resource usage</li>"
        "<li>Propose safe automated fixes for common issues</li>"
        "<li>Request approvals before executing changes</li>"
        "</ul>"
        "<p class='mt-4 text-blue-100/70'>Ask me about a specific service or say “What\'s wrong?” to start a diagnostic.</p>"
    )
    return [assistant_message(content)]

@app.route('/')
def serve_frontend():
    """Serve the main landing page."""
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/system.html')
def serve_system():
    """Serve the system health page."""
    return send_from_directory(app.static_folder, 'system.html')


@app.route('/containers.html')
def serve_containers():
    """Serve the containers management page."""
    return send_from_directory(app.static_folder, 'containers.html')


@app.route('/ops-copilot.html')
def serve_ops_copilot():
    """Serve the Ops-Copilot AI assistant page."""
    return send_from_directory(app.static_folder, 'ops-copilot.html')


@app.route('/edit.html')
def serve_edit():
    """Serve the edit configuration page."""
    return send_from_directory(app.static_folder, 'edit.html')


@app.route('/login.html')
def serve_login():
    """Serve the login page."""
    return send_from_directory(app.static_folder, 'login.html')


@app.route('/coraline-banner.jpg')
def serve_banner():
    """Serve the Coraline banner image."""
    return send_from_directory(app.static_folder, 'coraline-banner.jpg')


@app.route('/api/system-stats', methods=['GET'])
def api_system_stats():
    """Alias endpoint for system stats used by the Ops-Copilot UI."""
    return jsonify(get_system_stats())


@app.route('/api/stats', methods=['GET'])
def api_stats():
    """API endpoint to return system stats as JSON."""
    return jsonify(get_system_stats())


@app.route('/api/containers', methods=['GET'])
def api_list_containers():
    """API endpoint to list all Docker containers."""
    return jsonify(list_containers())


@app.route('/api/ops-copilot/chat', methods=['POST'])
def api_ops_copilot_chat():
    """Mocked chat endpoint powering the Ops-Copilot UI."""
    payload = request.get_json(silent=True) or {}
    message = (payload.get('message') or '').strip()

    if not message:
        return jsonify({
            "messages": [
                assistant_message(
                    "<p class='text-blue-100/80'>Share a question or request so I can help troubleshoot.</p>"
                )
            ]
        })

    try:
        messages = generate_mock_chat_response(message)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Ops-Copilot mock response error: {exc}")
        messages = [
            assistant_message(
                "<p class='text-rose-200'>I ran into an error while processing that. Please try again.</p>"
            )
        ]

    return jsonify({"messages": messages})


@app.route('/api/ops-copilot/approve', methods=['POST'])
def api_ops_copilot_approve():
    """Mock approval endpoint to confirm automation steps."""
    payload = request.get_json(silent=True) or {}
    action_id = payload.get('action_id')

    if not action_id:
        return jsonify({"error": "action_id is required"}), 400

    if action_id == "restart_sonarr":
        followup = (
            "<p class='font-semibold text-blue-100'>🔧 Automation complete</p>"
            "<p class='mt-2 text-blue-100/80'>The Sonarr container restarted successfully and the queue resumed processing.</p>"
            "<ul class='mt-3 list-disc space-y-1 pl-5 text-blue-100/80'>"
            "<li>Restart duration: 18 seconds</li>"
            "<li>Queue throughput restored (4 items pending)</li>"
            "<li>Action logged to the audit trail</li>"
            "</ul>"
        )
        return jsonify({
            "status": "success",
            "result": "Sonarr container restart simulated successfully.",
            "followup": followup,
        })

    return jsonify({
        "status": "error",
        "error": "Unknown automation request."
    }), 400


@app.route('/api/containers/<container_id>/<action>', methods=['POST'])
def api_control_container(container_id, action):
    """API endpoint to control a Docker container."""
    return jsonify(control_container(container_id, action))


@app.route('/api/shutdown', methods=['POST'])
def api_shutdown():
    """API endpoint to shutdown the system."""
    return jsonify(system_action("shutdown"))


@app.route('/api/reboot', methods=['POST'])
def api_reboot():
    """API endpoint to reboot the system."""
    return jsonify(system_action("reboot"))

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080)
