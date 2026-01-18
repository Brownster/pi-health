from flask import Flask, jsonify, send_from_directory, request, session
import psutil
import os
import docker
import subprocess
import socket
import json
import secrets
import hashlib
from urllib import request as urlrequest
from stack_manager import stack_manager
from auth_utils import login_required
from catalog_manager import catalog_manager
from storage_plugins import storage_bp
from storage_plugins.registry import init_plugins
from pi_monitor import get_pi_metrics
from update_scheduler import update_scheduler, init_scheduler
from backup_scheduler import backup_scheduler, init_backup_scheduler
from disk_manager import disk_manager
from setup_manager import setup_manager

# Initialize Flask
app = Flask(__name__, static_folder='static')

# Storage plugin configuration directory
STORAGE_PLUGIN_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "config",
    "storage_plugins"
)

# Configure session
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(32))

# Authentication configuration - supports multiple users via environment variables
# Format: PIHEALTH_USERS=user1:password1,user2:password2
def load_users():
    """Load users from environment variable or use default."""
    users_env = os.getenv('PIHEALTH_USERS', '')
    users = {}
    if users_env:
        for user_pass in users_env.split(','):
            if ':' in user_pass:
                username, password = user_pass.split(':', 1)
                users[username.strip()] = password.strip()
    # Fallback to legacy single user config or default
    if not users:
        default_user = os.getenv('PIHEALTH_USER', 'admin')
        default_pass = os.getenv('PIHEALTH_PASSWORD', 'pihealth')
        users[default_user] = default_pass
    return users

AUTH_USERS = load_users()
print(f"Loaded {len(AUTH_USERS)} user(s) for authentication")


def verify_credentials(username, password):
    """Verify username and password against configured users."""
    if username in AUTH_USERS:
        return AUTH_USERS[username] == password
    return False

# Load theme configuration
THEME_NAME = os.getenv('THEME', 'professional')
THEME_PATH = os.path.join('themes', THEME_NAME)
THEME_CONFIG_PATH = os.path.join(THEME_PATH, 'theme.json')

