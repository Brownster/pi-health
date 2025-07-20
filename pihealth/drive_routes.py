from flask import Blueprint, jsonify, request
import importlib

# These will be initialized via init_drive_routes
drive_manager = None
snapraid_manager = None
mergerfs_manager = None
failure_detector = None
health_status_cache = None


def _app_module():
    """Lazily import the app module to allow patching in tests."""
    return importlib.import_module('app')


def _drive_manager():
    return getattr(_app_module(), 'drive_manager', drive_manager)


def _snapraid_manager():
    return getattr(_app_module(), 'snapraid_manager', snapraid_manager)


def _mergerfs_manager():
    return getattr(_app_module(), 'mergerfs_manager', mergerfs_manager)


def _failure_detector():
    return getattr(_app_module(), 'failure_detector', failure_detector)


def _health_cache():
    return getattr(_app_module(), 'health_status_cache', health_status_cache)


def init_drive_routes(drive_mgr, snapraid_mgr, mergerfs_mgr, failure_det, cache):
    global drive_manager, snapraid_manager, mergerfs_manager, failure_detector, health_status_cache
    drive_manager = drive_mgr
    snapraid_manager = snapraid_mgr
    mergerfs_manager = mergerfs_mgr
    failure_detector = failure_det
    health_status_cache = cache


drive_bp = Blueprint('drive_bp', __name__)


@drive_bp.route('/api/disks', methods=['GET'])
def api_list_disks():
    """Return drive information for NAS management."""
    try:
        dm = _drive_manager()
        cache = _health_cache()
        drives = dm.discover_drives()
        drives_data = []
        for drive in drives:
            smart_health = cache.get(drive.device_path) or dm.get_smart_health(drive.device_path)
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
                "is_usb": dm.is_usb_drive(drive.device_path),
                "smart_health": smart_health,
            }
            drives_data.append(drive_info)
        return jsonify({"status": "success", "drives": drives_data, "total_drives": len(drives_data)})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to discover drives: {str(e)}", "drives": [], "total_drives": 0}), 500


@drive_bp.route('/api/smart/<path:device_path>/health', methods=['GET'])
def api_smart_health(device_path):
    try:
        device_path = '/' + device_path
        dm = _drive_manager()
        smart_health = dm.get_smart_health(device_path, use_cache=False)
        if smart_health is None:
            return jsonify({"status": "error", "message": "SMART not available for this device or device not found", "health": None}), 404
        return jsonify({"status": "success", "device_path": device_path, "health": smart_health})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to get SMART health: {str(e)}", "health": None}), 500


@drive_bp.route('/api/smart/<path:device_path>/<test_type>', methods=['POST'])
def api_smart_test(device_path, test_type):
    try:
        device_path = '/' + device_path
        valid_test_types = ['short', 'long', 'conveyance']
        if test_type not in valid_test_types:
            return jsonify({"status": "error", "message": f"Invalid test type. Must be one of: {', '.join(valid_test_types)}"}), 400
        dm = _drive_manager()
        success = dm.start_smart_test(device_path, test_type)
        if not success:
            return jsonify({"status": "error", "message": "Failed to start SMART test. Check if device supports SMART or if a test is already running."}), 400
        return jsonify({"status": "success", "message": f"Started {test_type} SMART test on {device_path}", "device_path": device_path, "test_type": test_type})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to start SMART test: {str(e)}"}), 500


@drive_bp.route('/api/smart/<path:device_path>/test-status', methods=['GET'])
def api_smart_test_status(device_path):
    try:
        device_path = '/' + device_path
        dm = _drive_manager()
        test_status = dm.get_smart_test_status(device_path)
        if test_status is None:
            return jsonify({"status": "success", "device_path": device_path, "test_status": None, "message": "No test information available"})
        return jsonify({"status": "success", "device_path": device_path, "test_status": test_status})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to get SMART test status: {str(e)}", "test_status": None}), 500


@drive_bp.route('/api/smart/<path:device_path>/history', methods=['GET'])
def api_smart_health_history(device_path):
    try:
        device_path = '/' + device_path
        days = int(request.args.get('days', 7))
        if days < 1 or days > 30:
            return jsonify({"status": "error", "message": "Days parameter must be between 1 and 30"}), 400
        dm = _drive_manager()
        history = dm.get_smart_health_history(device_path, days)
        return jsonify({"status": "success", "device_path": device_path, "days": days, "history": history, "history_count": len(history)})
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid days parameter - must be a number"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to get SMART health history: {str(e)}", "history": []}), 500


