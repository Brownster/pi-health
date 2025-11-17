from flask import Flask, jsonify, send_from_directory, request
import psutil
import os
import docker
import subprocess
from urllib import request as urlrequest
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


def parse_port_key(port_key):
    """Split Docker's port key (e.g. '8080/tcp') into structured parts."""
    if not port_key:
        return None, None
    if isinstance(port_key, int):
        return port_key, 'tcp'

    try:
        port_str, protocol = port_key.split('/')
    except ValueError:
        port_str, protocol = port_key, 'tcp'

    try:
        port_num = int(port_str)
    except ValueError:
        port_num = None

    return port_num, protocol


def get_container_ports(container):
    """Return a structured list of ports exposed/published by a container."""
    ports = []
    seen_ports = set()

    try:
        network_settings = container.attrs.get('NetworkSettings', {})
        port_bindings = network_settings.get('Ports') or {}
        config = container.attrs.get('Config', {})
        exposed_ports = config.get('ExposedPorts') or {}
    except Exception as e:
        print(f"Error inspecting ports for container {container.name}: {e}")
        return ports

    # Ports published to the host
    for container_port, bindings in port_bindings.items():
        port_num, protocol = parse_port_key(container_port)
        seen_ports.add((port_num, protocol))

        if not bindings:
            ports.append(
                {
                    "container_port": port_num,
                    "protocol": protocol,
                    "host_port": None,
                    "host_ip": None,
                }
            )
            continue

        for binding in bindings:
            host_port = binding.get("HostPort")
            host_ip = binding.get("HostIp") or None
            ports.append(
                {
                    "container_port": port_num,
                    "protocol": protocol,
                    "host_port": int(host_port) if host_port else None,
                    "host_ip": host_ip if host_ip not in ("0.0.0.0", "") else None,
                }
            )

    # Any remaining exposed ports (useful for network_mode=host/service)
    for container_port in exposed_ports.keys():
        port_num, protocol = parse_port_key(container_port)
        if (port_num, protocol) in seen_ports:
            continue
        ports.append(
            {
                "container_port": port_num,
                "protocol": protocol,
                "host_port": None,
                "host_ip": None,
            }
        )

    return ports


def get_container_ports_cached(container, port_cache):
    """Return cached port metadata for a container to avoid repeated inspections."""
    if container.id not in port_cache:
        port_cache[container.id] = get_container_ports(container)
    return port_cache[container.id]


