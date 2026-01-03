# Pi-Health

A lightweight, web-based dashboard for monitoring and managing Raspberry Pi systems running Docker. Features system health monitoring, container management, disk management, and storage pooling with SnapRAID/MergerFS integration.

![Dashboard](https://github.com/user-attachments/assets/ea6db04f-52dd-4f5a-8576-731381744f56)

![Containers](https://github.com/user-attachments/assets/baa2c074-9298-4208-868c-b178bcee7a1d)

![Stacks](https://github.com/user-attachments/assets/b0c4cb0e-308e-4ec2-8715-6a03082b99d5)

![Apps](https://github.com/user-attachments/assets/648c5ce6-f486-4e45-88a4-3157653a8533)

## Features

- **System Health Monitoring**: CPU, memory, temperature, and disk usage
- **Docker Management**: View, start, stop, and restart containers
- **Stack Management**: Deploy and manage Docker Compose stacks
- **App Store**: One-click deployment of popular self-hosted applications
- **Disk Management**: Mount/unmount drives, manage fstab entries
- **Storage Plugins**: SnapRAID parity protection and MergerFS drive pooling
- **Auto-Update Scheduler**: Automatically update container images on a schedule
- **Multi-user Authentication**: Support for multiple users
- **Theming**: Multiple visual themes (Coraline, Professional, Minimal)

## Supported Hardware

### Recommended Configurations

| Configuration | Description | Use Case |
|--------------|-------------|----------|
| **Raspberry Pi 4/5 (4GB+)** | Primary target platform | Home server, media management |
| **Raspberry Pi 4/5 (8GB)** | For running more containers | NAS, Plex/Jellyfin with transcoding |
| **x86/x64 Linux** | Any Debian/Ubuntu-based system | Development, VMs, repurposed PCs |

### Storage Configurations

| Setup | Drives | Protection | Best For |
|-------|--------|------------|----------|
| **Single Drive** | 1 | None | Simple media storage |
| **Basic NAS** | 2-4 | MergerFS pooling | Combined storage, no redundancy |
| **Protected NAS** | 3+ | SnapRAID + MergerFS | Data protection with parity |
| **Multi-Parity** | 5+ | SnapRAID (2+ parity) | Maximum protection |

### Drive Recommendations

- **Boot Drive**: 32GB+ SD card or USB SSD (recommended for longevity)
- **Data Drives**: USB 3.0 HDDs or SSDs via powered USB hub
- **For SnapRAID**: Parity drive should be >= largest data drive

### USB Hub Requirements

When connecting multiple drives to a Raspberry Pi:
- Use a **powered USB 3.0 hub** (drives draw significant power)
- Recommended: 10+ port hub with 5V/4A+ power supply
- Avoid bus-powered hubs for HDDs

## Installation

### Bare Metal Install (Recommended for Raspberry Pi)

```bash
git clone https://github.com/Brownster/pi-health.git
cd pi-health
./start.sh
```

This will:
- Install Python and Docker CE (including Docker Compose plugin)
- Create a Python virtual environment
- Set up the privileged helper service (for disk operations)
- Register a systemd service for pi-health
- Create the `pihealth` group for socket permissions

Optional flags:

```bash
# Install Tailscale
ENABLE_TAILSCALE=1 ./start.sh

# Configure VPN (Gluetun) network + PIA credentials
ENABLE_VPN=1 PIA_USERNAME=your_user PIA_PASSWORD=your_pass ./start.sh
```

Access the dashboard at `http://<pi-ip>:80`

### Example: Split VPN and Non-VPN Stacks

Services that use `network_mode: "service:vpn"` must live in the same stack as the `vpn` container.
For a quick bootstrap, see:

- `examples/stacks/vpn-stack/docker-compose.yml`
- `examples/stacks/media-stack/docker-compose.yml`

Copy the `examples/stacks/.env.example` file to each stack folder as `.env` and set `HOME=/home/pi`.
Each folder can then be placed under `STACKS_PATH` (default: `/opt/stacks`).

Quick copy:

```bash
sudo mkdir -p /opt/stacks
sudo cp -r examples/stacks/vpn-stack /opt/stacks/
sudo cp -r examples/stacks/media-stack /opt/stacks/
sudo cp examples/stacks/.env.example /opt/stacks/vpn-stack/.env
sudo cp examples/stacks/.env.example /opt/stacks/media-stack/.env
```

### Docker Install

**Docker Run:**
```bash
docker run -d \
  -p 8080:8080 \
  -v /proc:/host_proc:ro \
  -v /sys:/host_sys:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --name pi-health-dashboard \
  brownster/pi-health:latest
```

**Docker Compose:**
```yaml
services:
  pi-health-dashboard:
    image: brownster/pi-health:latest
    container_name: pi-health-dashboard
    environment:
      - TZ=${TIMEZONE}
      - DISK_PATH=/mnt/storage
      - STACKS_PATH=/opt/stacks
    ports:
      - 8080:8080
    volumes:
      - /proc:/host_proc:ro
      - /sys:/host_sys:ro
      - /var/run/docker.sock:/var/run/docker.sock
      - ./config:/config
      - /mnt/storage:/mnt/storage
    restart: unless-stopped
```

> **Note**: Disk management and storage plugin features require the bare metal install with the helper service.

## Configuration

### Environment Variables

Create `/etc/pi-health.env` for configuration overrides:

```bash
# Theme selection (coraline, professional, minimal)
THEME=coraline

# Paths to monitor for disk usage
DISK_PATH=/mnt/storage
DISK_PATH_2=/mnt/downloads

# Docker stack directory
STACKS_PATH=/opt/stacks

# Authentication (default: admin/pihealth)
PIHEALTH_USER=admin
PIHEALTH_PASSWORD=your_secure_password

# Multi-user support
PIHEALTH_USERS=admin:password1,user2:password2
```

### Storage Plugin Configuration

Storage plugins store their configuration in `config/storage_plugins/`:

- `snapraid.json` - SnapRAID array configuration
- `mergerfs.json` - MergerFS pool configuration

## Storage Management

### SnapRAID

SnapRAID provides parity-based backup for your data drives. Unlike RAID, it:
- Protects individual files (not blocks)
- Allows mixing different drive sizes
- Runs on a schedule (not real-time)
- Lets you recover from up to 6 drive failures (with 6 parity drives)

**Configuration via UI:**
1. Navigate to Storage > SnapRAID tab
2. Add data drives and parity drive(s)
3. Configure exclusion patterns
4. Set sync/scrub schedules
5. Click "Apply Config"

**Safety Features:**
- Delete threshold (default 50 files) - warns before large deletions
- Update threshold (default 500 files) - warns before large changes
- Recovery status dashboard

### MergerFS

MergerFS combines multiple drives into a single unified mount point:
- Drives appear as one large volume
- Configurable file placement policies
- No striping - files stay intact on individual drives
- Easy to add/remove drives

**Supported Policies:**
| Policy | Description |
|--------|-------------|
| `epmfs` | Existing path, most free space (default) |
| `mfs` | Most free space |
| `lfs` | Least free space |
| `rand` | Random distribution |
| `pfrd` | Percentage free random distribution |

**Configuration via UI:**
1. Navigate to Storage > MergerFS tab
2. Create a new pool
3. Add branch paths (source drives)
4. Set mount point and policy
5. Click "Apply Config"

### Recommended Setup: MergerFS + SnapRAID

For a protected NAS setup:

```
/mnt/disk1  ─┐
/mnt/disk2  ─┼─► MergerFS ─► /mnt/storage (unified view)
/mnt/disk3  ─┘
/mnt/parity ────► SnapRAID parity protection
```

1. Mount individual drives under `/mnt/`
2. Create MergerFS pool combining data drives
3. Configure SnapRAID with data drives + parity drive
4. Schedule nightly SnapRAID sync

## Auto-Update Scheduler

Automatically pull and update Docker images for your stacks:

1. Navigate to Settings
2. Enable Auto-Update
3. Choose schedule (Daily 4 AM or Weekly Sunday 4 AM)
4. Optionally exclude specific stacks
5. View update history and results

## App Store

One-click deployment of popular self-hosted applications:

- **Media**: Plex, Jellyfin, Sonarr, Radarr, Prowlarr
- **Downloads**: qBittorrent, SABnzbd, NZBGet
- **Utilities**: Portainer, Heimdall, Nginx Proxy Manager
- **And many more...**

Apps are deployed as Docker Compose stacks with sensible defaults.

## Privileged Helper Service

The helper service (`pihealth-helper.service`) runs as root and handles:
- Mounting/unmounting drives
- Writing to `/etc/fstab`
- Writing SnapRAID configuration to `/etc/snapraid.conf`
- Managing systemd timers for scheduled tasks
- Running SnapRAID commands (sync, scrub, fix)

Communication happens over a Unix socket with strict command allowlisting.

## Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Start development server
python app.py
```

## Troubleshooting

### Helper Service Issues

```bash
# Check helper service status
sudo systemctl status pihealth-helper

# View helper logs
sudo journalctl -u pihealth-helper -f

# Restart helper service
sudo systemctl restart pihealth-helper
```

### Permission Issues

Ensure your user is in the `pihealth` group:
```bash
sudo usermod -aG pihealth $USER
# Log out and back in for changes to take effect
```

### Drive Mount Issues

```bash
# List detected drives
lsblk -f

# Check fstab syntax
sudo mount -a

# View mount errors
dmesg | tail -20
```

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions welcome! Please open an issue or submit a pull request.
