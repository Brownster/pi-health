from flask import Flask, jsonify, redirect, send_from_directory, request, session
import psutil
import os
import docker
import subprocess
import socket
import json
import secrets
import hashlib
import getpass
from urllib import request as urlrequest
from stack_manager import stack_manager
from auth_utils import (
    LoginRateLimiter,
    get_csrf_token,
    load_users,
    login_required,
    rotate_csrf_token,
    verify_credentials as verify_password,
)
from catalog_manager import catalog_manager
from tools_manager import tools_manager
from storage_plugins import storage_bp
from storage_plugins.registry import init_plugins
from pi_monitor import get_pi_metrics
from update_scheduler import update_scheduler, init_scheduler
from backup_scheduler import backup_scheduler, init_backup_scheduler
from disk_manager import disk_manager
from setup_manager import setup_manager
from helper_client import helper_call, HelperError
from werkzeug.utils import safe_join

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

PIHEALTH_UPDATE_CONFIG = os.path.join(os.path.dirname(__file__), "config", "pihealth_update.json")
DEFAULT_PIHEALTH_UPDATE_CONFIG = {
    "repo_path": f"/home/{os.getenv('USER', 'pi')}/pi-health",
    "service_name": "pi-health"
}


def _load_pihealth_update_config():
    if os.path.exists(PIHEALTH_UPDATE_CONFIG):
        try:
            with open(PIHEALTH_UPDATE_CONFIG, "r") as handle:
                data = json.load(handle)
                return {**DEFAULT_PIHEALTH_UPDATE_CONFIG, **data}
        except Exception:
            return DEFAULT_PIHEALTH_UPDATE_CONFIG.copy()
    return DEFAULT_PIHEALTH_UPDATE_CONFIG.copy()


def _save_pihealth_update_config(config):
    os.makedirs(os.path.dirname(PIHEALTH_UPDATE_CONFIG), exist_ok=True)
    with open(PIHEALTH_UPDATE_CONFIG, "w") as handle:
        json.dump(config, handle, indent=2)

AUTH_USERS = load_users()
LOGIN_RATE_LIMITER = LoginRateLimiter()
print(f"Loaded {len(AUTH_USERS)} user(s) for authentication")


def verify_credentials(username, password):
    """Verify username and password against configured users."""
    return verify_password(AUTH_USERS, username, password)

# Load theme configuration
THEME_NAME = os.getenv('THEME', 'modern')
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

app.extensions['docker_client'] = docker_client

app.register_blueprint(stack_manager)
app.register_blueprint(catalog_manager)
app.register_blueprint(tools_manager)
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

    # Prefer the actual CPU package sensor; chipset/ambient sensors (e.g. acpitz)
    # read much lower and would misreport CPU temperature on x86 hosts.
    preferred = ('cpu_thermal', 'cpu-thermal', 'coretemp', 'k10temp',
                 'soc_thermal', 'cpu')
    for key in preferred:
        for entry in temps.get(key, []):
            current = getattr(entry, 'current', None)
            if current is not None:
                return current

    # Fall back to the first sensor that reports a reading.
    for entries in temps.values():
        for entry in entries:
            current = getattr(entry, 'current', None)
            if current is not None:
                return current
    return None


def _read_proc_stat_cpu(path):
    """Read aggregate + per-core CPU jiffy counters from a /proc/stat-style file.

    Returns {name: [user, nice, system, idle, iowait, irq, softirq, steal]}."""
    counters = {}
    with open(path, 'r') as f:
        for line in f:
            if line.startswith('cpu'):
                parts = line.split()
                try:
                    counters[parts[0]] = list(map(int, parts[1:9]))
                except (ValueError, IndexError):
                    continue
            elif counters:
                break  # cpu lines are first/contiguous in /proc/stat
    return counters


def _cpu_percent_from_delta(start, end):
    """Percent busy between two jiffy snapshots of one cpu line."""
    total = sum(end) - sum(start)
    idle = (end[3] + end[4]) - (start[3] + start[4])  # idle + iowait
    if total <= 0:
        return None
    return round(100 * (total - idle) / total, 1)


