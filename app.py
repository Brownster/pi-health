from flask import Flask, jsonify, send_from_directory, request
import psutil
import os
import docker
from compose_editor import compose_editor
from nas.drive_manager import DriveManager
from nas.snapraid_manager import SnapRAIDManager
from nas.smart_manager import SMARTManager
from nas.config_manager import ConfigManager
from nas.mergerfs_manager import MergerFSManager
from nas.failure_detector import FailureDetector
from nas.notification_manager import NotificationManager
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import logging

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

# Initialize NAS managers
drive_manager = DriveManager()
config_manager = ConfigManager()
snapraid_manager = SnapRAIDManager(config_manager)
mergerfs_manager = MergerFSManager()
smart_manager = SMARTManager()
failure_detector = FailureDetector(drive_manager, snapraid_manager, smart_manager)

# Initialize background scheduler for health monitoring
scheduler = BackgroundScheduler()
health_check_interval = int(os.getenv('SMART_HEALTH_CHECK_INTERVAL', '3600'))  # Default 1 hour

# Track update status for containers
container_updates = {}

# Health status cache for dashboard display
health_status_cache = {}


def update_drive_health_cache():
    """Background task to update drive health status cache."""
    try:
        drives = drive_manager.discover_drives()
        for drive in drives:
            # Use the new method that records to history
            smart_health = drive_manager.get_smart_health_with_history(drive.device_path, use_cache=False)
            if smart_health:
                health_status_cache[drive.device_path] = smart_health
                logging.info(f"Updated SMART health cache for {drive.device_path}")
    except Exception as e:
        logging.error(f"Error updating drive health cache: {e}")


def start_background_health_monitoring():
    """Start background health monitoring scheduler."""
    try:
        # Add job to update health cache periodically
        scheduler.add_job(
            func=update_drive_health_cache,
            trigger="interval",
            seconds=health_check_interval,
            id='health_check',
            name='Drive Health Check',
            replace_existing=True
        )
        
        # Start the scheduler
        scheduler.start()
        logging.info(f"Started background health monitoring with {health_check_interval}s interval")

        # Start the failure detector
        failure_detector.start_monitoring()
        logging.info("Started failure detector monitoring")
        
        # Shutdown scheduler when app exits
        atexit.register(lambda: scheduler.shutdown())
        atexit.register(lambda: failure_detector.stop_monitoring())
        
    except Exception as e:
        logging.error(f"Error starting background health monitoring: {e}")


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


@app.route('/drives.html')
def serve_drives():
    """Serve the drives management page."""
    return send_from_directory(app.static_folder, 'drives.html')


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


@app.route('/api/disks', methods=['GET'])
def api_list_disks():
    """
    API endpoint to return drive information for NAS management.
    
    Returns:
        JSON response with drive information including mount points,
        device names, sizes, free space, and health status.
    """
    try:
        # Discover all available drives
        drives = drive_manager.discover_drives()
        
        # Convert drive configs to JSON-serializable format
        drives_data = []
        for drive in drives:
            # Get SMART health status (use cache if available)
            smart_health = health_status_cache.get(drive.device_path) or drive_manager.get_smart_health(drive.device_path)
            
            drive_info = {
                "device_path": drive.device_path,
                "uuid": drive.uuid,
                "mount_point": drive.mount_point,
                "filesystem": drive.filesystem,
                "role": drive.role.value,
                "size_bytes": drive.size_bytes,
                "used_bytes": drive.used_bytes,
                "free_bytes": drive.free_bytes,
                "usage_percent": round(drive.usage_percent, 2),
                "health_status": drive.health_status.value,
                "label": drive.label,
                "is_usb": drive_manager.is_usb_drive(drive.device_path),
                "smart_health": smart_health
            }
            drives_data.append(drive_info)
        
        return jsonify({
            "status": "success",
            "drives": drives_data,
            "total_drives": len(drives_data)
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to discover drives: {str(e)}",
            "drives": [],
            "total_drives": 0
        }), 500


@app.route('/api/smart/<path:device_path>/health', methods=['GET'])
def api_smart_health(device_path):
    """
    API endpoint to get SMART health status for a specific device.
    
    Args:
        device_path: Device path (URL encoded)
        
    Returns:
        JSON response with SMART health information
    """
    try:
        # Decode the device path
        device_path = '/' + device_path
        
        # Get SMART health status
        smart_health = drive_manager.get_smart_health(device_path, use_cache=False)
        
        if smart_health is None:
            return jsonify({
                "status": "error",
                "message": "SMART not available for this device or device not found",
                "health": None
            }), 404
        
        return jsonify({
            "status": "success",
            "device_path": device_path,
            "health": smart_health
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get SMART health: {str(e)}",
            "health": None
        }), 500