@drive_bp.route('/api/smart/<path:device_path>/trends', methods=['GET'])
def api_smart_trend_analysis(device_path):
    try:
        device_path = '/' + device_path
        days = int(request.args.get('days', 7))
        if days < 2 or days > 30:
            return jsonify({"status": "error", "message": "Days parameter must be between 2 and 30 for trend analysis"}), 400
        dm = _drive_manager()
        analysis = dm.get_smart_trend_analysis(device_path, days)
        if analysis is None:
            return jsonify({"status": "success", "device_path": device_path, "message": "Insufficient data for trend analysis", "analysis": None})
        return jsonify({"status": "success", "device_path": device_path, "analysis": analysis})
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid days parameter - must be a number"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to get SMART trend analysis: {str(e)}", "analysis": None}), 500


@drive_bp.route('/api/snapraid/status', methods=['GET'])
def api_snapraid_status():
    try:
        sm = _snapraid_manager()
        status_info = sm.get_status()
        if status_info is None:
            return jsonify({"status": "error", "message": "Unable to get SnapRAID status. Check if SnapRAID is configured and accessible.", "snapraid_status": None}), 500
        status_dict = sm.to_dict(status_info)
        return jsonify({"status": "success", "snapraid_status": status_dict})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to get SnapRAID status: {str(e)}", "snapraid_status": None}), 500


@drive_bp.route('/api/snapraid/sync', methods=['POST'])
def api_snapraid_sync():
    try:
        data = request.get_json() or {}
        force = data.get('force', False)
        sm = _snapraid_manager()
        success, message = sm.sync(force=force)
        if success:
            return jsonify({"status": "success", "message": message, "operation": "sync", "force": force})
        else:
            return jsonify({"status": "error", "message": message, "operation": "sync", "force": force}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to start SnapRAID sync: {str(e)}", "operation": "sync"}), 500


@drive_bp.route('/api/snapraid/scrub', methods=['POST'])
def api_snapraid_scrub():
    try:
        data = request.get_json() or {}
        percentage = data.get('percentage', 10)
        if not isinstance(percentage, int) or not 1 <= percentage <= 100:
            return jsonify({"status": "error", "message": "Percentage must be an integer between 1 and 100", "operation": "scrub"}), 400
        sm = _snapraid_manager()
        success, message = sm.scrub(percentage=percentage)
        if success:
            return jsonify({"status": "success", "message": message, "operation": "scrub", "percentage": percentage})
        else:
            return jsonify({"status": "error", "message": message, "operation": "scrub", "percentage": percentage}), 400
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e), "operation": "scrub"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to start SnapRAID scrub: {str(e)}", "operation": "scrub"}), 500


@drive_bp.route('/api/snapraid/diff', methods=['POST'])
def api_snapraid_diff():
    try:
        sm = _snapraid_manager()
        success, message, changes = sm.diff()
        if success:
            return jsonify({"status": "success", "message": message, "operation": "diff", "changes": changes, "change_count": len(changes)})
        else:
            return jsonify({"status": "error", "message": message, "operation": "diff", "changes": [], "change_count": 0}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to get SnapRAID diff: {str(e)}", "operation": "diff", "changes": [], "change_count": 0}), 500


@drive_bp.route('/api/snapraid/sync/async', methods=['POST'])
def api_snapraid_sync_async():
    try:
        data = request.get_json() or {}
        force = data.get('force', False)
        sm = _snapraid_manager()
        operation_id = sm.sync_async(force=force)
        return jsonify({"status": "success", "message": "SnapRAID sync operation started", "operation": "sync", "operation_id": operation_id, "force": force})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to start SnapRAID sync: {str(e)}", "operation": "sync"}), 500


@drive_bp.route('/api/snapraid/scrub/async', methods=['POST'])
def api_snapraid_scrub_async():
    try:
        data = request.get_json() or {}
        percentage = data.get('percentage', 10)
        if not isinstance(percentage, int) or not 1 <= percentage <= 100:
            return jsonify({"status": "error", "message": "Percentage must be an integer between 1 and 100", "operation": "scrub"}), 400
        sm = _snapraid_manager()
        operation_id = sm.scrub_async(percentage=percentage)
        return jsonify({"status": "success", "message": "SnapRAID scrub operation started", "operation": "scrub", "operation_id": operation_id, "percentage": percentage})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e), "operation": "scrub"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to start SnapRAID scrub: {str(e)}", "operation": "scrub"}), 500