def get_cpu_usage_delta(interval=0.1):
    """Current CPU usage via two /proc/stat snapshots (delta), aggregate + per-core.

    Unlike a single snapshot (which yields the average since boot), this reflects
    actual instantaneous load. Tries /host_proc/stat (Docker) then /proc/stat."""
    for stat_path in ['/host_proc/stat', '/proc/stat']:
        try:
            start = _read_proc_stat_cpu(stat_path)
            if not start:
                continue
            time.sleep(interval)
            end = _read_proc_stat_cpu(stat_path)
            aggregate = None
            if 'cpu' in start and 'cpu' in end:
                aggregate = _cpu_percent_from_delta(start['cpu'], end['cpu'])
            per_core = [
                {'core': name, 'usage_percent': _cpu_percent_from_delta(start[name], end[name])}
                for name in sorted(start)
                if name != 'cpu' and name in end
            ]
            return aggregate, per_core
        except Exception:
            continue
    return None, []


def _safe_disk_usage(path):
    """psutil.disk_usage(path) as a dict, or None if the path isn't mounted."""
    try:
        usage = psutil.disk_usage(path)
    except Exception:
        return None
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": usage.percent,
    }


def _collect_disk_usage(metric, path, warnings):
    """Collect one disk metric and append a source-scoped warning on failure."""
    usage = _safe_disk_usage(path)
    if usage is None:
        warnings.append({
            'code': 'source_unavailable',
            'metric': metric,
            'source': path,
            'message': f'Disk usage unavailable for {path}',
        })
    return usage


def get_system_stats():
    """Gather system statistics including CPU, memory, disk, and network."""
    # CPU usage - instantaneous, via two /proc/stat snapshots (not since-boot avg)
    cpu_usage, per_core = get_cpu_usage_delta()

    # Memory usage
    memory = psutil.virtual_memory()
    memory_usage = {
        "total": memory.total,
        "used": memory.used,
        "free": memory.available,
        "percent": memory.percent,
    }

    # Disk usage (with configurable path); guarded so a missing mount returns
    # None instead of raising and 500-ing the whole stats endpoint.
    warnings = []
    disk_usage = _collect_disk_usage(
        'disk_usage',
        os.getenv('DISK_PATH', '/'),
        warnings,
    )
    disk_usage_2 = _collect_disk_usage(
        'disk_usage_2',
        os.getenv('DISK_PATH_2', '/mnt/backup'),
        warnings,
    )
    
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
        "warnings": warnings,
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
        net_topology, _net_groups = analyze_network_topology(containers)
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
                "health": get_container_health(container),
                "exit_code": (container.attrs.get('State') or {}).get('ExitCode')
                if container.status in ('exited', 'dead') else None,
                "network": net_topology.get(
                    container.id,
                    {"mode": "", "role": "standalone", "provider": None, "status": "ok"},
                ),
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

def get_container_health(container):
    """Return the container's healthcheck status, or None if it defines no healthcheck.

    Values: 'healthy', 'unhealthy', 'starting'."""
    try:
        health = (container.attrs.get('State') or {}).get('Health') or {}
    except Exception:
        return None
    return health.get('Status')


def get_container_health_detail(container):
    """Return health status plus the most recent healthcheck output.

    Surfacing the output is what distinguishes a genuinely failing service from a
    broken check (e.g. gluetun reporting 'unhealthy' only because `curl` is missing)."""
    state = container.attrs.get('State') or {}
    health = state.get('Health') or {}
    last_output = None
    log = health.get('Log') or []
    if log:
        out = (log[-1].get('Output') or '').strip()
        last_output = out[-500:] if out else None
    return {
        'status': health.get('Status'),
        'failing_streak': health.get('FailingStreak'),
        'last_output': last_output,
    }


def _network_target(host_config):
    """Describe a container's shared-network target.

    Returns ('container', <id>) when it joins another container's namespace,
    ('service', <name>) for the compose service form, or (None, None) for
    standalone/bridge/host networking."""
    mode = (host_config or {}).get('NetworkMode') or ''
    if mode.startswith('container:'):
        return 'container', mode.split(':', 1)[1]
    if mode.startswith('service:'):
        return 'service', mode.split(':', 1)[1]
    return None, None


def _compose_label(container, key):
    return ((container.attrs.get('Config') or {}).get('Labels') or {}).get(key)


def _compose_dependency_name(container):
    """Best-effort name of the service a container shares its network with, taken
    from the compose depends_on label. Used to name the provider when the live
    namespace target is already gone (the orphaned case)."""
    dep = _compose_label(container, 'com.docker.compose.depends_on') or ''
    first = dep.split(',')[0].strip()
    if first:
        name = first.split(':', 1)[0].strip()
        if name:
            return name
    return None