@app.route('/api/smart/<path:device_path>/<test_type>', methods=['POST'])
def api_smart_test(device_path, test_type):
    """
    API endpoint to start a SMART test on a device.
    
    Args:
        device_path: Device path (URL encoded)
        test_type: Type of test ('short', 'long', 'conveyance')
        
    Returns:
        JSON response with test start status
    """
    try:
        # Decode the device path
        device_path = '/' + device_path
        
        # Validate test type
        valid_test_types = ['short', 'long', 'conveyance']
        if test_type not in valid_test_types:
            return jsonify({
                "status": "error",
                "message": f"Invalid test type. Must be one of: {', '.join(valid_test_types)}"
            }), 400
        
        # Start the test
        success = drive_manager.start_smart_test(device_path, test_type)
        
        if not success:
            return jsonify({
                "status": "error",
                "message": "Failed to start SMART test. Check if device supports SMART or if a test is already running."
            }), 400
        
        return jsonify({
            "status": "success",
            "message": f"Started {test_type} SMART test on {device_path}",
            "device_path": device_path,
            "test_type": test_type
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to start SMART test: {str(e)}"
        }), 500


@app.route('/api/smart/<path:device_path>/test-status', methods=['GET'])
def api_smart_test_status(device_path):
    """
    API endpoint to get SMART test status for a device.
    
    Args:
        device_path: Device path (URL encoded)
        
    Returns:
        JSON response with test status information
    """
    try:
        # Decode the device path
        device_path = '/' + device_path
        
        # Get test status
        test_status = drive_manager.get_smart_test_status(device_path)
        
        if test_status is None:
            return jsonify({
                "status": "success",
                "device_path": device_path,
                "test_status": None,
                "message": "No test information available"
            })
        
        return jsonify({
            "status": "success",
            "device_path": device_path,
            "test_status": test_status
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get SMART test status: {str(e)}",
            "test_status": None
        }), 500


@app.route('/api/smart/<path:device_path>/history', methods=['GET'])
def api_smart_health_history(device_path):
    """
    API endpoint to get SMART health history for a device.
    
    Args:
        device_path: Device path (URL encoded)
        
    Query parameters:
        days: Number of days of history to retrieve (default: 7)
        
    Returns:
        JSON response with health history
    """
    try:
        # Decode the device path
        device_path = '/' + device_path
        
        # Get days parameter
        days = int(request.args.get('days', 7))
        if days < 1 or days > 30:
            return jsonify({
                "status": "error",
                "message": "Days parameter must be between 1 and 30"
            }), 400
        
        # Get health history
        history = drive_manager.get_smart_health_history(device_path, days)
        
        return jsonify({
            "status": "success",
            "device_path": device_path,
            "days": days,
            "history": history,
            "history_count": len(history)
        })
    
    except ValueError:
        return jsonify({
            "status": "error",
            "message": "Invalid days parameter - must be a number"
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get SMART health history: {str(e)}",
            "history": []
        }), 500


@app.route('/api/smart/<path:device_path>/trends', methods=['GET'])
def api_smart_trend_analysis(device_path):
    """
    API endpoint to get SMART trend analysis for a device.
    
    Args:
        device_path: Device path (URL encoded)
        
    Query parameters:
        days: Number of days to analyze (default: 7)
        
    Returns:
        JSON response with trend analysis
    """
    try:
        # Decode the device path
        device_path = '/' + device_path
        
        # Get days parameter
        days = int(request.args.get('days', 7))
        if days < 2 or days > 30:
            return jsonify({
                "status": "error",
                "message": "Days parameter must be between 2 and 30 for trend analysis"
            }), 400
        
        # Get trend analysis
        analysis = drive_manager.get_smart_trend_analysis(device_path, days)
        
        if analysis is None:
            return jsonify({
                "status": "success",
                "device_path": device_path,
                "message": "Insufficient data for trend analysis",
                "analysis": None
            })
        
        return jsonify({
            "status": "success",
            "device_path": device_path,
            "analysis": analysis
        })
    
    except ValueError:
        return jsonify({
            "status": "error",
            "message": "Invalid days parameter - must be a number"
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get SMART trend analysis: {str(e)}",
            "analysis": None
        }), 500