@drive_bp.route('/api/snapraid/operations', methods=['GET'])
def api_snapraid_list_operations():
    try:
        active_only = request.args.get('active_only', 'false').lower() == 'true'
        sm = _snapraid_manager()
        operations = sm.list_operations(active_only=active_only)
        operations_data = [sm.operation_to_dict(op) for op in operations]
        return jsonify({"status": "success", "operations": operations_data, "total_operations": len(operations_data), "active_only": active_only})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to list SnapRAID operations: {str(e)}", "operations": [], "total_operations": 0}), 500


@drive_bp.route('/api/snapraid/operations/<operation_id>', methods=['GET'])
def api_snapraid_get_operation(operation_id):
    try:
        sm = _snapraid_manager()
        operation = sm.get_operation_status(operation_id)
        if operation is None:
            return jsonify({"status": "error", "message": f"Operation not found: {operation_id}", "operation": None}), 404
        operation_data = sm.operation_to_dict(operation)
        return jsonify({"status": "success", "operation": operation_data})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to get operation status: {str(e)}", "operation": None}), 500


@drive_bp.route('/api/snapraid/operations/<operation_id>/cancel', methods=['POST'])
def api_snapraid_cancel_operation(operation_id):
    try:
        sm = _snapraid_manager()
        success = sm.cancel_operation(operation_id)
        if success:
            return jsonify({"status": "success", "message": f"Operation {operation_id} cancelled successfully", "operation_id": operation_id})
        else:
            return jsonify({"status": "error", "message": f"Operation not found or cannot be cancelled: {operation_id}", "operation_id": operation_id}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to cancel operation: {str(e)}", "operation_id": operation_id}), 500


@drive_bp.route('/api/snapraid/config/generate', methods=['POST'])
def api_snapraid_generate_config():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Request body is required"}), 400
        data_drives = data.get('data_drives', [])
        parity_drives = data.get('parity_drives', [])
        content_locations = data.get('content_locations')
        if not data_drives:
            return jsonify({"status": "error", "message": "At least one data drive is required"}), 400
        if not parity_drives:
            return jsonify({"status": "error", "message": "At least one parity drive is required"}), 400
        sm = _snapraid_manager()
        config_content = sm.generate_config(data_drives=data_drives, parity_drives=parity_drives, content_locations=content_locations)
        return jsonify({"status": "success", "message": "SnapRAID configuration generated successfully", "config_content": config_content, "data_drives": data_drives, "parity_drives": parity_drives})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to generate SnapRAID configuration: {str(e)}"}), 500


@drive_bp.route('/api/snapraid/config/validate', methods=['POST'])
def api_snapraid_validate_config():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Request body is required"}), 400
        config_content = data.get('config_content', '')
        if not config_content:
            return jsonify({"status": "error", "message": "config_content is required"}), 400
        sm = _snapraid_manager()
        is_valid, errors = sm.validate_config(config_content)
        return jsonify({"status": "success", "is_valid": is_valid, "errors": errors, "error_count": len(errors)})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to validate SnapRAID configuration: {str(e)}", "is_valid": False, "errors": [], "error_count": 0}), 500


@drive_bp.route('/api/snapraid/config/update', methods=['POST'])
def api_snapraid_update_config():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Request body is required"}), 400
        data_drives = data.get('data_drives', [])
        parity_drives = data.get('parity_drives', [])
        content_locations = data.get('content_locations')
        backup = data.get('backup', True)
        if not data_drives:
            return jsonify({"status": "error", "message": "At least one data drive is required"}), 400
        if not parity_drives:
            return jsonify({"status": "error", "message": "At least one parity drive is required"}), 400
        sm = _snapraid_manager()
        success, message = sm.update_config(data_drives=data_drives, parity_drives=parity_drives, content_locations=content_locations, backup=backup)
        if success:
            return jsonify({"status": "success", "message": message, "data_drives": data_drives, "parity_drives": parity_drives, "backup_created": backup})
        else:
            return jsonify({"status": "error", "message": message}), 400
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to update SnapRAID configuration: {str(e)}"}), 500


@drive_bp.route('/api/snapraid/config/auto-update', methods=['POST'])
def api_snapraid_auto_update_config():
    try:
        sm = _snapraid_manager()
        dm = _drive_manager()
        success, message = sm.auto_update_config_from_drives(dm)
        if success:
            return jsonify({"status": "success", "message": message})
        else:
            return jsonify({"status": "error", "message": message}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to auto-update SnapRAID configuration: {str(e)}"}), 500


@drive_bp.route('/api/snapraid/config/check', methods=['GET'])
def api_snapraid_check_config():
    try:
        sm = _snapraid_manager()
        success, message = sm.check_config()
        return jsonify({"status": "success" if success else "error", "is_valid": success, "message": message})
    except Exception as e:
        return jsonify({"status": "error", "is_valid": False, "message": f"Failed to check SnapRAID configuration: {str(e)}"}), 500


@drive_bp.route('/api/mergerfs', methods=['GET'])
def api_mergerfs_pools():
    try:
        include_stats = request.args.get('include_stats', 'true').lower() == 'true'
        include_branches = request.args.get('include_branches', 'false').lower() == 'true'
        mm = _mergerfs_manager()
        pools = mm.discover_pools()
        pools_data = []
        for pool in pools:
            pool_data = mm.to_dict(pool)
            if include_stats:
                updated_pool = mm.get_pool_statistics(pool.mount_point)
                if updated_pool:
                    pool_data.update(mm.to_dict(updated_pool))
            if include_branches:
                branch_stats = mm.get_branch_statistics(pool.mount_point)
                pool_data['branch_statistics'] = mm.branch_stats_to_dict(branch_stats)
            mergerfsctl_info = mm.get_mergerfsctl_info(pool.mount_point)
            if mergerfsctl_info:
                pool_data['mergerfsctl_info'] = mergerfsctl_info
            pools_data.append(pool_data)
        return jsonify({"status": "success", "pools": pools_data, "total_pools": len(pools_data), "mergerfs_available": mm.is_mergerfs_available()})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to get MergerFS pools: {str(e)}", "pools": [], "total_pools": 0, "mergerfs_available": False}), 500


@drive_bp.route('/api/failure-detector/drive/<path:device_path>', methods=['GET'])
def api_failure_detector_drive_assessment(device_path):
    try:
        device_path = '/' + device_path
        fd = _failure_detector()
        assessment = fd.assess_drive_health(device_path)
        if assessment is None:
            return jsonify({"status": "error", "message": "Could not assess drive health", "assessment": None}), 404
        return jsonify({"status": "success", "device_path": device_path, "assessment": fd.to_dict(assessment)})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to get drive health assessment: {str(e)}", "assessment": None}), 500


@drive_bp.route('/api/failure-detector/failed-drives', methods=['GET'])
def api_failure_detector_failed_drives():
    try:
        fd = _failure_detector()
        failed_drives = fd.get_failed_drives()
        return jsonify({"status": "success", "failed_drives": failed_drives, "count": len(failed_drives)})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to get failed drives: {str(e)}", "failed_drives": [], "count": 0}), 500


@drive_bp.route('/api/failure-detector/degraded-drives', methods=['GET'])
def api_failure_detector_degraded_drives():
    try:
        fd = _failure_detector()
        degraded_drives = fd.get_degraded_drives()
        return jsonify({"status": "success", "degraded_drives": degraded_drives, "count": len(degraded_drives)})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to get degraded drives: {str(e)}", "degraded_drives": [], "count": 0}), 500


@drive_bp.route('/api/failure-detector/history/<path:device_path>', methods=['GET'])
def api_failure_detector_failure_history(device_path):
    try:
        device_path = '/' + device_path
        fd = _failure_detector()
        history = fd.get_failure_history(device_path)
        return jsonify({"status": "success", "device_path": device_path, "history": [fd.to_dict(event) for event in history], "count": len(history)})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to get failure history: {str(e)}", "history": [], "count": 0}), 500
