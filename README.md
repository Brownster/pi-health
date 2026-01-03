# pi-health

![image](https://github.com/user-attachments/assets/ea6db04f-52dd-4f5a-8576-731381744f56)

![image](https://github.com/user-attachments/assets/baa2c074-9298-4208-868c-b178bcee7a1d)

![image](https://github.com/user-attachments/assets/b0c4cb0e-308e-4ec2-8715-6a03082b99d5)

![image](https://github.com/user-attachments/assets/648c5ce6-f486-4e45-88a4-3157653a8533)


## Recommended: Bare Metal Install (Raspberry Pi)

From a clean Pi:

```bash
git clone https://github.com/Brownster/pi-health.git
cd pi-health
sudo ./setup.sh
```

This installs Python + Docker + Compose, sets up a venv, and registers a systemd service for pi-health.  
Open `http://<pi-ip>:8080` after install.

Optional overrides in `/etc/pi-health.env`:
```
THEME=coraline
DISK_PATH=/mnt/storage
DISK_PATH_2=/mnt/downloads
STACKS_PATH=/opt/stacks
```

## Container Install (Optional)

RUN
docker run -d \
-p 8080:8080 \
-v /proc:/host_proc \
-v /sys:/host_sys \
-v /var/run/docker.sock:/var/run/docker.sock \
--name pi-health-dashboard \
brownster/pi-health:latest


DOCKER COMPOSE
services:
  pi-health-dashboard:
    image: brownster/pi-health:latest
    container_name: pi-health-dashboard
    environment:
      - TZ=${TIMEZONE}
      - DISK_PATH=/mnt/storage
      - DOCKER_COMPOSE_PATH=/config/docker-compose.yml
      - ENV_FILE_PATH=/config/.env
      - BACKUP_DIR=/config/backups
    ports:
      - 8080:8080
    volumes:
      - /proc:/host_proc:ro
      - /sys:/host_sys:ro
      - /var/run/docker.sock:/var/run/docker.sock
      - ./config:/config
      - /mnt/storage:/mnt/storage #disk to monitor for storage space
    restart: unless-stopped

## Host Install (Recommended for Raspberry Pi)

From a clean Pi:

```bash
git clone https://github.com/Brownster/pi-health.git
cd pi-health
sudo ./setup.sh
```

This will:
- Install Python + Docker + Compose
- Create a venv and install `requirements.txt`
- Register a systemd service for pi-health

pi-health will start on boot and be available at `http://<pi-ip>:8080`.

Optional environment overrides can be placed in:
`/etc/pi-health.env`

Example:
```
THEME=coraline
DISK_PATH=/mnt/storage
DISK_PATH_2=/mnt/downloads
STACKS_PATH=/opt/stacks
```
## PI-PVR Base Setup Reference

pi-health is designed to run on a Raspberry Pi host prepared by the PI-PVR setup (Docker + mounts + boot ordering). The PI-PVR repository is included in `PI-PVR/` for reference.

Reference scripts:

`PI-PVR/setup.sh`
```bash
#!/bin/bash
# Main setup script

# Exit on error
set -euo pipefail

# Run the PVR setup script
./setup-pvr.sh

# Run the Spotify installer
./install_spotify.sh
```

`/usr/local/bin/check_mount_and_start.sh` (created by `PI-PVR/setup-pvr.sh`)
```bash
#!/bin/bash

STORAGE_MOUNT="/mnt/storage"
DOWNLOAD_MOUNT="/mnt/downloads"
BACKUP_MOUNT="/mnt/backup"
DOCKER_COMPOSE_FILE="$HOME/docker/docker-compose.yml"

# Wait until mounts are ready
until mountpoint -q "$STORAGE_MOUNT" && mountpoint -q "$DOWNLOAD_MOUNT" && mountpoint -q "$BACKUP_MOUNT"; do
    echo "Waiting for drives to be mounted..."
    sleep 5
done

echo "Drives are mounted. Starting Docker containers..."
docker compose -f "$DOCKER_COMPOSE_FILE" up -d
```
