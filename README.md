# Pi-Health

Pi-Health is a full home lab management interface for Raspberry Pi and small servers. It provides system monitoring, Docker management, storage pooling, shares, app templates, and automation in a single UI.

![Dashboard](https://github.com/user-attachments/assets/ea6db04f-52dd-4f5a-8576-731381744f56)

![Containers](https://github.com/user-attachments/assets/baa2c074-9298-4208-868c-b178bcee7a1d)

![Stacks](https://github.com/user-attachments/assets/b0c4cb0e-308e-4ec2-8715-6a03082b99d5)

![Apps](https://github.com/user-attachments/assets/648c5ce6-f486-4e45-88a4-3157653a8533)

## Features

- **System Health Monitoring**: CPU, memory, temperature, disk, and network stats
- **Docker Management**: View, start, stop, and restart containers
- **Stack Management**: Deploy and manage Docker Compose stacks
- **App Store**: YAML-driven catalog with one-click deployments
- **Disk Management**: Mount/unmount drives and manage fstab entries
- **Storage Plugins**: SnapRAID parity protection and MergerFS drive pooling
- **Remote Mounts**: SSHFS mounts with automount support
- **Share Plugins**: Samba sharing (NFS planned)
- **Networking Setup**: Tailscale and VPN (Gluetun) bootstrap
- **Updates**: Container auto-update scheduler and Pi-Health self-update
- **Backups**: Scheduled config backups
- **Tools**: CopyParty deployment and configuration
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

## Installation (Host Service Only)

Pi-Health runs as a systemd service on the host. Docker deployment is no longer supported.

### Bare Metal Install (Recommended)

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

Access the dashboard at `http://<host-ip>:8002`

## Quick Start

1. Create `/etc/pi-health.env` with your admin credentials:
   ```bash
   sudo tee /etc/pi-health.env >/dev/null <<'EOF'
   PIHEALTH_USER=admin
   PIHEALTH_PASSWORD=change-me
   EOF
   ```
2. Install and start Pi-Health:
   ```bash
   ./start.sh
   ```
3. Log in at `http://<host-ip>:8002` (defaults to `admin` / `pihealth` if you skip step 1).
4. Go to **Settings > Plugins** and enable the storage/share plugins you need.
5. Use **Disks**, **Storage**, **Apps**, and **Tools** to configure mounts, pools, apps, and CopyParty.

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

# Run E2E UI tests (Playwright)
# Requires: pip install playwright pytest-playwright
# Then install browsers: playwright install
BASE_URL=http://localhost:8002 pytest -m e2e tests/e2e/ -v

# Run tests in tox (consistent envs)
# Unit tests:
tox -e unit
# UI tests (app must be running on BASE_URL):
BASE_URL=http://localhost:8002 tox -e e2e
# Full test suite (unit + e2e). tox will start the app automatically:
tox -e all

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

### Container Memory Stats Not Showing

On Raspberry Pi OS, cgroup memory accounting is disabled by default. Container CPU and network stats will work, but memory will show as "—".

To enable memory stats, add these parameters to your kernel command line:

```bash
sudo nano /boot/firmware/cmdline.txt
```

Add to the **end** of the existing line (keep it all on one line):
```
cgroup_enable=memory cgroup_memory=1
```

Then reboot. Note: This uses slightly more RAM for memory tracking.

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions welcome! Please open an issue or submit a pull request.
