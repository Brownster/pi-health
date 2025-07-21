import os
import atexit
import logging
from flask import Flask
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import docker

from nas.drive_manager import DriveManager
from nas.config_manager import ConfigManager
from nas.snapraid_manager import SnapRAIDManager
from nas.mergerfs_manager import MergerFSManager
from nas.smart_manager import SMARTManager
from nas.failure_detector import FailureDetector

# Globals populated by create_app
scheduler = None
health_status_cache = {}
container_updates = {}

docker_client = None
docker_available = False

drive_manager = None
config_manager = None
snapraid_manager = None
mergerfs_manager = None
smart_manager = None
failure_detector = None


def create_app():
    """Application factory for the PiHealth server."""
    global scheduler, docker_client, docker_available
    global drive_manager, config_manager, snapraid_manager
    global mergerfs_manager, smart_manager, failure_detector

    # Load environment variables
    load_dotenv()

    # Configure logging
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))

    app = Flask(__name__, static_folder='static')
    app.secret_key = os.getenv("PIHEALTH_SECRET_KEY", "change-me")

    # Initialize Docker client if available
    try:
        docker_client = docker.from_env()
        docker_available = True
    except Exception as e:
        print(f"Warning: Could not connect to Docker: {e}")
        docker_client = None
        docker_available = False

    # Initialize core managers
    drive_manager = DriveManager()
    config_manager = ConfigManager()
    snapraid_manager = SnapRAIDManager(config_manager)
    mergerfs_manager = MergerFSManager()
    smart_manager = SMARTManager()
    failure_detector = FailureDetector(drive_manager, snapraid_manager, smart_manager)

    scheduler = BackgroundScheduler()
    health_check_interval = int(os.getenv('SMART_HEALTH_CHECK_INTERVAL', '3600'))

    def update_drive_health_cache():
        try:
            drives = drive_manager.discover_drives()
            for drive in drives:
                smart_health = drive_manager.get_smart_health_with_history(drive.device_path, use_cache=False)
                if smart_health:
                    health_status_cache[drive.device_path] = smart_health
                    logging.info(f"Updated SMART health cache for {drive.device_path}")
        except Exception as e:
            logging.error(f"Error updating drive health cache: {e}")

    def start_background_health_monitoring():
        try:
            scheduler.add_job(update_drive_health_cache, trigger="interval", seconds=health_check_interval, id='health_check', replace_existing=True)
            scheduler.start()
            logging.info(f"Started background health monitoring with {health_check_interval}s interval")
            failure_detector.start_monitoring()
            logging.info("Started failure detector monitoring")
            atexit.register(lambda: scheduler.shutdown())
            atexit.register(lambda: failure_detector.stop_monitoring())
        except Exception as e:
            logging.error(f"Error starting background health monitoring: {e}")

    start_background_health_monitoring()

    # Register blueprints
    from .drive_routes import drive_bp, init_drive_routes
    from .system_routes import system_bp
    from .docker_routes import docker_bp
    from .auth_routes import auth_bp

    init_drive_routes(drive_manager, snapraid_manager, mergerfs_manager, failure_detector, health_status_cache)

    app.register_blueprint(system_bp)
    app.register_blueprint(docker_bp)
    app.register_blueprint(drive_bp)
    app.register_blueprint(auth_bp)

    return app
