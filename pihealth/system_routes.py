import os
import logging
import psutil
from flask import Blueprint, jsonify, send_from_directory

from . import docker_client, docker_available, container_updates

# Serve static HTML files from the project-level static directory
system_bp = Blueprint(
    "system_bp",
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), "..", "static"),
)


def calculate_cpu_usage(cpu_line):
    user, nice, system, idle, iowait, irq, softirq, steal = map(int, cpu_line[1:9])
    total_time = user + nice + system + idle + iowait + irq + softirq + steal
    idle_time = idle + iowait
    usage_percent = 100 * (total_time - idle_time) / total_time
    return usage_percent


def get_system_stats():
    try:
        with open('/host_proc/stat', 'r') as f:
            cpu_line = f.readline().split()
            cpu_usage = calculate_cpu_usage(cpu_line)
    except Exception:
        cpu_usage = None

    memory = psutil.virtual_memory()
    memory_usage = {
        "total": memory.total,
        "used": memory.used,
        "free": memory.available,
        "percent": memory.percent,
    }

    disk_path = os.getenv('DISK_PATH', '/')
    disk = psutil.disk_usage(disk_path)
    disk_usage = {
        "total": disk.total,
        "used": disk.used,
        "free": disk.free,
        "percent": disk.percent,
    }

    disk_path_2 = os.getenv('DISK_PATH_2', '/mnt/backup')
    disk_2 = psutil.disk_usage(disk_path_2)
    disk_usage_2 = {
        "total": disk_2.total,
        "used": disk_2.used,
        "free": disk_2.free,
        "percent": disk_2.percent,
    }

    if os.path.exists('/usr/bin/vcgencmd'):
        try:
            temp_output = os.popen('vcgencmd measure_temp').readline()
            temperature = float(temp_output.replace('temp=', '').replace("'C\n", ''))
        except Exception:
            temperature = None
    else:
        temperature = None

    net_io = psutil.net_io_counters()
    network_usage = {
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
    }

    return {
        "cpu_usage_percent": cpu_usage,
        "memory_usage": memory_usage,
        "disk_usage": disk_usage,
        "disk_usage_2": disk_usage_2,
        "temperature_celsius": temperature,
        "network_usage": network_usage,
    }


def list_containers():
    if not docker_available:
        return [{"id": "docker-not-available", "name": "Docker Not Available", "status": "unavailable", "image": "N/A"}]
    try:
        containers = docker_client.containers.list(all=True)
        return [
            {
                "id": c.id[:12],
                "name": c.name,
                "status": c.status,
                "image": c.image.tags[0] if c.image.tags else 'unknown',
                "update_available": container_updates.get(c.id[:12], False),
            }
            for c in containers
        ]
    except Exception as e:
        logging.error(f"Error listing containers: {e}")
        return [{"id": "error-listing", "name": "Error Listing Containers", "status": "error", "image": str(e)}]


def check_container_update(container):
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
    try:
        if not container.image.tags:
            return {"error": "Container image has no tag"}
        tag = container.image.tags[0]
        docker_client.images.pull(tag)
        import subprocess
        subprocess.run(['docker', 'compose', 'up', '-d', container.name], check=False)
        container_updates[container.id[:12]] = False
        return {"status": "Container updated"}
    except Exception as e:
        return {"error": str(e)}


def control_container(container_id, action):
    if not docker_available:
        return {"error": "Docker is not available"}
    try:
        container = docker_client.containers.get(container_id)
        if action == 'start':
            container.start()
        elif action == 'stop':
            container.stop()
        elif action == 'restart':
            container.restart()
        elif action == 'check_update':
            return check_container_update(container)
        elif action == 'update':
            return update_container(container)
        else:
            return {"error": "Invalid action"}
        return {"status": f"Container {action}ed successfully"}
    except Exception as e:
        return {"error": str(e)}


def system_action(action):
    try:
        if action == 'shutdown':
            import subprocess
            subprocess.Popen(['sudo', 'shutdown', '-h', 'now'])
            return {"status": "Shutdown initiated"}
        elif action == 'reboot':
            import subprocess
            subprocess.Popen(['sudo', 'reboot'])
            return {"status": "Reboot initiated"}
        else:
            return {"error": "Invalid system action"}
    except Exception as e:
        return {"error": str(e)}


@system_bp.route('/')
def serve_frontend():
    return send_from_directory(system_bp.static_folder or 'static', 'index.html')


@system_bp.route('/system.html')
def serve_system():
    return send_from_directory(system_bp.static_folder or 'static', 'system.html')


@system_bp.route('/containers.html')
def serve_containers():
    return send_from_directory(system_bp.static_folder or 'static', 'containers.html')


@system_bp.route('/drives.html')
def serve_drives():
    return send_from_directory(system_bp.static_folder or 'static', 'drives.html')


@system_bp.route('/edit.html')
def serve_edit():
    return send_from_directory(system_bp.static_folder or 'static', 'edit.html')


@system_bp.route('/login.html')
def serve_login():
    return send_from_directory(system_bp.static_folder or 'static', 'login.html')


@system_bp.route('/coraline-banner.jpg')
def serve_banner():
    return send_from_directory(system_bp.static_folder or 'static', 'coraline-banner.jpg')


@system_bp.route('/api/stats', methods=['GET'])
def api_stats():
    return jsonify(get_system_stats())




@system_bp.route('/api/shutdown', methods=['POST'])
def api_shutdown():
    return jsonify(system_action('shutdown'))


@system_bp.route('/api/reboot', methods=['POST'])
def api_reboot():
    return jsonify(system_action('reboot'))