def load_theme_config():
    """Load the theme configuration from JSON file."""
    try:
        with open(THEME_CONFIG_PATH, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: Theme '{THEME_NAME}' not found at {THEME_CONFIG_PATH}")
        print("Falling back to default 'professional' theme")
        fallback_path = os.path.join('themes', 'professional', 'theme.json')
        with open(fallback_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading theme config: {e}")
        # Return minimal default theme
        return {
            "name": "default",
            "display_name": "Default",
            "title": "Pi-Health Dashboard",
            "colors": {
                "primary": "#5f4b8b",
                "background": "#111827"
            }
        }

theme_config = load_theme_config()
print(f"Loaded theme: {theme_config.get('display_name', 'Unknown')} ({THEME_NAME})")

# Initialize Docker client with graceful fallback
try:
    docker_client = docker.from_env()
    docker_available = True
except Exception as e:
    print(f"Warning: Could not connect to Docker: {e}")
    print("Docker functionality will be disabled")
    docker_client = None
    docker_available = False

app.register_blueprint(stack_manager)
app.register_blueprint(catalog_manager)
app.register_blueprint(storage_bp)
app.register_blueprint(update_scheduler)
app.register_blueprint(backup_scheduler)
app.register_blueprint(disk_manager)
app.register_blueprint(setup_manager)

# Initialize storage plugins
init_plugins(STORAGE_PLUGIN_CONFIG_DIR)

# Initialize the auto-update scheduler
init_scheduler(app)
# Initialize the backup scheduler
init_backup_scheduler(app)

# Track update status for containers
container_updates = {}

# Container stats cache with TTL
import time
_container_stats_cache = {}
_container_stats_timestamps = {}
CONTAINER_STATS_TTL = 5  # seconds


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


def get_cpu_usage_per_core(stat_lines):
    """Calculate per-core usage percentages from /proc/stat lines."""
    per_core = []
    for line in stat_lines:
        if not line.startswith('cpu') or line.startswith('cpu '):
            continue
        parts = line.split()
        if len(parts) < 9:
            continue
        core_id = parts[0]
        usage = calculate_cpu_usage(parts)
        per_core.append({'core': core_id, 'usage_percent': usage})
    return per_core


def get_temperature_fallback():
    """Try to get temperature using psutil sensors when vcgencmd is unavailable."""
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False)
    except Exception:
        return None

    if not temps:
        return None

    for entries in temps.values():
        for entry in entries:
            current = getattr(entry, 'current', None)
            if current is not None:
                return current
    return None


def get_system_stats():
    """Gather system statistics including CPU, memory, disk, and network."""
    # CPU usage
    try:
        with open('/host_proc/stat', 'r') as f:
            stat_lines = f.readlines()
            cpu_line = stat_lines[0].split() if stat_lines else []
            cpu_usage = calculate_cpu_usage(cpu_line) if cpu_line else None
            per_core = get_cpu_usage_per_core(stat_lines)
    except Exception:
        cpu_usage = None
        per_core = []

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

    if temperature is None:
        temperature = get_temperature_fallback()

    # Network I/O
    net_io = psutil.net_io_counters()
    network_usage = {
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
    }

    # Get Pi-specific metrics
    pi_metrics = get_pi_metrics()

    # Combine all stats
    return {
        "cpu_usage_percent": cpu_usage,
        "cpu_usage_per_core": per_core,
        "memory_usage": memory_usage,
        "disk_usage": disk_usage,
        "disk_usage_2": disk_usage_2,
        "temperature_celsius": temperature,
        "network_usage": network_usage,
        "throttling": pi_metrics.get('throttling'),
        "cpu_freq_mhz": pi_metrics.get('cpu_freq_mhz'),
        "cpu_voltage": pi_metrics.get('cpu_voltage'),
        "wifi_signal": pi_metrics.get('wifi_signal'),
        "is_raspberry_pi": pi_metrics.get('is_raspberry_pi', False),
    }


def calculate_container_cpu_percent(stats):
    """Calculate CPU percentage from Docker stats."""
    try:
        cpu_stats = stats.get('cpu_stats', {})
        precpu_stats = stats.get('precpu_stats', {})

        cpu_usage = cpu_stats.get('cpu_usage', {})
        precpu_usage = precpu_stats.get('cpu_usage', {})

        cpu_delta = cpu_usage.get('total_usage', 0) - precpu_usage.get('total_usage', 0)
        system_delta = cpu_stats.get('system_cpu_usage', 0) - precpu_stats.get('system_cpu_usage', 0)

        if system_delta > 0 and cpu_delta > 0:
            num_cpus = cpu_stats.get('online_cpus', 1) or len(cpu_usage.get('percpu_usage', [1]))
            cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0
            return round(cpu_percent, 1)
    except Exception:
        pass
    return None


def calculate_container_memory_stats(stats):
    """Extract memory usage stats from Docker stats."""
    try:
        memory_stats = stats.get('memory_stats', {})
        usage = memory_stats.get('usage', 0)
        limit = memory_stats.get('limit', 0)

        # Subtract cache for more accurate "real" memory usage
        cache = memory_stats.get('stats', {}).get('cache', 0)
        actual_usage = usage - cache if cache else usage

        if limit > 0:
            percent = round((actual_usage / limit) * 100, 1)
        else:
            percent = None

        return {
            'used': actual_usage,
            'limit': limit,
            'percent': percent
        }
    except Exception:
        return {'used': None, 'limit': None, 'percent': None}


def calculate_container_network_stats(stats):
    """Sum network rx/tx bytes across all interfaces."""
    try:
        networks = stats.get('networks', {})
        rx_bytes = 0
        tx_bytes = 0
        for iface_stats in networks.values():
            rx_bytes += iface_stats.get('rx_bytes', 0)
            tx_bytes += iface_stats.get('tx_bytes', 0)
        return {'rx': rx_bytes, 'tx': tx_bytes}
    except Exception:
        return {'rx': None, 'tx': None}


def get_container_stats_cached(container_id):
    """Fetch container stats with TTL caching."""
    now = time.time()

    # Check cache
    if container_id in _container_stats_cache:
        cached_time = _container_stats_timestamps.get(container_id, 0)
        if (now - cached_time) < CONTAINER_STATS_TTL:
            return _container_stats_cache[container_id]

    # Fetch fresh stats
    try:
        container = docker_client.containers.get(container_id)
        if container.status != 'running':
            return None

        stats = container.stats(stream=False)

        result = {
            'cpu_percent': calculate_container_cpu_percent(stats),
            'memory': calculate_container_memory_stats(stats),
            'network': calculate_container_network_stats(stats)
        }

        _container_stats_cache[container_id] = result
        _container_stats_timestamps[container_id] = now
        return result
    except Exception as e:
        print(f"Error fetching stats for {container_id}: {e}")
        return None


def list_containers(include_stats=True):
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

            # Fetch resource stats for running containers (if requested)
            stats = None
            if include_stats and container.status == 'running':
                stats = get_container_stats_cached(container.id)

            container_data = {
                "id": container.id[:12],
                "name": container.name,
                "status": container.status,
                "image": container.image.tags[0] if container.image.tags else "unknown",
                "update_available": container_updates.get(container.id[:12], False),
                "ports": ports,
                "cpu_percent": None,
                "memory_percent": None,
                "memory_used": None,
                "memory_limit": None,
                "net_rx": None,
                "net_tx": None,
            }

            if stats:
                container_data["cpu_percent"] = stats.get('cpu_percent')
                memory = stats.get('memory', {})
                container_data["memory_percent"] = memory.get('percent')
                container_data["memory_used"] = memory.get('used')
                container_data["memory_limit"] = memory.get('limit')
                network = stats.get('network', {})
                container_data["net_rx"] = network.get('rx')
                container_data["net_tx"] = network.get('tx')

            container_list.append(container_data)

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


def socket_probe(host="8.8.8.8", port=53, timeout=5):
    """Attempt a TCP socket connection as a fallback network check."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"Socket connection to {host}:{port} succeeded."
    except OSError as exc:
        return False, f"Socket connection to {host}:{port} failed: {exc}"


def run_network_test():
    """Ping 8.8.8.8 and report local/public IP details."""
    ping_output = ""
    ping_success = False
    probe_method = "ping"

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
        probe_method = "socket"
        socket_success, socket_message = socket_probe()
        ping_success = socket_success
        ping_output = (
            "Ping command not available in this container.\n" + socket_message
        )
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
        "probe_method": probe_method,
    }


def command_missing(exit_code, output):
    """Determine if a command failure was due to a missing binary."""
    output = (output or "").lower()
    return exit_code in (126, 127) or "not found" in output or "no such file" in output


def exec_in_container(container, script):
    """Execute a shell script inside a container and capture its output."""
    try:
        result = container.exec_run([
            "/bin/sh",
            "-c",
            script,
        ], stdout=True, stderr=True)
    except FileNotFoundError:
        # Some minimal containers might only have /bin/busybox
        result = container.exec_run([
            "sh",
            "-c",
            script,
        ], stdout=True, stderr=True)

    output = result.output
    if isinstance(output, tuple):
        stdout, stderr = output
        decoded = ""
        if stdout:
            decoded += stdout.decode("utf-8", errors="replace")
        if stderr:
            decoded += stderr.decode("utf-8", errors="replace")
        output_text = decoded
    elif isinstance(output, (bytes, bytearray)):
        output_text = output.decode("utf-8", errors="replace")
    else:
        output_text = str(output)

    return result.exit_code, output_text.strip()


def container_http_probe_script(tool_name):
    """Return a shell snippet that ensures a tool exists before running it."""
    commands = {
        "curl": "curl -s --max-time 10 https://api.ipify.org",
        "wget": "wget -qO- --timeout=10 https://api.ipify.org",
        "busybox": "busybox wget -qO- https://api.ipify.org",
    }
    if tool_name == "python3":
        python_script = (
            "python3 - <<'PY'\n"
            "import socket\n"
            "sock = socket.create_connection(('8.8.8.8', 53), timeout=5)\n"
            "print('Socket connection to 8.8.8.8:53 succeeded')\n"
            "sock.close()\n"
            "PY"
        )
        return (
            "if command -v python3 >/dev/null 2>&1; then\n"
            f"{python_script}\n"
            "else\n"
            "  exit 127\n"
            "fi"
        )

    tool_command = commands.get(tool_name, "")
    if not tool_command:
        return "exit 127"

    return (
        f"if command -v {tool_name} >/dev/null 2>&1; then\n"
        f"  {tool_command}\n"
        "else\n"
        "  exit 127\n"
        "fi"
    )


def run_container_fallback_probe(container):
    """Try alternative connectivity checks inside a container."""
    probes = [
        ("curl", True),
        ("wget", True),
        ("busybox", True),
        ("python3", False),
    ]

    for tool, provides_public_ip in probes:
        script = container_http_probe_script(tool)
        exit_code, output = exec_in_container(container, script)
        if exit_code == 0:
            message = f"{tool} connectivity test succeeded."
            if output:
                message += f"\n{output}"
            public_ip = output.strip() if provides_public_ip and output else None
            return True, message, tool, public_ip

        if command_missing(exit_code, output):
            continue

        message = output or f"{tool} connectivity test failed"
        return False, message, tool, None

    return (
        False,
        "No available networking tools (ping/curl/wget/python3) inside the container.",
        "unavailable",
        None,
    )


def get_container_local_ip(container):
    """Retrieve the container's local IP address if possible."""
    exit_code, output = exec_in_container(container, "hostname -I 2>/dev/null")
    if exit_code == 0 and output:
        return output.strip()
    return None


def get_container_public_ip(container):
    """Try to fetch the container's public IP using available tools."""
    script = (
        "if command -v curl >/dev/null 2>&1; then\n"
        "  curl -s --max-time 10 https://api.ipify.org\n"
        "elif command -v wget >/dev/null 2>&1; then\n"
        "  wget -qO- --timeout=10 https://api.ipify.org\n"
        "elif command -v busybox >/dev/null 2>&1; then\n"
        "  busybox wget -qO- https://api.ipify.org\n"
        "else\n"
        "  exit 127\n"
        "fi"
    )
    exit_code, output = exec_in_container(container, script)
    if exit_code == 0 and output:
        return output.strip()
    return None


def run_container_network_test(container_id):
    """Run a network diagnostic from inside a specific container."""
    try:
        container = docker_client.containers.get(container_id)
    except Exception as exc:
        return {"error": str(exc)}

    ping_success = False
    ping_output = ""
    probe_method = "ping"

    try:
        exit_code, output = exec_in_container(container, "ping -c 4 8.8.8.8")
        ping_output = output
        if exit_code == 0:
            ping_success = True
        elif command_missing(exit_code, output):
            probe_method = "fallback"
            (
                ping_success,
                fallback_message,
                fallback_tool,
                public_ip_from_fallback,
            ) = run_container_fallback_probe(container)
            ping_output = ((ping_output + "\n\n") if ping_output else "") + fallback_message
            if ping_success:
                probe_method = fallback_tool
            else:
                probe_method = f"{fallback_tool}-failed"
        else:
            ping_success = False
    except Exception as exc:
        ping_output = str(exc)

    local_ip = get_container_local_ip(container)
    public_ip = get_container_public_ip(container)

    # If fallback already determined public IP, prefer it
    if 'public_ip_from_fallback' in locals() and public_ip_from_fallback:
        public_ip = public_ip_from_fallback

    return {
        "container_id": container.id,
        "container_name": container.name,
        "ping_success": ping_success,
        "ping_output": ping_output,
        "local_ip": local_ip,
        "public_ip": public_ip,
        "probe_method": probe_method,
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
            subprocess.Popen(['sudo', 'shutdown', '-h', 'now'])
            return {"status": "Shutdown initiated"}
        elif action == "reboot":
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



@app.route('/apps.html')
def serve_apps():
    """Serve the app catalog page."""
    return send_from_directory(app.static_folder, 'apps.html')


@app.route('/stacks.html')
def serve_stacks():
    """Serve the stacks management page."""
    return send_from_directory(app.static_folder, 'stacks.html')


@app.route('/settings.html')
def serve_settings():
    """Serve the settings page."""
    return send_from_directory(app.static_folder, 'settings.html')

@app.route('/storage.html')
def serve_storage():
    """Serve the storage plugins page (redirects to pools)."""
    return send_from_directory(app.static_folder, 'storage.html')


@app.route('/pools.html')
def serve_pools():
    """Serve the storage pools page."""
    return send_from_directory(app.static_folder, 'pools.html')


@app.route('/mounts.html')
def serve_mounts():
    """Serve the mounts page."""
    return send_from_directory(app.static_folder, 'mounts.html')


@app.route('/shares.html')
def serve_shares():
    """Serve the network shares page."""
    return send_from_directory(app.static_folder, 'shares.html')


@app.route('/plugins.html')
def serve_plugins():
    """Serve the plugins page."""
    return send_from_directory(app.static_folder, 'plugins.html')


@app.route('/disks.html')
def serve_disks():
    """Serve the disk management page."""
    return send_from_directory(app.static_folder, 'disks.html')


@app.route('/login.html')
def serve_login():
    """Serve the login page."""
    return send_from_directory(app.static_folder, 'login.html')


@app.route('/api/login', methods=['POST'])
def api_login():
    """API endpoint for user authentication."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    username = data.get('username', '').strip()
    password = data.get('password', '')

    if verify_credentials(username, password):
        session['authenticated'] = True
        session['username'] = username
        return jsonify({'status': 'success', 'username': username})
    else:
        return jsonify({'error': 'Invalid credentials'}), 401


@app.route('/api/logout', methods=['POST'])
def api_logout():
    """API endpoint for user logout."""
    session.clear()
    return jsonify({'status': 'logged out'})


@app.route('/api/auth/check', methods=['GET'])
def api_auth_check():
    """API endpoint to check authentication status."""
    if session.get('authenticated'):
        return jsonify({
            'authenticated': True,
            'username': session.get('username', 'unknown')
        })
    return jsonify({'authenticated': False}), 401


@app.route('/coraline-banner.jpg')
def serve_banner():
    """Serve the Coraline banner image (legacy route for backwards compatibility)."""
    return send_from_directory(app.static_folder, 'coraline-banner.jpg')


@app.route('/api/theme', methods=['GET'])
def api_theme():
    """API endpoint to return current theme configuration."""
    return jsonify(theme_config)


@app.route('/theme-banner')
def serve_theme_banner():
    """Serve the current theme's banner image."""
    banner_filename = theme_config.get('banner', {}).get('filename', 'banner.jpg')
    return send_from_directory(THEME_PATH, banner_filename)


@app.route('/themes/<theme_name>/<filename>')
def serve_theme_file(theme_name, filename):
    """Serve theme-specific files (icons.js, etc.)."""
    theme_path = os.path.join('themes', theme_name)
    # Security: only allow specific file extensions
    allowed_extensions = ['.js', '.json', '.css']
    if any(filename.endswith(ext) for ext in allowed_extensions):
        return send_from_directory(theme_path, filename)
    else:
        return jsonify({"error": "File type not allowed"}), 403


@app.route('/js/<path:path>')
def serve_js(path):
    return send_from_directory(os.path.join(app.static_folder, 'js'), path)

@app.route('/css/<path:path>')
def serve_css(path):
    return send_from_directory(os.path.join(app.static_folder, 'css'), path)

@app.route('/favicon.svg')
def serve_favicon():
    return send_from_directory(app.static_folder, 'favicon.svg')

@app.route('/api/stats', methods=['GET'])
@login_required
def api_stats():
    """API endpoint to return system stats as JSON."""
    return jsonify(get_system_stats())


@app.route('/api/containers', methods=['GET'])
@login_required
def api_list_containers():
    """API endpoint to list all Docker containers."""
    include_stats = request.args.get('stats', 'true').lower() != 'false'
    return jsonify(list_containers(include_stats=include_stats))


@app.route('/api/containers/<container_id>/<action>', methods=['POST'])
@login_required
def api_control_container(container_id, action):
    """API endpoint to control a Docker container."""
    return jsonify(control_container(container_id, action))


@app.route('/api/containers/<container_id>/logs', methods=['GET'])
@login_required
def api_container_logs(container_id):
    """API endpoint to fetch container logs."""
    tail = request.args.get('tail', default=200, type=int)
    return jsonify(get_container_logs(container_id, tail=tail))


@app.route('/api/shutdown', methods=['POST'])
@login_required
def api_shutdown():
    """API endpoint to shutdown the system."""
    return jsonify(system_action("shutdown"))


@app.route('/api/reboot', methods=['POST'])
@login_required
def api_reboot():
    """API endpoint to reboot the system."""
    return jsonify(system_action("reboot"))


@app.route('/api/network-test', methods=['POST'])
@login_required
def api_network_test():
    """API endpoint to run a network connectivity test."""
    return jsonify(run_network_test())


@app.route('/api/containers/<container_id>/network-test', methods=['POST'])
@login_required
def api_container_network_test(container_id):
    """API endpoint to run a network test from inside a specific container."""
    if not docker_available:
        return jsonify({"error": "Docker is not available"}), 503
    return jsonify(run_container_network_test(container_id))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8002))
    app.run(host="0.0.0.0", port=port)
