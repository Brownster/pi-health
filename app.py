from flask import Flask, jsonify, send_from_directory, request
import psutil
import os
import docker

# Initialize Flask and Docker client
app = Flask(__name__, static_folder='static')
docker_client = docker.from_env()


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
        "temperature_celsius": temperature,
        "network_usage": network_usage,
    }


def list_containers():
    """List all Docker containers with their status."""
    containers = docker_client.containers.list(all=True)
    return [
        {
            "id": container.id[:12],
            "name": container.name,
            "status": container.status,
            "image": container.image.tags[0] if container.image.tags else "unknown",
        }
        for container in containers
    ]


def control_container(container_id, action):
    """Start, stop, or restart a container by ID."""
    try:
        container = docker_client.containers.get(container_id)
        if action == "start":
            container.start()
        elif action == "stop":
            container.stop()
        elif action == "restart":
            container.restart()
        else:
            return {"error": "Invalid action"}
        return {"status": f"Container {action}ed successfully"}
    except Exception as e:
        return {"error": str(e)}


@app.route('/')
def serve_frontend():
    """Serve the frontend HTML file."""
    return send_from_directory(app.static_folder, 'index.html')


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


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080)