def analyze_network_topology(containers):
    """Map containers that ride on another container's network namespace
    (e.g. download clients behind a gluetun VPN) and flag *orphans* — members
    pinned to a namespace whose container no longer exists.

    Returns (info_by_id, groups_by_provider_name) where info entries carry
    {mode, role, provider, status, [members]} and groups carry member/orphan sets."""
    by_id = {c.id: c for c in containers}
    by_name = {c.name: c for c in containers}

    def _running(c):
        return getattr(c, 'status', None) == 'running'

    info = {}
    groups = {}

    for c in containers:
        host_config = c.attrs.get('HostConfig') or {}
        kind, value = _network_target(host_config)
        entry = {
            'mode': host_config.get('NetworkMode') or '',
            'role': 'standalone',
            'provider': None,
            'status': 'ok',
        }

        if kind in ('container', 'service'):
            entry['role'] = 'member'
            orphaned = False
            provider_name = None

            if kind == 'container':
                target = by_id.get(value)
                if target is None:
                    # Pinned to a namespace that no longer exists -> ORPHANED.
                    orphaned = True
                    provider_name = _compose_dependency_name(c)
                else:
                    provider_name = target.name
            else:  # service:<name>
                provider_name = value
                if by_name.get(value) is None:
                    orphaned = True

            entry['provider'] = provider_name
            if orphaned:
                entry['status'] = 'orphaned'
            else:
                tgt = by_name.get(provider_name) if provider_name else None
                entry['status'] = 'ok' if (tgt is not None and _running(tgt)) else 'provider_stopped'

            if provider_name:
                grp = groups.setdefault(provider_name, {'members': set(), 'orphaned': set()})
                grp['members'].add(c.name)
                if orphaned:
                    grp['orphaned'].add(c.name)

        info[c.id] = entry

    # Mark the provider containers themselves.
    for provider_name, grp in groups.items():
        provider = by_name.get(provider_name)
        if provider is not None:
            pinfo = info.get(provider.id)
            if pinfo is not None:
                pinfo['role'] = 'provider'
                pinfo['provider'] = provider_name
                pinfo['members'] = sorted(grp['members'])

    return info, groups


def get_host_public_ip():
    """Return the host's public IP, or None if it can't be determined."""
    try:
        with urlrequest.urlopen("https://api.ipify.org", timeout=10) as response:
            return response.read().decode("utf-8").strip()
    except Exception:
        return None


def list_network_groups(probe=False):
    """Return VPN-style network groups: a provider container plus the containers
    sharing its namespace, with health and orphan status. When probe=True, also
    compare the provider's public IP against the host's to detect a VPN leak."""
    if not docker_available:
        return {"docker_available": False, "groups": [], "orphans": []}

    try:
        containers = docker_client.containers.list(all=True)
    except Exception as exc:
        return {"docker_available": True, "error": str(exc), "groups": [], "orphans": []}

    info, groups = analyze_network_topology(containers)
    by_id = {c.id: c for c in containers}
    by_name = {c.name: c for c in containers}
    host_ip = get_host_public_ip() if probe else None

    group_list = []
    for provider_name, grp in groups.items():
        provider = by_name.get(provider_name)
        orphaned = sorted(grp['orphaned'])
        group = {
            'provider': provider_name,
            'provider_id': provider.id[:12] if provider else None,
            'provider_status': provider.status if provider else 'missing',
            'provider_health': get_container_health(provider) if provider else None,
            'members': sorted(grp['members']),
            'member_count': len(grp['members']),
            'orphaned_members': orphaned,
            'status': 'ok',
        }
        if orphaned or provider is None or provider.status != 'running':
            group['status'] = 'degraded'
        elif group['provider_health'] == 'unhealthy':
            group['status'] = 'provider_unhealthy'

        if probe and provider is not None and provider.status == 'running':
            provider_ip = get_container_public_ip(provider)
            group['provider_public_ip'] = provider_ip
            group['host_public_ip'] = host_ip
            group['vpn_leak'] = bool(provider_ip and host_ip and provider_ip == host_ip)

        group_list.append(group)

    orphans = [
        {
            'name': by_id[cid].name,
            'id': by_id[cid].id[:12],
            'status': by_id[cid].status,
            'provider': entry.get('provider'),
        }
        for cid, entry in info.items()
        if entry.get('status') == 'orphaned' and cid in by_id
    ]

    group_list.sort(key=lambda g: g['provider'] or '')
    orphans.sort(key=lambda o: o['name'])
    return {"docker_available": True, "groups": group_list, "orphans": orphans}