@app.route('/api/snapraid/status', methods=['GET'])
def api_snapraid_status():
    """
    API endpoint to get SnapRAID status information.
    
    Returns:
        JSON response with SnapRAID parity health and sync progress
    """
    try:
        # Get SnapRAID status
        status_info = snapraid_manager.get_status()
        
        if status_info is None:
            return jsonify({
                "status": "error",
                "message": "Unable to get SnapRAID status. Check if SnapRAID is configured and accessible.",
                "snapraid_status": None
            }), 500
        
        # Convert to dictionary for JSON response
        status_dict = snapraid_manager.to_dict(status_info)
        
        return jsonify({
            "status": "success",
            "snapraid_status": status_dict
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get SnapRAID status: {str(e)}",
            "snapraid_status": None
        }), 500


@app.route('/api/snapraid/sync', methods=['POST'])
def api_snapraid_sync():
    """
    API endpoint to trigger SnapRAID parity synchronization.
    
    Request body (optional):
        {
            "force": boolean  // Force sync even if no changes detected
        }
    
    Returns:
        JSON response with sync operation result
    """
    try:
        # Parse request data
        data = request.get_json() or {}
        force = data.get('force', False)
        
        # Start sync operation
        success, message = snapraid_manager.sync(force=force)
        
        if success:
            return jsonify({
                "status": "success",
                "message": message,
                "operation": "sync",
                "force": force
            })
        else:
            return jsonify({
                "status": "error",
                "message": message,
                "operation": "sync",
                "force": force
            }), 400
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to start SnapRAID sync: {str(e)}",
            "operation": "sync"
        }), 500


@app.route('/api/snapraid/scrub', methods=['POST'])
def api_snapraid_scrub():
    """
    API endpoint to start SnapRAID scrub operation for data integrity checking.
    
    Request body (optional):
        {
            "percentage": integer  // Percentage of data to scrub (1-100, default: 10)
        }
    
    Returns:
        JSON response with scrub operation result
    """
    try:
        # Parse request data
        data = request.get_json() or {}
        percentage = data.get('percentage', 10)
        
        # Validate percentage
        if not isinstance(percentage, int) or not 1 <= percentage <= 100:
            return jsonify({
                "status": "error",
                "message": "Percentage must be an integer between 1 and 100",
                "operation": "scrub"
            }), 400
        
        # Start scrub operation
        success, message = snapraid_manager.scrub(percentage=percentage)
        
        if success:
            return jsonify({
                "status": "success",
                "message": message,
                "operation": "scrub",
                "percentage": percentage
            })
        else:
            return jsonify({
                "status": "error",
                "message": message,
                "operation": "scrub",
                "percentage": percentage
            }), 400
    
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "operation": "scrub"
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to start SnapRAID scrub: {str(e)}",
            "operation": "scrub"
        }), 500


@app.route('/api/snapraid/diff', methods=['POST'])
def api_snapraid_diff():
    """
    API endpoint to show pending changes before sync.
    
    Returns:
        JSON response with list of pending changes
    """
    try:
        # Get diff information
        success, message, changes = snapraid_manager.diff()
        
        if success:
            return jsonify({
                "status": "success",
                "message": message,
                "operation": "diff",
                "changes": changes,
                "change_count": len(changes)
            })
        else:
            return jsonify({
                "status": "error",
                "message": message,
                "operation": "diff",
                "changes": [],
                "change_count": 0
            }), 400
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get SnapRAID diff: {str(e)}",
            "operation": "diff",
            "changes": [],
            "change_count": 0
        }), 500


@app.route('/api/snapraid/sync/async', methods=['POST'])
def api_snapraid_sync_async():
    """
    API endpoint to start SnapRAID sync operation asynchronously.
    
    Request body (optional):
        {
            "force": boolean  // Force sync even if no changes detected
        }
    
    Returns:
        JSON response with operation ID for tracking progress
    """
    try:
        # Parse request data
        data = request.get_json() or {}
        force = data.get('force', False)
        
        # Start async sync operation
        operation_id = snapraid_manager.sync_async(force=force)
        
        return jsonify({
            "status": "success",
            "message": "SnapRAID sync operation started",
            "operation": "sync",
            "operation_id": operation_id,
            "force": force
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to start SnapRAID sync: {str(e)}",
            "operation": "sync"
        }), 500