def inherit_ports_from_network_service(container, containers_by_name, port_cache):
    """If a container shares another container's network stack, inherit its host bindings."""
    host_config = container.attrs.get('HostConfig', {})
    network_mode = host_config.get('NetworkMode') or ''

    if not network_mode.startswith('service:'):
        return []

    service_name = network_mode.split(':', 1)[1]
    if not service_name:
        return []

    service_container = containers_by_name.get(service_name)
    if not service_container:
        try:
            service_container = docker_client.containers.get(service_name)
        except Exception:
            return []

    service_ports = get_container_ports_cached(service_container, port_cache)
    if not service_ports:
        return []

    exposed_ports = container.attrs.get('Config', {}).get('ExposedPorts') or {}
    if not exposed_ports:
        return []

    # Group the service's host bindings by (container_port, protocol)
    service_port_map = {}
    for port in service_ports:
        key = (port.get('container_port'), port.get('protocol'))
        service_port_map.setdefault(key, []).append(port)

    inherited_ports = []
    for exposed_port in exposed_ports.keys():
        port_num, protocol = parse_port_key(exposed_port)
        if port_num is None:
            continue

        matches = service_port_map.get((port_num, protocol))
        if not matches and protocol != 'tcp':
            matches = service_port_map.get((port_num, 'tcp'))
        if not matches:
            matches = service_port_map.get((port_num, None))

        if matches:
            for match in matches:
                inherited_ports.append(
                    {
                        "container_port": port_num,
                        "protocol": protocol or match.get('protocol') or 'tcp',
                        "host_port": match.get('host_port'),
                        "host_ip": match.get('host_ip'),
                        "via_service": service_name,
                    }
                )
        else:
            # No host binding available on the service container, but expose the port metadata
            inherited_ports.append(
                {
                    "container_port": port_num,
                    "protocol": protocol or 'tcp',
                    "host_port": None,
                    "host_ip": None,
                    "via_service": service_name,
                }
            )

    return inherited_ports


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
                "ports": [],
            }
        ]
    
    try:
        containers = docker_client.containers.list(all=True)
        containers_by_name = {container.name: container for container in containers}
        port_cache = {}
        container_list = []
        for container in containers:
            try:
                ports = [dict(port) for port in get_container_ports_cached(container, port_cache)]
                if not ports:
                    inherited = inherit_ports_from_network_service(container, containers_by_name, port_cache)
                    if inherited:
                        ports = inherited
            except Exception:
                ports = []

            container_list.append(
                {
                    "id": container.id[:12],
                    "name": container.name,
                    "status": container.status,
                    "image": container.image.tags[0] if container.image.tags else "unknown",
                    "update_available": container_updates.get(container.id[:12], False),
                    "ports": ports,
                }
            )

        return container_list
    except Exception as e:
        print(f"Error listing containers: {e}")
        return [
            {
                "id": "error-listing",
                "name": "Error Listing Containers",
                "status": "error",
                "image": str(e)[:30] + "..." if len(str(e)) > 30 else str(e),
                "ports": [],
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


def get_container_logs(container_id, tail=200):
    """Return the recent logs for a container."""
    if not docker_available:
        return {"error": "Docker is not available"}

    try:
        container = docker_client.containers.get(container_id)
        logs = container.logs(tail=tail)
        if isinstance(logs, bytes):
            logs = logs.decode("utf-8", errors="replace")
        return {"logs": logs, "container": container.name}
    except Exception as e:
        return {"error": str(e)}


def run_network_test():
    """Ping 8.8.8.8 and report local/public IP details."""
    ping_output = ""
    ping_success = False

    try:
        ping_result = subprocess.run(
            ["ping", "-c", "4", "8.8.8.8"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        ping_output = ping_result.stdout or ping_result.stderr or ""
        ping_success = ping_result.returncode == 0
    except FileNotFoundError:
        ping_output = "Ping command not available in this container."
    except subprocess.TimeoutExpired as exc:
        ping_output = exc.stdout or exc.stderr or "Ping timed out."
    except Exception as exc:
        ping_output = str(exc)

    local_ip = None
    try:
        hostname_result = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=5
        )
        local_ip = hostname_result.stdout.strip() or hostname_result.stderr.strip()
    except Exception:
        local_ip = None

    public_ip = None
    try:
        with urlrequest.urlopen("https://api.ipify.org", timeout=10) as response:
            public_ip = response.read().decode("utf-8").strip()
    except Exception:
        public_ip = None

    return {
        "ping_success": ping_success,
        "ping_output": ping_output,
        "local_ip": local_ip,
        "public_ip": public_ip,
    }

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


@app.route('/api/containers/<container_id>/logs', methods=['GET'])
def api_container_logs(container_id):
    """API endpoint to fetch container logs."""
    tail = request.args.get('tail', default=200, type=int)
    return jsonify(get_container_logs(container_id, tail=tail))


@app.route('/api/shutdown', methods=['POST'])
def api_shutdown():
    """API endpoint to shutdown the system."""
    return jsonify(system_action("shutdown"))


@app.route('/api/reboot', methods=['POST'])
def api_reboot():
    """API endpoint to reboot the system."""
    return jsonify(system_action("reboot"))


@app.route('/api/network-test', methods=['POST'])
def api_network_test():
    """API endpoint to run a network connectivity test."""
    return jsonify(run_network_test())

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080)
