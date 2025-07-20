# Pi-Health Dashboard

A comprehensive system monitoring and NAS management dashboard for Raspberry Pi and other Linux systems. Features Docker container management, SMART drive monitoring, SnapRAID integration, and advanced storage pool management.

![Pi-Health Dashboard](https://github.com/user-attachments/assets/ea6db04f-52dd-4f5a-8576-731381744f56)

## Features

### 🖥️ System Monitoring
- **Real-time System Stats**: CPU usage, memory, disk space, network I/O
- **Temperature Monitoring**: Raspberry Pi temperature via vcgencmd
- **Multi-disk Support**: Monitor multiple storage paths and backup drives
- **Background Health Checks**: Automated monitoring with configurable intervals

### 🐳 Docker Management
- **Container Overview**: View all containers with status, images, and health
- **Container Controls**: Start, stop, restart, and update containers
- **Update Detection**: Automatic detection of available container updates
- **Docker Compose Integration**: Built-in compose file editor and management

### 💾 Advanced NAS Features
- **Drive Discovery**: Automatic detection and enumeration of storage drives
- **SMART Monitoring**: Real-time SMART health data with historical tracking
- **SnapRAID Integration**: 
  - Status monitoring and operations (sync, scrub, diff)
  - Automatic configuration generation and validation
  - Asynchronous operation support with progress tracking
- **MergerFS Support**: Pooled storage management and monitoring
- **Failure Detection**: Proactive drive failure detection with notifications

### 🔧 Storage Management
- **Drive Health History**: Long-term SMART attribute tracking and trends
- **Storage Pool Monitoring**: Real-time status of merged filesystems
- **Automated Testing**: SMART self-tests (short, long, conveyance)
- **Health Alerts**: Configurable notifications for drive issues

### 🌐 Web Interface
- **Modern UI**: Responsive design with Tailwind CSS and Coraline theme
- **Authentication**: Session-based login system
- **Real-time Updates**: Live dashboard updates without page refresh
- **Multi-page Navigation**: Dedicated pages for containers, drives, and system stats

## Quick Start

### Docker Run
```bash
docker run -d \
  -p 8080:8080 \
  -v /proc:/host_proc:ro \
  -v /sys:/host_sys:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /mnt/storage:/mnt/storage:ro \
  --name pi-health-dashboard \
  brownster/pi-health:latest
```

### Docker Compose
```yaml
services:
  pi-health-dashboard:
    image: brownster/pi-health:latest
    container_name: pi-health-dashboard
    environment:
      - TZ=${TIMEZONE:-UTC}
      - DISK_PATH=/mnt/storage
      - DISK_PATH_2=/mnt/backup
      - SMART_HEALTH_CHECK_INTERVAL=3600
      - DOCKER_COMPOSE_PATH=/config/docker-compose.yml
      - ENV_FILE_PATH=/config/.env
      - BACKUP_DIR=/config/backups
    ports:
      - "8080:8080"
    volumes:
      - /proc:/host_proc:ro
      - /sys:/host_sys:ro
      - /var/run/docker.sock:/var/run/docker.sock
      - ./config:/config
      - /mnt/storage:/mnt/storage:ro
      - /mnt/backup:/mnt/backup:ro
      - /etc/snapraid:/etc/snapraid:ro
      - /etc/mergerfs:/etc/mergerfs:ro
    restart: unless-stopped
```

## Installation & Setup

### Prerequisites
- Docker and Docker Compose
- Python 3.8+ (for local development)
- Linux-based system (Raspberry Pi recommended)

### Local Development
1. **Clone the repository**:
   ```bash
   git clone https://github.com/Brownster/pi-health.git
   cd pi-health
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application**:
   ```bash
   python app.py
   ```

4. **Access the dashboard**:
   - Open http://localhost:8080
   - Default login: Use the built-in authentication

### Production Deployment
Use the Pi-Installer for automated setup with integrated NAS functionality:

```bash
# See docs/Pi-Installer/README.md for complete setup guide
curl -sSL https://raw.githubusercontent.com/Brownster/pi-health/main/docs/Pi-Installer/pi-pvr.sh | bash
```

## Configuration

### Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `TZ` | `UTC` | Timezone for log timestamps |
| `DISK_PATH` | `/` | Primary disk path to monitor |
| `DISK_PATH_2` | `/mnt/backup` | Secondary disk path to monitor |
| `SMART_HEALTH_CHECK_INTERVAL` | `3600` | Health check interval in seconds |
| `DOCKER_COMPOSE_PATH` | `/config/docker-compose.yml` | Path to Docker Compose file |
| `ENV_FILE_PATH` | `/config/.env` | Path to environment file |
| `BACKUP_DIR` | `/config/backups` | Backup directory for configurations |

### Storage Configuration
The dashboard automatically discovers and monitors:
- **Data Drives**: USB drives and additional storage
- **System Drives**: Boot and root filesystems (monitoring only)
- **Pooled Storage**: MergerFS-based storage pools
- **Parity Drives**: SnapRAID parity and content files

### SnapRAID Integration
- Automatic configuration generation based on discovered drives
- Support for multiple parity drives and content files
- Real-time operation monitoring with progress tracking
- Configurable scheduling and maintenance windows

## API Endpoints

### System Information
- `GET /api/stats` - System statistics (CPU, memory, disk, network)
- `GET /api/disks` - Discovered drives and mount points

### Container Management
- `GET /api/containers` - List all Docker containers
- `POST /api/containers/<id>/<action>` - Container actions (start, stop, restart)

### Drive Health
- `GET /api/smart/<device>/health` - SMART health status
- `POST /api/smart/<device>/<test_type>` - Run SMART tests
- `GET /api/smart/<device>/history` - Historical SMART data
- `GET /api/smart/<device>/trends` - Health trend analysis

### SnapRAID Operations
- `GET /api/snapraid/status` - SnapRAID array status
- `POST /api/snapraid/sync` - Start sync operation
- `POST /api/snapraid/scrub` - Start scrub operation
- `GET /api/snapraid/operations` - List active operations

## Architecture

### Core Components
- **Flask Application** (`app.py`): Main web server and API
- **NAS Module** (`nas/`): Storage management and monitoring
- **Drive Manager**: Hardware discovery and enumeration
- **SMART Manager**: Drive health monitoring and testing
- **SnapRAID Manager**: Array operations and configuration
- **Failure Detector**: Proactive monitoring and alerting

### Background Services
- **Health Monitoring**: Periodic SMART data collection
- **Failure Detection**: Continuous drive status monitoring
- **Operation Tracking**: SnapRAID operation progress monitoring

### Database
- SQLite-based storage for SMART history and configuration
- Automatic schema migration and data retention policies

## Development

### Project Structure
```
pi-health/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── static/               # Web interface files
│   ├── index.html        # Dashboard homepage
│   ├── containers.html   # Container management
│   ├── drives.html       # Drive monitoring
│   └── system.html       # System information
├── nas/                  # NAS management modules
│   ├── drive_manager.py  # Drive discovery and management
│   ├── smart_manager.py  # SMART monitoring
│   ├── snapraid_manager.py # SnapRAID operations
│   └── ...
├── tests/               # Comprehensive test suite
└── docs/               # Documentation and installers
```

### Running Tests
```bash
# Install test dependencies
pip install pytest pytest-cov

# Run test suite
pytest tests/

# Run with coverage
pytest --cov=nas tests/
```

### Contributing
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## Docker Integration

The dashboard includes comprehensive Docker integration for pooled storage environments:

### Features
- **Storage Health Checks**: Validates storage accessibility before container startup
- **Volume Mount Configuration**: Automatic configuration for pooled storage
- **Container Dependencies**: Ensures proper startup order with storage dependencies
- **Health Monitoring**: Continuous monitoring of storage pool status

### Integration Components
- **Storage Health Script**: Pre-startup validation (`check-docker-storage-health.sh`)
- **Systemd Integration**: Service dependencies for reliable startup
- **Docker Compose Override**: Enhanced container configuration with health checks

See `DOCKER_INTEGRATION_SUMMARY.md` for detailed implementation information.

## Troubleshooting

### Common Issues

**Docker connection fails**:
- Ensure Docker socket is mounted: `-v /var/run/docker.sock:/var/run/docker.sock`
- Check Docker daemon is running: `systemctl status docker`

**SMART data unavailable**:
- Ensure smartmontools is installed on the host
- Check device permissions for container access
- Some drives may not support SMART (especially USB adapters)

**SnapRAID operations fail**:
- Verify SnapRAID configuration is valid
- Check file permissions for config directory
- Ensure sufficient disk space for operations

**Storage not detected**:
- Check mount points are accessible from container
- Verify volume mounts in Docker configuration
- Review drive discovery logs in application output

### Logging
- Application logs are output to stdout/stderr
- Enable debug logging by setting log level in the application
- Docker logs: `docker logs pi-health-dashboard`

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- **LinuxServer.io** for container inspiration and best practices
- **Docker** and **Docker Compose** for containerization
- **Flask** and **psutil** for the core application framework
- **SnapRAID** and **MergerFS** for advanced storage management
- **Tailwind CSS** for the modern web interface

## Support

- 🐛 **Issues**: [GitHub Issues](https://github.com/Brownster/pi-health/issues)
- 📖 **Documentation**: See `docs/` directory
- 💬 **Discussions**: [GitHub Discussions](https://github.com/Brownster/pi-health/discussions)

---

**Pi-Health Dashboard** - Comprehensive NAS monitoring and management for Raspberry Pi and Linux systems.