@app.route('/api/snapraid/scrub/async', methods=['POST'])
def api_snapraid_scrub_async():
    """
    API endpoint to start SnapRAID scrub operation asynchronously.
    
    Request body (optional):
        {
            "percentage": integer  // Percentage of data to scrub (1-100, default: 10)
        }
    
    Returns:
        JSON response with operation ID for tracking progress
    """
    try:
        # Parse request data
        data = request.get_json() or {}
        percentage = data.get('percentage', 10)
        
        # Validate percentage
        if not isinstance(percentage, int) or not 1 <= percentage <= 100:
            return jsonify({
                "status": "error",
                "message": "Percentage must be an integer between 1 and 100",
                "operation": "scrub"
            }), 400
        
        # Start async scrub operation
        operation_id = snapraid_manager.scrub_async(percentage=percentage)
        
        return jsonify({
            "status": "success",
            "message": "SnapRAID scrub operation started",
            "operation": "scrub",
            "operation_id": operation_id,
            "percentage": percentage
        })
    
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "operation": "scrub"
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to start SnapRAID scrub: {str(e)}",
            "operation": "scrub"
        }), 500


@app.route('/api/snapraid/operations', methods=['GET'])
def api_snapraid_list_operations():
    """
    API endpoint to list SnapRAID operations.
    
    Query parameters:
        active_only: boolean  // If true, only return pending/running operations
    
    Returns:
        JSON response with list of operations
    """
    try:
        # Parse query parameters
        active_only = request.args.get('active_only', 'false').lower() == 'true'
        
        # Get operations list
        operations = snapraid_manager.list_operations(active_only=active_only)
        
        # Convert to dictionaries for JSON response
        operations_data = [snapraid_manager.operation_to_dict(op) for op in operations]
        
        return jsonify({
            "status": "success",
            "operations": operations_data,
            "total_operations": len(operations_data),
            "active_only": active_only
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to list SnapRAID operations: {str(e)}",
            "operations": [],
            "total_operations": 0
        }), 500


@app.route('/api/snapraid/operations/<operation_id>', methods=['GET'])
def api_snapraid_get_operation(operation_id):
    """
    API endpoint to get status of a specific SnapRAID operation.
    
    Args:
        operation_id: Operation ID
    
    Returns:
        JSON response with operation status
    """
    try:
        # Get operation status
        operation = snapraid_manager.get_operation_status(operation_id)
        
        if operation is None:
            return jsonify({
                "status": "error",
                "message": f"Operation not found: {operation_id}",
                "operation": None
            }), 404
        
        # Convert to dictionary for JSON response
        operation_data = snapraid_manager.operation_to_dict(operation)
        
        return jsonify({
            "status": "success",
            "operation": operation_data
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get operation status: {str(e)}",
            "operation": None
        }), 500


@app.route('/api/snapraid/operations/<operation_id>/cancel', methods=['POST'])
def api_snapraid_cancel_operation(operation_id):
    """
    API endpoint to cancel a SnapRAID operation.
    
    Args:
        operation_id: Operation ID
    
    Returns:
        JSON response with cancellation result
    """
    try:
        # Cancel the operation
        success = snapraid_manager.cancel_operation(operation_id)
        
        if success:
            return jsonify({
                "status": "success",
                "message": f"Operation {operation_id} cancelled successfully",
                "operation_id": operation_id
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Operation not found or cannot be cancelled: {operation_id}",
                "operation_id": operation_id
            }), 400
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to cancel operation: {str(e)}",
            "operation_id": operation_id
        }), 500


@app.route('/api/snapraid/config/generate', methods=['POST'])
def api_snapraid_generate_config():
    """
    API endpoint to generate SnapRAID configuration.
    
    Request body:
        {
            "data_drives": ["list", "of", "data", "drive", "paths"],
            "parity_drives": ["list", "of", "parity", "drive", "paths"],
            "content_locations": ["optional", "list", "of", "content", "locations"]
        }
    
    Returns:
        JSON response with generated configuration content
    """
    try:
        # Parse request data
        data = request.get_json()
        if not data:
            return jsonify({
                "status": "error",
                "message": "Request body is required"
            }), 400
        
        data_drives = data.get('data_drives', [])
        parity_drives = data.get('parity_drives', [])
        content_locations = data.get('content_locations')
        
        # Validate input
        if not data_drives:
            return jsonify({
                "status": "error",
                "message": "At least one data drive is required"
            }), 400
        
        if not parity_drives:
            return jsonify({
                "status": "error",
                "message": "At least one parity drive is required"
            }), 400
        
        # Generate configuration
        config_content = snapraid_manager.generate_config(
            data_drives=data_drives,
            parity_drives=parity_drives,
            content_locations=content_locations
        )
        
        return jsonify({
            "status": "success",
            "message": "SnapRAID configuration generated successfully",
            "config_content": config_content,
            "data_drives": data_drives,
            "parity_drives": parity_drives
        })
    
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to generate SnapRAID configuration: {str(e)}"
        }), 500