def recreate_network_group(provider_name):
    """Recreate a provider and every container sharing its namespace together,
    via `docker compose up -d`, so they all re-bind to the same live namespace.

    This is the one-click remedy for the orphaned-namespace failure: doing the
    services individually (or `docker start`) re-pins them to the dead namespace."""
    if not docker_available:
        return {"error": "Docker is not available"}

    try:
        provider = docker_client.containers.get(provider_name)
    except Exception as exc:
        return {"error": f"Provider container '{provider_name}' not found: {exc}"}

    config_files = _compose_label(provider, 'com.docker.compose.project.config_files')
    working_dir = _compose_label(provider, 'com.docker.compose.project.working_dir')
    if not config_files or not working_dir:
        return {"error": "Provider is not managed by docker compose; cannot safely recreate the group."}

    try:
        containers = docker_client.containers.list(all=True)
    except Exception as exc:
        return {"error": str(exc)}
    by_name = {c.name: c for c in containers}
    _, groups = analyze_network_topology(containers)
    member_names = sorted(groups.get(provider_name, {}).get('members', set()))

    # Resolve container names to compose service names (they can differ), provider first.
    ordered_services = []
    seen = set()
    for name in [provider_name] + member_names:
        container = by_name.get(name)
        service = _compose_label(container, 'com.docker.compose.service') if container else None
        service = service or name
        if service not in seen:
            seen.add(service)
            ordered_services.append(service)

    cmd = ["docker", "compose"]
    for path in config_files.split(','):
        path = path.strip()
        if path:
            cmd += ["-f", path]
    cmd += ["--project-directory", working_dir, "up", "-d"] + ordered_services

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception as exc:
        return {"error": str(exc)}

    ok = result.returncode == 0
    return {
        "status": "recreated" if ok else "error",
        "provider": provider_name,
        "services": ordered_services,
        "returncode": result.returncode,
        "stdout": (result.stdout or "")[-2000:],
        "stderr": (result.stderr or "")[-2000:],
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


UI_MODE_LEGACY = 'legacy'
UI_MODE_HYBRID = 'hybrid'
UI_MODE_V2 = 'v2'
VALID_UI_MODES = {UI_MODE_LEGACY, UI_MODE_HYBRID, UI_MODE_V2}
V2_PAGE_KEYS = {
    'index',
    'system',
    'containers',
    'apps',
    'stacks',
    'tools',
    'settings',
    'storage',
    'pools',
    'mounts',
    'shares',
    'plugins',
    'disks',
    'network',
    'tailscale',
}
V2_PAGE_ALIASES = {
    'home': 'index',
}


def normalize_ui_mode(mode_value):
    """Normalize UI mode env values to supported values with legacy fallback."""
    normalized = (mode_value or '').strip().lower()
    if normalized in VALID_UI_MODES:
        return normalized
    return UI_MODE_LEGACY


def get_ui_mode():
    """Read current UI mode from environment."""
    return normalize_ui_mode(os.getenv('PIHEALTH_UI_MODE', UI_MODE_LEGACY))


def parse_v2_pages(raw_pages):
    """Parse and normalize comma-separated v2 page keys."""
    if not raw_pages:
        return set()

    parsed_pages = set()
    for token in raw_pages.split(','):
        normalized = token.strip().lower()
        if not normalized:
            continue

        if normalized == '*':
            return set(V2_PAGE_KEYS)

        normalized = V2_PAGE_ALIASES.get(normalized, normalized)
        if normalized in V2_PAGE_KEYS:
            parsed_pages.add(normalized)

    return parsed_pages


def get_v2_enabled_pages():
    """Return selected v2 page keys for hybrid mode."""
    return parse_v2_pages(os.getenv('PIHEALTH_UI_V2_PAGES', ''))


def get_v2_target_for_page(page_key):
    """Map a legacy page key to its v2 route target."""
    if page_key == 'index':
        return '/v2'
    return f'/v2/{page_key}'


@app.route('/')
def serve_frontend():
    """Serve the main landing page."""
    return serve_ui_page('index', 'index.html')


@app.route('/system.html')
def serve_system():
    """Serve the system health page."""
    return serve_ui_page('system', 'system.html')


@app.route('/containers.html')
def serve_containers():
    """Serve the containers management page."""
    return serve_ui_page('containers', 'containers.html')



@app.route('/apps.html')
def serve_apps():
    """Serve the app catalog page."""
    return serve_ui_page('apps', 'apps.html')


@app.route('/stacks.html')
def serve_stacks():
    """Serve the stacks management page."""
    return serve_ui_page('stacks', 'stacks.html')


@app.route('/tools.html')
def serve_tools():
    """Serve the tools page."""
    return serve_ui_page('tools', 'tools.html')


@app.route('/settings.html')
def serve_settings():
    """Serve the settings page."""
    return serve_ui_page('settings', 'settings.html')

@app.route('/storage.html')
def serve_storage():
    """Serve the storage plugins page (redirects to pools)."""
    return serve_ui_page('storage', 'storage.html')


@app.route('/pools.html')
def serve_pools():
    """Serve the storage pools page."""
    return serve_ui_page('pools', 'pools.html')


@app.route('/mounts.html')
def serve_mounts():
    """Serve the mounts page."""
    return serve_ui_page('mounts', 'mounts.html')


@app.route('/shares.html')
def serve_shares():
    """Serve the network shares page."""
    return serve_ui_page('shares', 'shares.html')


@app.route('/plugins.html')
def serve_plugins():
    """Serve the plugins page."""
    return serve_ui_page('plugins', 'plugins.html')


@app.route('/disks.html')
def serve_disks():
    """Serve the disk management page."""
    return serve_ui_page('disks', 'disks.html')


@app.route('/network.html')
def serve_network():
    """Serve the host network page."""
    return serve_ui_page('network', 'network.html')


@app.route('/tailscale.html')
def serve_tailscale():
    """Serve the Tailscale page."""
    return serve_ui_page('tailscale', 'tailscale.html')


@app.route('/login.html')
def serve_login():
    """Serve the login page."""
    return send_from_directory(app.static_folder, 'login.html')


def get_v2_static_dir():
    """Return the absolute static directory used for v2 build artifacts."""
    return os.path.join(app.static_folder, 'v2')


def v2_index_exists():
    """Return True when the published v2 index artifact exists."""
    return os.path.isfile(os.path.join(get_v2_static_dir(), 'index.html'))


def should_redirect_legacy_page_to_v2(page_key):
    """Return whether a legacy UI route should redirect to v2."""
    mode = get_ui_mode()
    if mode == UI_MODE_LEGACY:
        return False

    if not v2_index_exists():
        return False

    if mode == UI_MODE_V2:
        return True

    return page_key in get_v2_enabled_pages()


def serve_ui_page(page_key, filename):
    """Serve legacy page or redirect to v2 based on runtime mode and page selection."""
    if should_redirect_legacy_page_to_v2(page_key):
        return redirect(get_v2_target_for_page(page_key))
    return send_from_directory(app.static_folder, filename)


@app.route('/v2')
@app.route('/v2/')
def serve_v2_index():
    """Serve the v2 SPA entrypoint."""
    if get_ui_mode() == UI_MODE_LEGACY:
        return jsonify({
            "error": "v2 UI is disabled in legacy mode",
            "mode": UI_MODE_LEGACY,
        }), 404

    if not v2_index_exists():
        return jsonify({
            "error": "v2 build artifacts are missing",
            "hint": "run `npm --prefix frontend run build:publish`",
        }), 404
    return send_from_directory(get_v2_static_dir(), 'index.html')


@app.route('/v2/<path:path>')
def serve_v2_path(path):
    """Serve v2 assets directly and fallback route-like paths to SPA index."""
    if get_ui_mode() == UI_MODE_LEGACY:
        return jsonify({
            "error": "v2 UI is disabled in legacy mode",
            "mode": UI_MODE_LEGACY,
        }), 404

    v2_static_dir = get_v2_static_dir()
    resolved_path = safe_join(v2_static_dir, path)
    if resolved_path and os.path.isfile(resolved_path):
        return send_from_directory(v2_static_dir, path)

    first_segment = path.split('/', 1)[0]
    has_extension = os.path.splitext(path)[1] != ''
    is_asset_request = first_segment == 'assets' or has_extension

    # Missing assets must return 404 instead of falling back to index.html.
    if is_asset_request:
        return jsonify({"error": f"v2 asset not found: {path}"}), 404

    if not v2_index_exists():
        return jsonify({
            "error": "v2 build artifacts are missing",
            "hint": "run `npm --prefix frontend run build:publish`",
        }), 404

    return send_from_directory(v2_static_dir, 'index.html')


@app.route('/api/login', methods=['POST'])
def api_login():
    """API endpoint for user authentication."""
    client_key = request.remote_addr or "unknown"
    retry_after = LOGIN_RATE_LIMITER.retry_after(client_key)
    if retry_after:
        response = jsonify({'error': 'Too many login attempts. Try again later.'})
        response.headers['Retry-After'] = str(retry_after)
        return response, 429

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    username = data.get('username', '').strip()
    password = data.get('password', '')

    if verify_credentials(username, password):
        LOGIN_RATE_LIMITER.reset(client_key)
        session['authenticated'] = True
        session['username'] = username
        return jsonify({
            'status': 'success',
            'username': username,
            'csrf_token': rotate_csrf_token(),
        })
    else:
        retry_after = LOGIN_RATE_LIMITER.record_failure(client_key)
        if retry_after:
            response = jsonify({'error': 'Too many login attempts. Try again later.'})
            response.headers['Retry-After'] = str(retry_after)
            return response, 429
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
            'username': session.get('username', 'unknown'),
            'csrf_token': get_csrf_token(),
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


@app.route('/api/containers/stats', methods=['GET'])
@login_required
def api_container_stats_batch():
    """API endpoint to fetch stats for multiple containers at once."""
    if not docker_available:
        return jsonify({})

    ids = request.args.get('ids', '')
    container_ids = [cid.strip() for cid in ids.split(',') if cid.strip()]

    if not container_ids:
        return jsonify({})

    result = {}
    for container_id in container_ids:
        stats = get_container_stats_cached(container_id)
        if stats:
            result[container_id] = {
                'cpu_percent': stats.get('cpu_percent'),
                'memory_percent': stats.get('memory', {}).get('percent'),
                'memory_used': stats.get('memory', {}).get('used'),
                'memory_limit': stats.get('memory', {}).get('limit'),
                'net_rx': stats.get('network', {}).get('rx'),
                'net_tx': stats.get('network', {}).get('tx'),
            }
    return jsonify(result)


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


@app.route('/api/containers/<container_id>/health', methods=['GET'])
@login_required
def api_container_health(container_id):
    """API endpoint to fetch a container's healthcheck status and latest output."""
    if not docker_available:
        return jsonify({"error": "Docker is not available"}), 503
    try:
        container = docker_client.containers.get(container_id)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(get_container_health_detail(container))


@app.route('/api/network-groups', methods=['GET'])
@login_required
def api_network_groups():
    """API endpoint listing shared-network (VPN) groups, their members, and orphans.

    Pass ?probe=true to also compare provider vs host public IP (VPN leak check)."""
    probe = request.args.get('probe', 'false').lower() == 'true'
    return jsonify(list_network_groups(probe=probe))


@app.route('/api/network-groups/<provider>/recreate', methods=['POST'])
@login_required
def api_recreate_network_group(provider):
    """API endpoint to recreate a provider and its namespace-sharing members together."""
    if not docker_available:
        return jsonify({"error": "Docker is not available"}), 503
    return jsonify(recreate_network_group(provider))


@app.route('/api/pihealth/update/config', methods=['GET'])
@login_required
def api_pihealth_update_config():
    return jsonify(_load_pihealth_update_config())


@app.route('/api/pihealth/update/config', methods=['POST'])
@login_required
def api_pihealth_update_config_save():
    data = request.get_json() or {}
    repo_path = str(data.get("repo_path", "")).strip()
    service_name = str(data.get("service_name", "")).strip()

    if not repo_path or not repo_path.startswith("/"):
        return jsonify({"error": "repo_path must be absolute"}), 400
    if not service_name:
        return jsonify({"error": "service_name is required"}), 400

    config = {"repo_path": repo_path, "service_name": service_name}
    _save_pihealth_update_config(config)
    return jsonify({"status": "saved", "config": config})


@app.route('/api/pihealth/update', methods=['POST'])
@login_required
def api_pihealth_update():
    config = _load_pihealth_update_config()
    config["user"] = getpass.getuser()
    try:
        result = helper_call("pihealth_update", config)
    except HelperError as exc:
        return jsonify({"error": str(exc)}), 503

    if not result.get("success"):
        return jsonify({"error": result.get("error", "Update failed")}), 400

    return jsonify({"status": "updating"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8002))
    app.run(host="0.0.0.0", port=port)
