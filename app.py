from flask import Flask, jsonify, send_from_directory, request
import psutil
import os
import docker
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
    disk = psutil.disk_usage(disk_path)
    disk_usage = {
        "total": disk.total,
        "used": disk.used,
        "free": disk.free,
        "percent": disk.percent,
    }

    # Second Disk Usage
    disk_path_2 = os.getenv('DISK_PATH_2', '/mnt/backup')
    disk_2 = psutil.disk_usage(disk_path_2)
    disk_usage_2 = {
        "total": disk_2.total,
        "used": disk_2.used,
        "free": disk_2.free,
        "percent": disk_2.percent,
    }
    
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


@app.route('/api/stats', methods=['GET'])
def api_stats():
    """API endpoint to return system stats as JSON."""
    return jsonify(get_system_stats())


@app.route('/api/containers', methods=['GET'])
def api_list_containers():
    """API endpoint to list all Docker containers."""
    return jsonify(list_containers())


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
