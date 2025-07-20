import pihealth

app = pihealth.create_app()

# Expose core objects for backwards compatibility
drive_manager = pihealth.drive_manager
snapraid_manager = pihealth.snapraid_manager
mergerfs_manager = pihealth.mergerfs_manager
failure_detector = pihealth.failure_detector
docker_client = pihealth.docker_client
docker_available = pihealth.docker_available
scheduler = pihealth.scheduler
container_updates = pihealth.container_updates
health_status_cache = pihealth.health_status_cache

__all__ = [
    'app',
    'drive_manager',
    'snapraid_manager',
    'mergerfs_manager',
    'failure_detector',
    'docker_client',
    'docker_available',
    'scheduler',
    'container_updates',
    'health_status_cache',
]

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