@app.route('/api/snapraid/config/validate', methods=['POST'])
def api_snapraid_validate_config():
    """
    API endpoint to validate SnapRAID configuration content.
    
    Request body:
        {
            "config_content": "SnapRAID configuration file content"
        }
    
    Returns:
        JSON response with validation result
    """
    try:
        # Parse request data
        data = request.get_json()
        if not data:
            return jsonify({
                "status": "error",
                "message": "Request body is required"
            }), 400
        
        config_content = data.get('config_content', '')
        if not config_content:
            return jsonify({
                "status": "error",
                "message": "config_content is required"
            }), 400
        
        # Validate configuration
        is_valid, errors = snapraid_manager.validate_config(config_content)
        
        return jsonify({
            "status": "success",
            "is_valid": is_valid,
            "errors": errors,
            "error_count": len(errors)
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to validate SnapRAID configuration: {str(e)}",
            "is_valid": False,
            "errors": [],
            "error_count": 0
        }), 500


@app.route('/api/snapraid/config/update', methods=['POST'])
def api_snapraid_update_config():
    """
    API endpoint to update SnapRAID configuration file.
    
    Request body:
        {
            "data_drives": ["list", "of", "data", "drive", "paths"],
            "parity_drives": ["list", "of", "parity", "drive", "paths"],
            "content_locations": ["optional", "list", "of", "content", "locations"],
            "backup": true  // optional, default true
        }
    
    Returns:
        JSON response with update result
    """
    try:
        # Parse request data
        data = request.get_json()
        if not data:
            return jsonify({
                "status": "error",
                "message": "Request body is required"
            }), 400
        
        data_drives = data.get('data_drives', [])
        parity_drives = data.get('parity_drives', [])
        content_locations = data.get('content_locations')
        backup = data.get('backup', True)
        
        # Validate input
        if not data_drives:
            return jsonify({
                "status": "error",
                "message": "At least one data drive is required"
            }), 400
        
        if not parity_drives:
            return jsonify({
                "status": "error",
                "message": "At least one parity drive is required"
            }), 400
        
        # Update configuration
        success, message = snapraid_manager.update_config(
            data_drives=data_drives,
            parity_drives=parity_drives,
            content_locations=content_locations,
            backup=backup
        )
        
        if success:
            return jsonify({
                "status": "success",
                "message": message,
                "data_drives": data_drives,
                "parity_drives": parity_drives,
                "backup_created": backup
            })
        else:
            return jsonify({
                "status": "error",
                "message": message
            }), 400
    
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to update SnapRAID configuration: {str(e)}"
        }), 500


@app.route('/api/snapraid/config/auto-update', methods=['POST'])
def api_snapraid_auto_update_config():
    """
    API endpoint to automatically update SnapRAID configuration based on detected drives.
    
    Returns:
        JSON response with auto-update result
    """
    try:
        # Auto-update configuration based on detected drives
        success, message = snapraid_manager.auto_update_config_from_drives(drive_manager)
        
        if success:
            return jsonify({
                "status": "success",
                "message": message
            })
        else:
            return jsonify({
                "status": "error",
                "message": message
            }), 400
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to auto-update SnapRAID configuration: {str(e)}"
        }), 500


@app.route('/api/snapraid/config/check', methods=['GET'])
def api_snapraid_check_config():
    """
    API endpoint to check SnapRAID configuration validity.
    
    Returns:
        JSON response with configuration check result
    """
    try:
        # Check configuration validity
        success, message = snapraid_manager.check_config()
        
        return jsonify({
            "status": "success" if success else "error",
            "is_valid": success,
            "message": message
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "is_valid": False,
            "message": f"Failed to check SnapRAID configuration: {str(e)}"
        }), 500


@app.route('/api/mergerfs', methods=['GET'])
def api_mergerfs_pools():
    """
    API endpoint to show current MergerFS pools and underlying paths.
    
    Query parameters:
        include_stats: boolean  // Include detailed statistics (default: true)
        include_branches: boolean  // Include branch statistics (default: false)
    
    Returns:
        JSON response with MergerFS pool information
    """
    try:
        # Parse query parameters
        include_stats = request.args.get('include_stats', 'true').lower() == 'true'
        include_branches = request.args.get('include_branches', 'false').lower() == 'true'
        
        # Discover MergerFS pools
        pools = mergerfs_manager.discover_pools()
        
        pools_data = []
        for pool in pools:
            # Get basic pool information
            pool_data = mergerfs_manager.to_dict(pool)
            
            # Add detailed statistics if requested
            if include_stats:
                updated_pool = mergerfs_manager.get_pool_statistics(pool.mount_point)
                if updated_pool:
                    pool_data.update(mergerfs_manager.to_dict(updated_pool))
            
            # Add branch statistics if requested
            if include_branches:
                branch_stats = mergerfs_manager.get_branch_statistics(pool.mount_point)
                pool_data['branch_statistics'] = mergerfs_manager.branch_stats_to_dict(branch_stats)
            
            # Add mergerfsctl info if available
            mergerfsctl_info = mergerfs_manager.get_mergerfsctl_info(pool.mount_point)
            if mergerfsctl_info:
                pool_data['mergerfsctl_info'] = mergerfsctl_info
            
            pools_data.append(pool_data)
        
        return jsonify({
            "status": "success",
            "pools": pools_data,
            "total_pools": len(pools_data),
            "mergerfs_available": mergerfs_manager.is_mergerfs_available()
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get MergerFS pools: {str(e)}",
            "pools": [],
            "total_pools": 0,
            "mergerfs_available": False
        }), 500


@app.route('/api/failure-detector/drive/<path:device_path>', methods=['GET'])
def api_failure_detector_drive_assessment(device_path):
    """
    API endpoint to get health assessment for a specific drive.
    
    Args:
        device_path: Device path (URL encoded)
        
    Returns:
        JSON response with drive health assessment
    """
    try:
        # Decode the device path
        device_path = '/' + device_path
        
        # Get health assessment
        assessment = failure_detector.assess_drive_health(device_path)
        
        if assessment is None:
            return jsonify({
                "status": "error",
                "message": "Could not assess drive health",
                "assessment": None
            }), 404
        
        return jsonify({
            "status": "success",
            "device_path": device_path,
            "assessment": failure_detector.to_dict(assessment)
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get drive health assessment: {str(e)}",
            "assessment": None
        }), 500


@app.route('/api/failure-detector/failed-drives', methods=['GET'])
def api_failure_detector_failed_drives():
    """
    API endpoint to get a list of all failed drives.
    
    Returns:
        JSON response with list of failed drives
    """
    try:
        failed_drives = failure_detector.get_failed_drives()
        
        return jsonify({
            "status": "success",
            "failed_drives": failed_drives,
            "count": len(failed_drives)
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get failed drives: {str(e)}",
            "failed_drives": [],
            "count": 0
        }), 500


@app.route('/api/failure-detector/degraded-drives', methods=['GET'])
def api_failure_detector_degraded_drives():
    """
    API endpoint to get a list of all degraded drives.
    
    Returns:
        JSON response with list of degraded drives
    """
    try:
        degraded_drives = failure_detector.get_degraded_drives()
        
        return jsonify({
            "status": "success",
            "degraded_drives": degraded_drives,
            "count": len(degraded_drives)
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get degraded drives: {str(e)}",
            "degraded_drives": [],
            "count": 0
        }), 500


@app.route('/api/failure-detector/history/<path:device_path>', methods=['GET'])
def api_failure_detector_failure_history(device_path):
    """
    API endpoint to get failure history for a specific drive.
    
    Args:
        device_path: Device path (URL encoded)
        
    Returns:
        JSON response with failure history
    """
    try:
        # Decode the device path
        device_path = '/' + device_path
        
        # Get failure history
        history = failure_detector.get_failure_history(device_path)
        
        return jsonify({
            "status": "success",
            "device_path": device_path,
            "history": [failure_detector.to_dict(event) for event in history],
            "count": len(history)
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get failure history: {str(e)}",
            "history": [],
            "count": 0
        }), 500


if __name__ == '__main__':
    # Start background health monitoring
    start_background_health_monitoring()
    
    app.run(host="0.0.0.0", port=8080)
