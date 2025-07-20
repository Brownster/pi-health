#!/bin/bash
# Server Variables
SHARE_METHOD=""
SERVER_IP=$(hostname -I | awk '{print $1}')
# General Variables
CONTAINER_NETWORK="vpn_network"
DOCKER_DIR="$HOME/docker"
ENV_FILE="$DOCKER_DIR/.env"

# Exit on error
set -euo pipefail

# Toggle debug mode: true = show all outputs, false = suppress outputs
DEBUG=true  # Set to 'false' to suppress command outputs

# Function to handle command output based on DEBUG flag
run() {
    if [ "$DEBUG" = true ]; then
        "$@"  # Run commands normally, show output
    else
        "$@" >/dev/null 2>&1  # Suppress output
    fi
}

# Create .env file for sensitive data
create_env_file() {
    echo "Creating .env file for sensitive data..."
    mkdir -p "$DOCKER_DIR"
    if [[ ! -f "$ENV_FILE" ]]; then
        read -r -p "Enter your PIA_USERNAME: " PIA_USERNAME
        read -r -s -p "Enter your PIA_PASSWORD: " PIA_PASSWORD
        echo ""
        read -r -p "Enter your TAILSCALE_AUTH_KEY (or press Enter to skip): " TAILSCALE_AUTH_KEY
        

        cat > "$ENV_FILE" <<EOF
#General Docker
DOCKER_DIR="$HOME/docker"
DOCKER_COMPOSE_URL="https://raw.githubusercontent.com/Brownster/docker-compose-pi/refs/heads/main/docker-compose.yml"

# Docker Configuration (Optional)
TIMEZONE=Europe/London
IMAGE_RELEASE="latest"
PUID=1000
PGID=1000

# Media folder names
MOVIES_FOLDER="Movies"       # Name of the folder for movies/films/kids films etc
TVSHOWS_FOLDER="TVShows"     # Name of the folder for TV shows/TV/kids TV etc
DOWNLOADS="/mnt/storage/downloads"
STORAGE_MOUNT="/mnt/storage/"

# Samba Variable
SAMBA_CONFIG="/etc/samba/smb.conf" # Path to Samba configuration file

#Tailscale
TAILSCALE_AUTH_KEY=$TAILSCALE_AUTH_KEY

#PORTS
JACKET_PORT="9117"
SONARR_PORT="8989"
RADARR_PORT="7878"
TRANSMISSION_PORT="9091"
NZBGET="6789"
GET_IPLAYER_PORT="1935"
MEDIASERVER_HTTP="8096"
MEDIASERVER_HTTPS="8920"

# VPN Configuration
PIA_USERNAME=$PIA_USERNAME
PIA_PASSWORD=$PIA_PASSWORD
VPN_CONTAINER="vpn"
VPN_IMAGE="qmcgaw/gluetun"
CONTAINER_NETWORK="vpn_network"

#Jacket
JACKETT_CONTAINER="jackett"
JACKETT_IMAGE="linuxserver/jackett"

#Sonarr
SONARR_CONTAINER="sonarr"
SONARR_IMAGE="linuxserver/sonarr"
SONARR_API_KEY="your_sonarr_api_key"   # Replace with actual API key after install

#Radarr
RADARR_CONTAINER="radarr"
RADARR_IMAGE="linuxserver/radarr"
RADARR_API_KEY="your_radarr_api_key"   # Replace with actual API key after install

#Transmission
TRANSMISSION_CONTAINER="transmission"
TRANSMISSION_IMAGE="linuxserver/transmission"
#NZBGet
NZBGET_CONTAINER="nzbget"
NZBGET_IMAGE="linuxserver/nzbget"

#Get Iplayer
GET_IPLAYER="get_iplayer"
GET_IPLAYER_IMAGE="ghcr.io/thespad/get_iplayer
INCLUDERADIO="true"
ENABLEIMPORT="true"

#JellyFin
JELLYFIN_CONTAINER="jellyfin"
JELLYFIN_IMAGE="linuxserver/jellyfin"

#WatchTower
WATCHTOWER_CONTAINER="watchtower"
WATCHTOWER_IMAGE="containrrr/watchtower"

#Track runs
tailscale_install_success=0
PIA_SETUP_SUCCESS=0
SHARE_SETUP_SUCCESS=0
docker_install_success=0
pia_vpn_setup_success=0
docker_compose_success=0
CREATE_CONFIG_SUCCESS=0
INSTALL_DEPENDANCIES_SUCCESS=0
DOCKER_NETWORK_SUCCESS=0
EOF
        echo ".env file created at $ENV_FILE."
        chmod 600 "$ENV_FILE"
    else
        echo ".env file already exists. Update credentials if necessary."
    fi
}


#GET_IPLAYER CONFIG CREATION
create_config_json() {
    if [[ "$CREATE_CONFIG_SUCCESS" == "1" ]]; then
        echo "IPlayer Get config already setup. Skipping."
        return
    fi   
    echo "Creating config.json for SonarrAutoImport..."

    # Define paths
    CONFIG_DIR="$DOCKER_DIR/get_iplayer/config"
    CONFIG_FILE="$CONFIG_DIR/config.json"

    # Ensure the directory exists
    mkdir -p "$CONFIG_DIR"

    # Generate the config.json file
    cat > "$CONFIG_FILE" <<EOF
{
  "radarr": {
    "url" : "http://127.0.0.1:${RADARR_PORT}",
    "apiKey" : "${RADARR_API_KEY}",
    "mappingPath" : "/downloads/",
    "downloadsFolder" : "${DOWNLOADS}/complete",
    "importMode" : "Move",
    "timeoutSecs" : "5"
  },
  "sonarr": {
    "url" : "http://127.0.0.1:${SONARR_PORT}",
    "apiKey" : "${SONARR_API_KEY}",
    "mappingPath" : "/downloads/",
    "downloadsFolder" : "${DOWNLOADS}/complete",
    "importMode" : "Copy",
    "timeoutSecs" : "5",
    "trimFolders" : "true",
    "transforms" : [
      {
        "search" : "Escape_to_the_Country_Series_(\\d+)_-_S(\\d+)E(\\d+)_-_.+\\.mp4",
        "replace" : "Escape to the Country S\$2E\$3.mp4"
      },
      {
        "search" : "Escape_to_the_Country_Series_(\\d+)_Extended_Versions_-_S(\\d+)E(\\d+)_-_.+\\.mp4",
        "replace" : "Escape to the Country Extended S\$2E\$3.mp4"
      },
      {
        "search" : "Escape_to_the_Country_Series_(\\d+)_-_Episode_(\\d+)\\.mp4",
        "replace" : "Escape to the Country S\$1E\$2.mp4"
      },
      {
        "search" : "Escape_to_the_Country_(\\d{4})_Season_(\\d+)_-_Episode_(\\d+)\\.mp4",
        "replace" : "Escape to the Country S\$2E\$3.mp4"
      }
    ]
  }
}
EOF

    # Update permissions
    chmod 600 "$CONFIG_FILE"

    echo "config.json created at $CONFIG_FILE."
    echo "Please update the API keys in the config file before running the container."
    sed -i 's/CREATE_CONFIG_SUCCESS=0/CREATE_CONFIG_SUCCESS==1/' "$ENV_FILE"
}



# Function to update /etc/fstab with the new mount point
update_fstab() {
    local mount_point="$1"
    local device="$2"

    # Get the UUID of the device
    local uuid=$(blkid -s UUID -o value "$device")
    if [[ -z "$uuid" ]]; then
        echo "Error: Could not retrieve UUID for device $device."
        exit 1
    fi

    # Check if the mount point is already in /etc/fstab
    if grep -q "$mount_point" /etc/fstab; then
        echo "Mount point $mount_point already exists in /etc/fstab. Skipping."
    else
        echo "Adding $mount_point to /etc/fstab..."
        echo "UUID=$uuid $mount_point auto defaults 0 2" | sudo tee -a /etc/fstab > /dev/null
    fi
}


# Install and configure Tailscale
setup_tailscale() {
    if [[ "$tailscale_install_success" == "1" ]]; then
        echo "Tailscale is already installed. Skipping."
        return
    fi
    
    echo "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
    echo "Tailscale installed."

    echo "Starting Tailscale and authenticating..."
    if [[ -z "$TAILSCALE_AUTH_KEY" ]]; then
        echo "TAILSCALE_AUTH_KEY is not set. Tailscale will require manual authentication."
        sudo tailscale up --accept-routes=false
    else
        sudo tailscale up --accept-routes=false --authkey="$TAILSCALE_AUTH_KEY"
    fi

    echo "Tailscale is running."
    echo "Access your server using its Tailscale IP: $(tailscale ip -4)"
    echo "Manage devices at https://login.tailscale.com."
    # Mark success
    sed -i 's/tailscale_install_success=0/tailscale_install_success=1/' "$ENV_FILE"
}

setup_pia_vpn() {
    if [[ "$PIA_SETUP_SUCCESS" == "1" ]]; then
        echo "PIA already setup. Skipping."
        return
    fi
    
    echo "Setting up PIA OpenVPN VPN..."

    # Source the .env file to load PIA credentials
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    else
        echo "Error: .env file not found. Ensure you have run create_env_file first."
        exit 1
    fi

    # Ensure PIA credentials are set
    if [[ -z "$PIA_USERNAME" || -z "$PIA_PASSWORD" ]]; then
        echo "Error: PIA credentials are not set. Ensure PIA_USERNAME and PIA_PASSWORD are correctly provided in the .env file."
        exit 1
    fi

    # Create the gluetun directory for configuration
    GLUETUN_DIR="$DOCKER_DIR/$VPN_CONTAINER"
    echo "Creating Gluetun configuration directory at $GLUETUN_DIR..."
    mkdir -p "$GLUETUN_DIR"

    # Write the environment variables to a Docker Compose file
    cat > "$GLUETUN_DIR/.env" <<EOF
VPN_SERVICE_PROVIDER=private internet access
OPENVPN_USER=$PIA_USERNAME
OPENVPN_PASSWORD=$PIA_PASSWORD
SERVER_REGIONS=Netherlands
EOF

    echo "OpenVPN setup complete. Configuration saved to $GLUETUN_DIR/.env."
    # Mark success
    sed -i 's/PIA_SETUP_SUCCESS=0/PIA_SETUP_SUCCESS=1/' "$ENV_FILE"
}


#choose storage configuration method
choose_storage_configuration() {
    if [[ "$SHARE_SETUP_SUCCESS" == "1" ]]; then
        echo "Storage configuration already setup. Skipping."
        return
    fi    

    echo "Choose your storage configuration:"
    echo "1. Traditional single-drive setup (existing behavior)"
    echo "2. Pooled storage with redundancy (NAS pooling)"
    read -r -p "Enter the number (1 or 2): " STORAGE_CONFIG

    if [[ "$STORAGE_CONFIG" == "2" ]]; then
        setup_pooled_storage
    else
        echo "Setting up traditional single-drive configuration..."
        choose_sharing_method
    fi

    SERVER_IP=$(hostname -I | awk '{print $1}') # Ensure SERVER_IP is set here for global use
}

#choose smb or nfs (smb if using windows devices to connect)
choose_sharing_method() {
    echo "Choose your preferred file sharing method:"
    echo "1. Samba (Best for cross-platform: Windows, macOS, Linux)"
    echo "2. NFS (Best for Linux-only environments)"
    read -r -p "Enter the number (1 or 2): " SHARE_METHOD

    if [[ "$SHARE_METHOD" == "1" ]]; then
        setup_usb_and_samba
    elif [[ "$SHARE_METHOD" == "2" ]]; then
        setup_usb_and_nfs
    else
        echo "Invalid selection. Defaulting to Samba."
        SHARE_METHOD="1"
        setup_usb_and_samba
    fi
}

# Enhanced pooling software installation with dependency checking and systemd setup
install_pooling_software() {
    echo "Installing pooling software (MergerFS and SnapRAID)..."
    
    # Check if already installed
    MERGERFS_INSTALLED=false
    SNAPRAID_INSTALLED=false
    
    if command -v mergerfs &> /dev/null; then
        echo "MergerFS is already installed."
        MERGERFS_INSTALLED=true
    fi
    
    if command -v snapraid &> /dev/null; then
        echo "SnapRAID is already installed."
        SNAPRAID_INSTALLED=true
    fi
    
    # Update package lists
    echo "Updating package lists..."
    sudo apt-get update || {
        echo "Error: Failed to update package lists."
        exit 1
    }
    
    # Install dependencies first
    echo "Installing dependencies..."
    sudo apt-get install -y \
        fuse3 \
        attr \
        acl \
        util-linux \
        smartmontools \
        parted \
        e2fsprogs || {
        echo "Error: Failed to install dependencies."
        exit 1
    }
    
    # Install MergerFS if not already installed
    if [[ "$MERGERFS_INSTALLED" == false ]]; then
        echo "Installing MergerFS..."
        
        # Check if MergerFS is available in repositories
        if apt-cache show mergerfs &> /dev/null; then
            sudo apt-get install -y mergerfs || {
                echo "Error: Failed to install MergerFS from repositories."
                echo "Attempting to install from GitHub releases..."
                install_mergerfs_from_github
            }
        else
            echo "MergerFS not available in repositories. Installing from GitHub..."
            install_mergerfs_from_github
        fi
        
        # Verify installation
        if command -v mergerfs &> /dev/null; then
            echo "MergerFS installed successfully."
            mergerfs --version
        else
            echo "Error: MergerFS installation failed."
            exit 1
        fi
    fi
    
    # Install SnapRAID if not already installed
    if [[ "$SNAPRAID_INSTALLED" == false ]]; then
        echo "Installing SnapRAID..."
        
        # Check if SnapRAID is available in repositories
        if apt-cache show snapraid &> /dev/null; then
            sudo apt-get install -y snapraid || {
                echo "Error: Failed to install SnapRAID from repositories."
                echo "Attempting to install from source..."
                install_snapraid_from_source
            }
        else
            echo "SnapRAID not available in repositories. Installing from source..."
            install_snapraid_from_source
        fi
        
        # Verify installation
        if command -v snapraid &> /dev/null; then
            echo "SnapRAID installed successfully."
            snapraid --version
        else
            echo "Error: SnapRAID installation failed."
            exit 1
        fi
    fi
    
    # Setup systemd services for automatic startup
    setup_pooling_systemd_services
    
    echo "Pooling software installation completed successfully."
}

# Install MergerFS from GitHub releases
install_mergerfs_from_github() {
    echo "Installing MergerFS from GitHub releases..."
    
    # Detect architecture
    ARCH=$(dpkg --print-architecture)
    
    # Get latest release URL
    MERGERFS_URL=$(curl -s https://api.github.com/repos/trapexit/mergerfs/releases/latest | \
        grep "browser_download_url.*${ARCH}\.deb" | \
        cut -d '"' -f 4)
    
    if [[ -z "$MERGERFS_URL" ]]; then
        echo "Error: Could not find MergerFS package for architecture $ARCH"
        exit 1
    fi
    
    # Download and install
    TEMP_DEB="/tmp/mergerfs.deb"
    echo "Downloading MergerFS from: $MERGERFS_URL"
    curl -L -o "$TEMP_DEB" "$MERGERFS_URL" || {
        echo "Error: Failed to download MergerFS package."
        exit 1
    }
    
    sudo dpkg -i "$TEMP_DEB" || {
        echo "Fixing dependencies..."
        sudo apt-get install -f -y
    }
    
    # Clean up
    rm -f "$TEMP_DEB"
}

# Install SnapRAID from source
install_snapraid_from_source() {
    echo "Installing SnapRAID from source..."
    
    # Install build dependencies
    sudo apt-get install -y \
        build-essential \
        git \
        autoconf \
        automake \
        libtool || {
        echo "Error: Failed to install build dependencies."
        exit 1
    }
    
    # Create temporary build directory
    BUILD_DIR="/tmp/snapraid-build"
    rm -rf "$BUILD_DIR"
    mkdir -p "$BUILD_DIR"
    cd "$BUILD_DIR"
    
    # Clone and build SnapRAID
    echo "Cloning SnapRAID repository..."
    git clone https://github.com/amadvance/snapraid.git . || {
        echo "Error: Failed to clone SnapRAID repository."
        exit 1
    }
    
    echo "Building SnapRAID..."
    ./autogen.sh || {
        echo "Error: Failed to run autogen."
        exit 1
    }
    
    ./configure || {
        echo "Error: Failed to configure build."
        exit 1
    }
    
    make -j$(nproc) || {
        echo "Error: Failed to compile SnapRAID."
        exit 1
    }
    
    sudo make install || {
        echo "Error: Failed to install SnapRAID."
        exit 1
    }
    
    # Update library cache
    sudo ldconfig
    
    # Clean up
    cd /
    rm -rf "$BUILD_DIR"
    
    echo "SnapRAID built and installed from source."
}

# Setup systemd services for pooling software
setup_pooling_systemd_services() {
    echo "Setting up systemd services for pooling software..."
    
    # Create systemd service for ensuring MergerFS mounts are available before Docker
    cat > /tmp/mergerfs-mount.service <<EOF
[Unit]
Description=Ensure MergerFS mounts are ready
After=local-fs.target
Before=docker.service
Wants=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c 'for i in {1..30}; do if mountpoint -q /mnt/storage; then exit 0; fi; sleep 2; done; exit 1'
TimeoutStartSec=60

[Install]
WantedBy=multi-user.target
EOF
    
    sudo mv /tmp/mergerfs-mount.service /etc/systemd/system/
    
    # Create systemd service for Docker container health checks
    cat > /tmp/docker-storage-health.service <<EOF
[Unit]
Description=Docker Storage Health Check
After=mergerfs-mount.service docker.service
Requires=mergerfs-mount.service
Wants=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c '/usr/local/bin/check-docker-storage-health.sh'
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
EOF
    
    sudo mv /tmp/docker-storage-health.service /etc/systemd/system/
    
    # Create systemd service for SnapRAID health monitoring
    cat > /tmp/snapraid-health.service <<EOF
[Unit]
Description=SnapRAID Health Check
After=mergerfs-mount.service
Requires=mergerfs-mount.service

[Service]
Type=oneshot
ExecStart=/usr/bin/snapraid status
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    
    sudo mv /tmp/snapraid-health.service /etc/systemd/system/
    
    # Create systemd timer for periodic SnapRAID health checks
    cat > /tmp/snapraid-health.timer <<EOF
[Unit]
Description=Run SnapRAID health check daily
Requires=snapraid-health.service

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF
    
    sudo mv /tmp/snapraid-health.timer /etc/systemd/system/
    
    # Create systemd service for automatic SnapRAID sync (weekly)
    cat > /tmp/snapraid-sync.service <<EOF
[Unit]
Description=SnapRAID Sync Operation
After=mergerfs-mount.service
Requires=mergerfs-mount.service

[Service]
Type=oneshot
ExecStart=/usr/bin/snapraid sync
StandardOutput=journal
StandardError=journal
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF
    
    sudo mv /tmp/snapraid-sync.service /etc/systemd/system/
    
    # Create systemd timer for weekly SnapRAID sync
    cat > /tmp/snapraid-sync.timer <<EOF
[Unit]
Description=Run SnapRAID sync weekly
Requires=snapraid-sync.service

[Timer]
OnCalendar=weekly
Persistent=true

[Install]
WantedBy=timers.target
EOF
    
    sudo mv /tmp/snapraid-sync.timer /etc/systemd/system/
    
    # Reload systemd and enable services
    sudo systemctl daemon-reload
    
    # Enable the mount check service
    sudo systemctl enable mergerfs-mount.service
    
    # Enable health monitoring timer
    sudo systemctl enable snapraid-health.timer
    sudo systemctl start snapraid-health.timer
    
    # Enable sync timer (but don't start it yet - user should run initial sync manually)
    sudo systemctl enable snapraid-sync.timer
    
    echo "Systemd services configured successfully."
    echo "Health checks will run daily, sync will run weekly (after initial manual sync)."
}

# Generate enhanced MergerFS configuration
generate_mergerfs_config() {
    local mount_points=("$@")
    local storage_mount="/mnt/storage"
    
    if [[ ${#mount_points[@]} -eq 0 ]]; then
        echo "Error: No mount points provided for MergerFS configuration."
        return 1
    fi
    
    # Create MergerFS configuration directory
    sudo mkdir -p /etc/mergerfs
    
    # Generate configuration file
    cat > /tmp/mergerfs.conf <<EOF
# MergerFS Configuration
# Generated by Pi-PVR installer on $(date)

# Source paths (colon-separated)
MERGERFS_SOURCES=$(IFS=:; echo "${mount_points[*]}")

# Mount point
MERGERFS_MOUNT=$storage_mount

# Mount options optimized for media server use
MERGERFS_OPTIONS=defaults,allow_other,use_ino,cache.files=partial,dropcacheonclose=true,category.create=epmfs,category.search=ff,category.action=epall,func.getattr=newest,cache.statfs=true,cache.attr=true

# Policies explanation:
# - category.create=epmfs: Existing Path, Most Free Space (keeps folders together)
# - category.search=ff: First Found (fast file access)
# - category.action=epall: Existing Path, All (operations on all instances)
# - func.getattr=newest: Use newest file attributes
# - cache.statfs=true: Cache filesystem statistics
# - cache.attr=true: Cache file attributes for better performance
EOF
    
    sudo mv /tmp/mergerfs.conf /etc/mergerfs/mergerfs.conf
    echo "MergerFS configuration saved to /etc/mergerfs/mergerfs.conf"
}

# Generate enhanced SnapRAID configuration
generate_snapraid_config() {
    local data_drives=("$@")
    local parity_drive="$1"
    shift
    local mount_points=("$@")
    
    if [[ ${#mount_points[@]} -eq 0 ]]; then
        echo "Error: No data drives provided for SnapRAID configuration."
        return 1
    fi
    
    # Create SnapRAID configuration directory
    sudo mkdir -p /etc/snapraid
    sudo mkdir -p /var/snapraid
    
    # Generate configuration file
    cat > /tmp/snapraid.conf <<EOF
# SnapRAID configuration file
# Generated by Pi-PVR installer on $(date)

# Parity location
parity /mnt/parity1/snapraid.parity

# Content file locations (multiple for redundancy)
content /var/snapraid/snapraid.content
content /mnt/disk1/snapraid.content
content /mnt/parity1/snapraid.content

# Data drives
EOF
    
    # Add data drives to config
    for i in "${!mount_points[@]}"; do
        echo "data d$((i+1)) ${mount_points[$i]}" >> /tmp/snapraid.conf
    done
    
    cat >> /tmp/snapraid.conf <<EOF

# Exclusions for better performance and compatibility
exclude *.tmp
exclude *.temp
exclude *.log
exclude /lost+found/
exclude *.!sync
exclude .AppleDouble/
exclude .DS_Store
exclude .Thumbs.db
exclude .fseventsd/
exclude .Spotlight-V100/
exclude .TemporaryItems/
exclude .Trashes/
exclude *.part
exclude *.partial
exclude *.!qB
exclude *.!ut

# Docker and system exclusions
exclude /docker/
exclude /var/lib/docker/
exclude /.dockerenv
exclude /proc/
exclude /sys/
exclude /dev/

# Media server temporary files
exclude */.grab/
exclude */tmp/
exclude */temp/
exclude */cache/
exclude */logs/

# Block size (256KB is optimal for large media files)
block_size 256

# Hash size (16 bytes provides good balance of speed and reliability)
hash_size 16

# Auto-save state every 10GB processed
autosave 10

# Pool configuration for better performance
pool /mnt/storage

# Smart update (only sync changed files)
smart-update
EOF
    
    sudo mv /tmp/snapraid.conf /etc/snapraid/snapraid.conf
    echo "SnapRAID configuration saved to /etc/snapraid/snapraid.conf"
}

# Setup pooled storage with MergerFS and SnapRAID
setup_pooled_storage() {
    echo "Setting up pooled storage with redundancy..."
    
    # Detect available drives
    echo "Detecting USB drives..."
    USB_DRIVES=$(lsblk -o NAME,SIZE,TYPE,FSTYPE | awk '/part/ {print "/dev/"$1, $2, $4}' | sed 's/[└├─]//g')

    if [[ -z "$USB_DRIVES" ]]; then
        echo "No USB drives detected. Please ensure they are connected and retry."
        exit 1
    fi

    # Display available drives
    echo "Available USB drives:"
    echo "$USB_DRIVES" | nl
    
    # Count available drives
    DRIVE_COUNT=$(echo "$USB_DRIVES" | wc -l)
    
    if [[ $DRIVE_COUNT -lt 2 ]]; then
        echo "Error: Pooled storage requires at least 2 drives. Only $DRIVE_COUNT drive(s) detected."
        echo "Falling back to traditional single-drive setup..."
        choose_sharing_method
        return
    fi

    echo ""
    echo "Pooled storage configuration options:"
    echo "- Minimum 2 drives: Basic pooling without parity"
    echo "- 3+ drives: Pooling with 1 parity drive for redundancy"
    echo ""

    # Select data drives
    echo "Select drives for data storage (you can select multiple drives):"
    DATA_DRIVES=()
    SELECTED_NUMBERS=()
    
    while true; do
        echo "Available drives:"
        for i in $(seq 1 $DRIVE_COUNT); do
            if [[ ! " ${SELECTED_NUMBERS[@]} " =~ " ${i} " ]]; then
                echo "$i. $(echo "$USB_DRIVES" | sed -n "${i}p")"
            fi
        done
        
        read -r -p "Select drive number for data (or 'done' to finish): " SELECTION
        
        if [[ "$SELECTION" == "done" ]]; then
            break
        elif [[ "$SELECTION" =~ ^[0-9]+$ ]] && [[ $SELECTION -ge 1 ]] && [[ $SELECTION -le $DRIVE_COUNT ]]; then
            if [[ ! " ${SELECTED_NUMBERS[@]} " =~ " ${SELECTION} " ]]; then
                SELECTED_NUMBERS+=($SELECTION)
                DRIVE_INFO=$(echo "$USB_DRIVES" | sed -n "${SELECTION}p")
                DATA_DRIVES+=("$DRIVE_INFO")
                echo "Added: $DRIVE_INFO"
            else
                echo "Drive already selected."
            fi
        else
            echo "Invalid selection. Please enter a number between 1 and $DRIVE_COUNT, or 'done'."
        fi
        
        if [[ ${#DATA_DRIVES[@]} -ge $DRIVE_COUNT ]]; then
            echo "All drives selected for data."
            break
        fi
    done

    if [[ ${#DATA_DRIVES[@]} -eq 0 ]]; then
        echo "No data drives selected. Exiting pooled storage setup."
        exit 1
    fi

    # Select parity drive if enough drives available
    PARITY_DRIVE=""
    REMAINING_DRIVES=$((DRIVE_COUNT - ${#DATA_DRIVES[@]}))
    
    if [[ $REMAINING_DRIVES -gt 0 ]]; then
        echo ""
        echo "Select parity drive for redundancy (recommended):"
        echo "Available drives for parity:"
        
        for i in $(seq 1 $DRIVE_COUNT); do
            if [[ ! " ${SELECTED_NUMBERS[@]} " =~ " ${i} " ]]; then
                echo "$i. $(echo "$USB_DRIVES" | sed -n "${i}p")"
            fi
        done
        
        read -r -p "Select drive number for parity (or 'skip' for no parity): " PARITY_SELECTION
        
        if [[ "$PARITY_SELECTION" != "skip" ]] && [[ "$PARITY_SELECTION" =~ ^[0-9]+$ ]] && [[ $PARITY_SELECTION -ge 1 ]] && [[ $PARITY_SELECTION -le $DRIVE_COUNT ]]; then
            if [[ ! " ${SELECTED_NUMBERS[@]} " =~ " ${PARITY_SELECTION} " ]]; then
                PARITY_DRIVE=$(echo "$USB_DRIVES" | sed -n "${PARITY_SELECTION}p" | awk '{print $1}')
                echo "Selected parity drive: $PARITY_DRIVE"
            else
                echo "Drive already selected for data. Skipping parity setup."
            fi
        else
            echo "Skipping parity drive setup."
        fi
    else
        echo "No drives available for parity. Setting up basic pooling without redundancy."
    fi

    # Install required packages with enhanced error handling
    install_pooling_software

    # Setup individual drive mounts
    echo "Setting up individual drive mounts..."
    MOUNT_POINTS=()
    
    for i in "${!DATA_DRIVES[@]}"; do
        DRIVE_PATH=$(echo "${DATA_DRIVES[$i]}" | awk '{print $1}')
        DRIVE_FS=$(echo "${DATA_DRIVES[$i]}" | awk '{print $3}')
        MOUNT_POINT="/mnt/disk$((i+1))"
        
        echo "Setting up $DRIVE_PATH at $MOUNT_POINT..."
        
        # Create mount point
        sudo mkdir -p "$MOUNT_POINT"
        
        # Format drive to ext4 if it's NTFS or unformatted
        if [[ "$DRIVE_FS" == "ntfs" ]] || [[ -z "$DRIVE_FS" ]]; then
            echo "Warning: Drive $DRIVE_PATH is $DRIVE_FS. Converting to ext4 will erase all data!"
            read -r -p "Continue with formatting to ext4? (y/N): " FORMAT_CONFIRM
            
            if [[ "$FORMAT_CONFIRM" =~ ^[Yy]$ ]]; then
                echo "Formatting $DRIVE_PATH to ext4..."
                sudo mkfs.ext4 -F "$DRIVE_PATH"
            else
                echo "Skipping format. Attempting to mount as-is..."
            fi
        fi
        
        # Mount the drive
        sudo mount "$DRIVE_PATH" "$MOUNT_POINT"
        if [[ $? -ne 0 ]]; then
            echo "Error: Failed to mount $DRIVE_PATH. Please check the drive."
            exit 1
        fi
        
        # Update fstab
        update_fstab "$MOUNT_POINT" "$DRIVE_PATH"
        
        # Set permissions
        sudo chown -R "$USER:$USER" "$MOUNT_POINT"
        sudo chmod -R 775 "$MOUNT_POINT"
        
        MOUNT_POINTS+=("$MOUNT_POINT")
    done

    # Setup parity drive if selected
    if [[ -n "$PARITY_DRIVE" ]]; then
        echo "Setting up parity drive $PARITY_DRIVE..."
        PARITY_MOUNT="/mnt/parity1"
        
        sudo mkdir -p "$PARITY_MOUNT"
        
        # Format parity drive to ext4 if needed
        PARITY_FS=$(lsblk -o FSTYPE -n "$PARITY_DRIVE")
        if [[ "$PARITY_FS" == "ntfs" ]] || [[ -z "$PARITY_FS" ]]; then
            echo "Formatting parity drive to ext4..."
            sudo mkfs.ext4 -F "$PARITY_DRIVE"
        fi
        
        sudo mount "$PARITY_DRIVE" "$PARITY_MOUNT"
        update_fstab "$PARITY_MOUNT" "$PARITY_DRIVE"
        sudo chown -R "$USER:$USER" "$PARITY_MOUNT"
        sudo chmod -R 775 "$PARITY_MOUNT"
    fi

    # Setup MergerFS pool
    echo "Setting up MergerFS storage pool..."
    STORAGE_MOUNT="/mnt/storage"
    sudo mkdir -p "$STORAGE_MOUNT"
    
    # Create MergerFS mount command
    MERGERFS_SOURCES=$(IFS=:; echo "${MOUNT_POINTS[*]}")
    
    # Add to fstab for persistent mounting
    if ! grep -q "$STORAGE_MOUNT" /etc/fstab; then
        echo "Adding MergerFS pool to /etc/fstab..."
        echo "$MERGERFS_SOURCES $STORAGE_MOUNT fuse.mergerfs defaults,allow_other,use_ino,cache.files=partial,dropcacheonclose=true,category.create=epmfs,category.search=ff,category.action=epall 0 0" | sudo tee -a /etc/fstab
    fi
    
    # Mount the pool
    sudo mount "$STORAGE_MOUNT"
    if [[ $? -ne 0 ]]; then
        echo "Error: Failed to mount MergerFS pool."
        exit 1
    fi

    # Create media directories
    echo "Creating media directories..."
    MOVIES_DIR="$STORAGE_MOUNT/Movies"
    TVSHOWS_DIR="$STORAGE_MOUNT/TVShows"
    DOWNLOADS_DIR="$STORAGE_MOUNT/downloads"
    
    sudo mkdir -p "$MOVIES_DIR" "$TVSHOWS_DIR" "$DOWNLOADS_DIR"
    sudo chown -R "$USER:$USER" "$STORAGE_MOUNT"
    sudo chmod -R 775 "$STORAGE_MOUNT"

    # Generate enhanced MergerFS configuration
    generate_mergerfs_config "${MOUNT_POINTS[@]}"
    
    # Setup SnapRAID configuration if parity drive is available
    if [[ -n "$PARITY_DRIVE" ]]; then
        echo "Setting up enhanced SnapRAID configuration..."
        generate_snapraid_config "$PARITY_DRIVE" "${MOUNT_POINTS[@]}"
        echo "SnapRAID configuration created at /etc/snapraid/snapraid.conf"
        echo "Run 'sudo snapraid sync' to create initial parity after adding data."
    fi

    # Setup file sharing
    echo "Setting up file sharing for pooled storage..."
    choose_sharing_method

    echo ""
    echo "Pooled storage setup complete!"
    echo "Storage pool mounted at: $STORAGE_MOUNT"
    echo "Data drives: ${#DATA_DRIVES[@]}"
    if [[ -n "$PARITY_DRIVE" ]]; then
        echo "Parity drive: $PARITY_DRIVE"
        echo "Run 'sudo snapraid sync' to create initial parity protection."
    else
        echo "No parity protection configured."
    fi
    
    # Configure Docker integration for pooled storage
    configure_docker_pooled_storage
    
    # Mark success
    sed -i 's/SHARE_SETUP_SUCCESS=0/SHARE_SETUP_SUCCESS=1/' "$ENV_FILE"
}

# Configure Docker integration for pooled storage
configure_docker_pooled_storage() {
    echo "Configuring Docker integration for pooled storage..."
    
    # Install the storage health check script
    echo "Installing Docker storage health check script..."
    local script_dir="$(dirname "${BASH_SOURCE[0]}")"
    if [[ -f "$script_dir/check-docker-storage-health.sh" ]]; then
        sudo cp "$script_dir/check-docker-storage-health.sh" /usr/local/bin/
        sudo chmod +x /usr/local/bin/check-docker-storage-health.sh
        echo "Docker storage health check script installed from $script_dir"
    elif [[ -f "check-docker-storage-health.sh" ]]; then
        sudo cp check-docker-storage-health.sh /usr/local/bin/
        sudo chmod +x /usr/local/bin/check-docker-storage-health.sh
        echo "Docker storage health check script installed from current directory"
    else
        echo "Warning: check-docker-storage-health.sh not found, creating basic health check script..."
        create_docker_health_check_script
    fi
    
    # Update .env file with pooled storage paths
    update_env_for_pooled_storage
    
    # Create Docker Compose override for pooled storage
    create_docker_compose_override
    
    # Setup Docker service dependencies
    setup_docker_service_dependencies
    
    echo "Docker integration for pooled storage configured successfully."
}

# Create Docker health check script if not present
create_docker_health_check_script() {
    cat > /tmp/check-docker-storage-health.sh <<'EOF'
#!/bin/bash

# Docker Storage Health Check Script
# This script verifies that pooled storage is accessible before Docker containers start

set -euo pipefail

# Configuration
STORAGE_MOUNT="/mnt/storage"
REQUIRED_DIRS=("Movies" "TVShows" "downloads")
TIMEOUT=60
CHECK_INTERVAL=2

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >&2
}

# Check if MergerFS mount is available
check_mergerfs_mount() {
    if ! mountpoint -q "$STORAGE_MOUNT"; then
        log "ERROR: MergerFS mount $STORAGE_MOUNT is not available"
        return 1
    fi
    
    log "INFO: MergerFS mount $STORAGE_MOUNT is available"
    return 0
}

# Check if required directories exist and are writable
check_required_directories() {
    for dir in "${REQUIRED_DIRS[@]}"; do
        local full_path="$STORAGE_MOUNT/$dir"
        
        if [[ ! -d "$full_path" ]]; then
            log "ERROR: Required directory $full_path does not exist"
            return 1
        fi
        
        if [[ ! -w "$full_path" ]]; then
            log "ERROR: Required directory $full_path is not writable"
            return 1
        fi
        
        log "INFO: Directory $full_path is accessible and writable"
    done
    
    return 0
}

# Wait for storage to become available
wait_for_storage() {
    local elapsed=0
    
    log "INFO: Waiting for storage to become available (timeout: ${TIMEOUT}s)"
    
    while [[ $elapsed -lt $TIMEOUT ]]; do
        if check_mergerfs_mount; then
            log "INFO: Storage became available after ${elapsed}s"
            return 0
        fi
        
        sleep $CHECK_INTERVAL
        elapsed=$((elapsed + CHECK_INTERVAL))
    done
    
    log "ERROR: Storage did not become available within ${TIMEOUT}s"
    return 1
}

# Main health check function
main() {
    log "INFO: Starting Docker storage health check"
    
    # Wait for storage to be available
    if ! wait_for_storage; then
        log "ERROR: Storage availability check failed"
        exit 1
    fi
    
    # Check required directories
    if ! check_required_directories; then
        log "ERROR: Required directories check failed"
        exit 1
    fi
    
    log "INFO: Docker storage health check completed successfully"
    exit 0
}

# Run main function
main "$@"
EOF
    
    sudo mv /tmp/check-docker-storage-health.sh /usr/local/bin/
    sudo chmod +x /usr/local/bin/check-docker-storage-health.sh
    echo "Docker health check script created at /usr/local/bin/check-docker-storage-health.sh"
}

# Update .env file for pooled storage configuration
update_env_for_pooled_storage() {
    echo "Updating .env file for pooled storage..."
    
    # Source current .env to preserve existing values
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi
    
    # Update storage-related variables for pooled storage
    sed -i 's|^STORAGE_MOUNT=.*|STORAGE_MOUNT="/mnt/storage"|' "$ENV_FILE"
    sed -i 's|^DOWNLOADS=.*|DOWNLOADS="/mnt/storage/downloads"|' "$ENV_FILE"
    
    # Add pooled storage specific variables if not present
    if ! grep -q "POOLED_STORAGE_ENABLED" "$ENV_FILE"; then
        cat >> "$ENV_FILE" <<EOF

# Pooled Storage Configuration
POOLED_STORAGE_ENABLED=true
MERGERFS_MOUNT="/mnt/storage"
SNAPRAID_CONFIG="/etc/snapraid/snapraid.conf"
DOCKER_STORAGE_HEALTH_CHECK=true
EOF
    fi
    
    echo "Environment file updated for pooled storage."
}

# Create Docker Compose override for enhanced pooled storage support
create_docker_compose_override() {
    echo "Creating Docker Compose override for pooled storage..."
    
    local override_file="$DOCKER_DIR/docker-compose.override.yml"
    
    cat > "$override_file" <<EOF
# Docker Compose Override for Pooled Storage
# This file provides enhanced configuration for pooled storage integration

version: "3.8"

services:
  # Add storage health check dependency to VPN container (which other containers depend on)
  \${VPN_CONTAINER}:
    depends_on:
      - storage-health-check
    healthcheck:
      test: ["CMD-SHELL", "curl --fail http://localhost:8000 && mountpoint -q /mnt/storage"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  # Storage health check service
  storage-health-check:
    image: alpine:latest
    container_name: storage-health-check
    command: >
      sh -c "
        apk add --no-cache util-linux &&
        while true; do
          if mountpoint -q /mnt/storage && [ -d /mnt/storage/Movies ] && [ -d /mnt/storage/TVShows ] && [ -d /mnt/storage/downloads ]; then
            echo 'Storage health check passed'
            sleep 30
          else
            echo 'Storage health check failed'
            exit 1
          fi
        done
      "
    volumes:
      - /mnt/storage:/mnt/storage:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "mountpoint -q /mnt/storage"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Enhanced Jellyfin configuration for pooled storage
  \${JELLYFIN_CONTAINER}:
    depends_on:
      storage-health-check:
        condition: service_healthy
    volumes:
      - \${DOCKER_DIR}/\${JELLYFIN_CONTAINER}:/config
      - \${STORAGE_MOUNT}:/media:ro
      - \${STORAGE_MOUNT}/Movies:/movies:ro
      - \${STORAGE_MOUNT}/TVShows:/tv:ro
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:\${MEDIASERVER_HTTP}/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  # Enhanced Pi Health Dashboard for pooled storage monitoring
  pi-health-dashboard:
    depends_on:
      storage-health-check:
        condition: service_healthy
    environment:
      - TZ=\${TIMEZONE}
      - DISK_PATH=/mnt/storage
      - DISK_PATH_2=/mnt/downloads
      - DOCKER_COMPOSE_PATH=/config/docker-compose.yml
      - ENV_FILE_PATH=/config/.env
      - BACKUP_DIR=/config/backups
      - POOLED_STORAGE_ENABLED=true
      - MERGERFS_MOUNT=/mnt/storage
      - SNAPRAID_CONFIG=/etc/snapraid/snapraid.conf
    volumes:
      - /proc:/host_proc:ro
      - /sys:/host_sys:ro
      - /var/run/docker.sock:/var/run/docker.sock
      - \${DOCKER_DIR}/:/config
      - /mnt/storage:/mnt/storage:ro
      - /mnt/disk1:/mnt/disk1:ro
      - /mnt/disk2:/mnt/disk2:ro
      - /mnt/disk3:/mnt/disk3:ro
      - /mnt/disk4:/mnt/disk4:ro
      - /mnt/disk5:/mnt/disk5:ro
      - /mnt/parity1:/mnt/parity1:ro
      - /etc/snapraid:/etc/snapraid:ro
      - /etc/mergerfs:/etc/mergerfs:ro
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
EOF
    
    echo "Docker Compose override created at $override_file"
}

# Setup Docker service dependencies for pooled storage
setup_docker_service_dependencies() {
    echo "Setting up Docker service dependencies for pooled storage..."
    
    # Create systemd drop-in directory for Docker service
    sudo mkdir -p /etc/systemd/system/docker.service.d
    
    # Create override configuration for Docker service
    cat > /tmp/10-storage-dependency.conf <<EOF
[Unit]
# Ensure Docker waits for storage to be available
After=mergerfs-mount.service docker-storage-health.service
Wants=mergerfs-mount.service docker-storage-health.service

[Service]
# Add pre-start health check
ExecStartPre=/usr/local/bin/check-docker-storage-health.sh
EOF
    
    sudo mv /tmp/10-storage-dependency.conf /etc/systemd/system/docker.service.d/
    
    # Enable the Docker storage health service
    sudo systemctl enable docker-storage-health.service
    
    # Reload systemd configuration
    sudo systemctl daemon-reload
    
    echo "Docker service dependencies configured for pooled storage."
    echo "Docker will now wait for storage to be available before starting containers."
}

# Configure USB drive and Samba share
setup_usb_and_samba() {
    echo "Detecting USB drives..."

    # List available partitions
    USB_DRIVES=$(lsblk -o NAME,SIZE,TYPE,FSTYPE | awk '/part/ {print "/dev/"$1, $2, $4}' | sed 's/[└├─]//g')

    if [[ -z "$USB_DRIVES" ]]; then
        echo "No USB drives detected. Please ensure they are connected and retry."
        exit 1
    fi

    # Display USB drives and prompt for storage drive
    echo "Available USB drives:"
    echo "$USB_DRIVES" | nl
    read -r -p "Select the drive number for storage (TV Shows and Movies): " STORAGE_SELECTION
    STORAGE_DRIVE=$(echo "$USB_DRIVES" | sed -n "${STORAGE_SELECTION}p" | awk '{print $1}')
    STORAGE_FS=$(echo "$USB_DRIVES" | sed -n "${STORAGE_SELECTION}p" | awk '{print $3}')
    
    # Define storage mount point before case
    STORAGE_MOUNT="/mnt/storage"

    # Option for downloads directory
    echo "Do you want to:"
    echo "1. Use the same drive for downloads."
    echo "2. Use a different USB drive for downloads."
    echo "3. Explicitly specify a path for downloads (e.g., internal storage)."
    read -r -p "Enter your choice (1/2/3): " DOWNLOAD_CHOICE

case "$DOWNLOAD_CHOICE" in
    1)
        DOWNLOAD_DRIVE=$STORAGE_DRIVE
        DOWNLOAD_FS=$STORAGE_FS
        DOWNLOAD_MOUNT="$STORAGE_MOUNT/downloads"  # Explicitly set the downloads mount path
        ;;
    2)
        echo "Available USB drives:"
        echo "$USB_DRIVES" | nl
        read -r -p "Select the drive number for downloads: " DOWNLOAD_SELECTION
        DOWNLOAD_DRIVE=$(echo "$USB_DRIVES" | sed -n "${DOWNLOAD_SELECTION}p" | awk '{print $1}')
        DOWNLOAD_FS=$(echo "$USB_DRIVES" | sed -n "${DOWNLOAD_SELECTION}p" | awk '{print $3}')
        DOWNLOAD_MOUNT="/mnt/downloads"  # Default path for a different drive
        ;;
    3)
        read -r -p "Enter the explicit path for downloads (e.g., /home/username/Downloads): " DOWNLOAD_MOUNT
        ;;
    *)
        echo "Invalid choice. Defaulting to the same drive for downloads."
        DOWNLOAD_DRIVE=$STORAGE_DRIVE
        DOWNLOAD_FS=$STORAGE_FS
        DOWNLOAD_MOUNT="$STORAGE_MOUNT/downloads"  # Default path if invalid input
        ;;
esac

    # Define mount points
    STORAGE_MOUNT="/mnt/storage"
    if [[ -z "$DOWNLOAD_MOUNT" ]]; then
        DOWNLOAD_MOUNT="/mnt/downloads"
    fi

    # Mount storage drive
    echo "Mounting $STORAGE_DRIVE to $STORAGE_MOUNT..."
    sudo mkdir -p "$STORAGE_MOUNT"
    if [[ "$STORAGE_FS" == "ntfs" ]]; then
        sudo mount -t ntfs-3g "$STORAGE_DRIVE" "$STORAGE_MOUNT"
    else
        sudo mount "$STORAGE_DRIVE" "$STORAGE_MOUNT"
    fi
    if [[ $? -ne 0 ]]; then
        echo "Error: Failed to mount $STORAGE_DRIVE. Please check the drive and try again."
        exit 1
    fi

    # Update fstab for storage drive
    update_fstab "$STORAGE_MOUNT" "$STORAGE_DRIVE"

    # Mount download drive or validate path
    if [[ "$DOWNLOAD_CHOICE" == "2" ]]; then
        echo "Mounting $DOWNLOAD_DRIVE to $DOWNLOAD_MOUNT..."
        sudo mkdir -p "$DOWNLOAD_MOUNT"
        if [[ "$DOWNLOAD_FS" == "ntfs" ]]; then
            sudo mount -t ntfs-3g "$DOWNLOAD_DRIVE" "$DOWNLOAD_MOUNT"
        else
            sudo mount "$DOWNLOAD_DRIVE" "$DOWNLOAD_MOUNT"
        fi
        if [[ $? -ne 0 ]]; then
            echo "Error: Failed to mount $DOWNLOAD_DRIVE. Please check the drive and try again."
            exit 1
        fi
        update_fstab "$DOWNLOAD_MOUNT" "$DOWNLOAD_DRIVE"
    else
        # Verify the explicit path exists
        sudo mkdir -p "$DOWNLOAD_MOUNT"
    fi

    # Detect and create media directories
    MOVIES_DIR="$STORAGE_MOUNT/Movies"
    TVSHOWS_DIR="$STORAGE_MOUNT/TVShows"

    for DIR in "$MOVIES_DIR" "$TVSHOWS_DIR"; do
        if [[ ! -d "$DIR" ]]; then
            echo "Creating directory $DIR..."
            sudo mkdir -p "$DIR"
        fi
    done

    # Set permissions for storage and downloads
    echo "Setting permissions..."
    sudo chmod -R 775 "$STORAGE_MOUNT" "$DOWNLOAD_MOUNT"
    sudo chown -R "$USER:$USER" "$STORAGE_MOUNT" "$DOWNLOAD_MOUNT"

    # Install Samba and configure shares
    echo "Configuring Samba..."
    if ! command -v smbd &> /dev/null; then
        sudo apt-get install -y samba samba-common-bin
    fi

    # Add shares
    if ! grep -q "\[Downloads\]" "$SAMBA_CONFIG"; then
        sudo bash -c "cat >> $SAMBA_CONFIG" <<EOF

[Movies]
   path = $MOVIES_DIR
   browseable = yes
   read only = no
   guest ok = yes

[TVShows]
   path = $TVSHOWS_DIR
   browseable = yes
   read only = no
   guest ok = yes

[Downloads]
   path = $DOWNLOAD_MOUNT
   browseable = yes
   read only = no
   guest ok = yes
EOF
        sudo systemctl restart smbd
    fi

    echo "Configuration complete."
    echo "Storage Drive Mounted: $STORAGE_MOUNT"
    echo "Download Location: $DOWNLOAD_MOUNT"
    echo "Samba Shares:"
    printf '  \\\\%s\\Movies\n' "$SERVER_IP"
    printf '  \\\\%s\\TVShows\n' "$SERVER_IP"
    printf '  \\\\%s\\Downloads\n' "$SERVER_IP"

    # Mark success
    sed -i 's/SHARE_SETUP_SUCCESS=0/SHARE_SETUP_SUCCESS=1/' "$ENV_FILE"
}


setup_usb_and_nfs() {
    echo "Installing necessary NFS packages..."
    sudo apt-get install -y nfs-kernel-server

    echo "Detecting USB drives..."
    USB_DRIVES=$(lsblk -o NAME,SIZE,TYPE,FSTYPE | awk '/part/ {print "/dev/"$1, $2, $4}' | sed 's/[└├─]//g')

    if [[ -z "$USB_DRIVES" ]]; then
        echo "No USB drives detected. Please ensure they are connected and retry."
        exit 1
    fi

    echo "Available USB drives:"
    echo "$USB_DRIVES" | nl
    read -r -p "Select the drive number for storage: " STORAGE_SELECTION
    STORAGE_DRIVE=$(echo "$USB_DRIVES" | sed -n "${STORAGE_SELECTION}p" | awk '{print $1}')
    STORAGE_FS=$(echo "$USB_DRIVES" | sed -n "${STORAGE_SELECTION}p" | awk '{print $3}')

    read -r -p "Do you want to use the same drive for downloads? (y/n): " SAME_DRIVE
    if [[ "$SAME_DRIVE" =~ ^[Yy]$ ]]; then
        DOWNLOAD_DRIVE=$STORAGE_DRIVE
        DOWNLOAD_FS=$STORAGE_FS
    else
        echo "Available USB drives:"
        echo "$USB_DRIVES" | nl
        read -r -p "Select the drive number for downloads: " DOWNLOAD_SELECTION
        DOWNLOAD_DRIVE=$(echo "$USB_DRIVES" | sed -n "${DOWNLOAD_SELECTION}p" | awk '{print $1}')
        DOWNLOAD_FS=$(echo "$USB_DRIVES" | sed -n "${DOWNLOAD_SELECTION}p" | awk '{print $3}')
    fi

    # Define mount points
    STORAGE_MOUNT="/mnt/storage"
    DOWNLOAD_MOUNT="/mnt/downloads"

    # Mount storage drive
    echo "Mounting $STORAGE_DRIVE to $STORAGE_MOUNT..."
    sudo mkdir -p "$STORAGE_MOUNT"
    if [[ "$STORAGE_FS" == "ntfs" ]]; then
        sudo mount -t ntfs-3g "$STORAGE_DRIVE" "$STORAGE_MOUNT"
    else
        sudo mount "$STORAGE_DRIVE" "$STORAGE_MOUNT"
    fi
    if [[ $? -ne 0 ]]; then
        echo "Error: Failed to mount $STORAGE_DRIVE. Please check the drive and try again."
        exit 1
    fi

    # Update fstab for storage drive
    update_fstab "$STORAGE_MOUNT" "$STORAGE_DRIVE"

    # Mount download drive if different
    if [[ "$SAME_DRIVE" =~ ^[Nn]$ ]]; then
        echo "Mounting $DOWNLOAD_DRIVE to $DOWNLOAD_MOUNT..."
        sudo mkdir -p "$DOWNLOAD_MOUNT"
        if [[ "$DOWNLOAD_FS" == "ntfs" ]]; then
            sudo mount -t ntfs-3g "$DOWNLOAD_DRIVE" "$DOWNLOAD_MOUNT"
        else
            sudo mount "$DOWNLOAD_DRIVE" "$DOWNLOAD_MOUNT"
        fi
        if [[ $? -ne 0 ]]; then
            echo "Error: Failed to mount $DOWNLOAD_DRIVE. Please check the drive and try again."
            exit 1
        fi

        # Update fstab for download drive
        update_fstab "$DOWNLOAD_MOUNT" "$DOWNLOAD_DRIVE"
    fi

    # Detect and create media directories
    MOVIES_DIR="$STORAGE_MOUNT/Movies"
    TVSHOWS_DIR="$STORAGE_MOUNT/TVShows"

    if [[ ! -d "$MOVIES_DIR" ]]; then
        read -r -p "Movies directory not found. Do you want to create it? (y/n): " CREATE_MOVIES
        if [[ "$CREATE_MOVIES" =~ ^[Yy]$ ]]; then
            echo "Creating Movies directory..."
            sudo mkdir -p "$MOVIES_DIR"
        else
            echo "Skipping Movies directory creation."
        fi
    fi

    if [[ ! -d "$TVSHOWS_DIR" ]]; then
        read -r -p "TVShows directory not found. Do you want to create it? (y/n): " CREATE_TVSHOWS
        if [[ "$CREATE_TVSHOWS" =~ ^[Yy]$ ]]; then
            echo "Creating TVShows directory..."
            sudo mkdir -p "$TVSHOWS_DIR"
        else
            echo "Skipping TVShows directory creation."
        fi
    fi

    # Update /etc/exports for NFS
    EXPORTS_FILE="/etc/exports"
    echo "Setting up NFS share..."

    # Add storage directory if not already in exports
    if ! grep -q "$STORAGE_MOUNT" "$EXPORTS_FILE"; then
        echo "$STORAGE_MOUNT *(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a "$EXPORTS_FILE"
    else
        echo "NFS export for $STORAGE_MOUNT already exists. Skipping."
    fi

    # Add download directory if not already in exports
    if ! grep -q "$DOWNLOAD_MOUNT" "$EXPORTS_FILE"; then
        echo "$DOWNLOAD_MOUNT *(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a "$EXPORTS_FILE"
    else
        echo "NFS export for $DOWNLOAD_MOUNT already exists. Skipping."
    fi

    echo "Exporting directories for NFS..."
    sudo exportfs -ra

    echo "Restarting NFS server..."
    sudo systemctl restart nfs-kernel-server

    SERVER_IP=$(hostname -I | awk '{print $1}')
    echo "Configuration complete."
    echo "NFS Shares available at:"
    echo "  $SERVER_IP:$STORAGE_MOUNT"
    echo "  $SERVER_IP:$DOWNLOAD_MOUNT"

    # Mark success
    sed -i 's/SHARE_SETUP_SUCCESS=0/SHARE_SETUP_SUCCESS=1/' "$ENV_FILE"
}


# Create Docker Compose file
create_docker_compose() {
    if [[ "$docker_compose_success" == "1" ]]; then
        echo "Docker Compose stack is already deployed. Skipping."
        return
    fi    
    
    echo "Creating Docker Compose file..."
    cat > "$DOCKER_DIR/docker-compose.yml" <<EOF
version: "3.8"
services:
  ${VPN_CONTAINER}:
    image: ${VPN_IMAGE}:${IMAGE_RELEASE}
    container_name: ${VPN_CONTAINER}
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun:/dev/net/tun
    volumes:
      - "${DOCKER_DIR}/${VPN_CONTAINER}:/gluetun"
    env_file:
      - ${DOCKER_DIR}/${VPN_CONTAINER}/.env
    healthcheck:
      test: curl --fail http://localhost:8000 || exit 1
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    ports:
      - ${JACKET_PORT}:${JACKET_PORT}
      - ${SONARR_PORT}:${SONARR_PORT}
      - ${RADARR_PORT}:${RADARR_PORT}
      - ${TRANSMISSION_PORT}:${TRANSMISSION_PORT}
      - ${NZBGET}:${NZBGET}
    networks:
      - ${CONTAINER_NETWORK}

  ${JACKETT_CONTAINER}:
    image: ${JACKETT_IMAGE}:${IMAGE_RELEASE}
    container_name: ${JACKETT_CONTAINER}
    network_mode: "service:${VPN_CONTAINER}"
    environment:
      - TZ=${TIMEZONE}
      - PUID=${PUID}
      - PGID=${PGID}
    volumes:
      - ${DOCKER_DIR}/${JACKETT_CONTAINER}:/config
      - ${DOWNLOADS}:/downloads
    restart: unless-stopped

  ${SONARR_CONTAINER}:
    image: ${SONARR_IMAGE}:${IMAGE_RELEASE}
    container_name: ${SONARR_CONTAINER}
    network_mode: "service:${VPN_CONTAINER}"
    environment:
      - TZ=${TIMEZONE}
      - PUID=${PUID}
      - PGID=${PGID}
    volumes:
      - ${DOCKER_DIR}/${SONARR_CONTAINER}:/config
      - ${STORAGE_MOUNT}/${TVSHOWS_FOLDER}:/tv
      - ${DOWNLOADS}:/downloads
    restart: unless-stopped

  ${RADARR_CONTAINER}:
    image: ${RADARR_IMAGE}:${IMAGE_RELEASE}
    container_name: ${RADARR_CONTAINER}
    network_mode: "service:${VPN_CONTAINER}"
    environment:
      - TZ=${TIMEZONE}
      - PUID=${PUID}
      - PGID=${PGID}
    volumes:
      - ${DOCKER_DIR}/${RADARR_CONTAINER}:/config
      - ${STORAGE_MOUNT}/${MOVIES_FOLDER}:/movies
      - ${DOWNLOADS}:/downloads
    restart: unless-stopped

  ${TRANSMISSION_CONTAINER}:
    image: ${TRANSMISSION_IMAGE}:${IMAGE_RELEASE}
    container_name: ${TRANSMISSION_CONTAINER}
    network_mode: "service:${VPN_CONTAINER}"
    environment:
      - TZ=${TIMEZONE}
      - PUID=${PUID}
      - PGID=${PGID}
    volumes:
      - ${DOCKER_DIR}/${TRANSMISSION_CONTAINER}:/config
      - ${DOWNLOADS}:/downloads
    restart: unless-stopped

  ${NZBGET_CONTAINER}:
    image: ${NZBGET_IMAGE}:${IMAGE_RELEASE}
    container_name: ${NZBGET_CONTAINER}
    network_mode: "service:${VPN_CONTAINER}"
    environment:
      - TZ=${TIMEZONE}
      - PUID=${PUID}
      - PGID=${PGID}
    volumes:
      - ${DOCKER_DIR}/${NZBGET_CONTAINER}:/config
      - ${DOWNLOADS}/incomplete:/incomplete
      - ${DOWNLOADS}/complete:/complete
    restart: unless-stopped

  ${GET_IPLAYER}:
    image: ${GET_IPLAYER_IMAGE}:${IMAGE_RELEASE}
    container_name: ${GET_IPLAYER}
    network_mode: bridge
    environment:
      - TZ=${TIMEZONE}
      - PUID=${PUID}
      - PGID=${PGID}
      - INCLUDERADIO=${INCLUDERADIO}
      - ENABLEIMPORT=${ENABLEIMPORT}
    volumes:
      - ${DOCKER_DIR}/${GET_IPLAYER}/config:/config
      - ${DOWNLOADS}/complete:/downloads
    ports:
      - ${GET_IPLAYER_PORT}:${GET_IPLAYER_PORT}
    restart: unless-stopped

  ${JELLYFIN_CONTAINER}:
    image: ${JELLYFIN_IMAGE}:${IMAGE_RELEASE}
    container_name: ${JELLYFIN_CONTAINER}
    network_mode: bridge
    environment:
      - TZ=${TIMEZONE}
      - PUID=${PUID}
      - PGID=${PGID}
    volumes:
      - ${DOCKER_DIR}/${JELLYFIN_CONTAINER}:/config
      - ${STORAGE_MOUNT}:/media
    ports:
      - ${MEDIASERVER_HTTP}:${MEDIASERVER_HTTP}
      - ${MEDIASERVER_HTTPS}:${MEDIASERVER_HTTPS}
    restart: unless-stopped

  ${WATCHTOWER_CONTAINER}:
    image: ${WATCHTOWER_IMAGE}:${IMAGE_RELEASE}
    container_name: ${WATCHTOWER_CONTAINER}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - WATCHTOWER_CLEANUP=true
      - WATCHTOWER_POLL_INTERVAL=3600
    restart: unless-stopped

networks:
  ${CONTAINER_NETWORK}:
    driver: bridge

EOF
    echo "Docker Compose file created at $DOCKER_DIR/docker-compose.yml"
    echo "Docker Compose stack deployed successfully."
    sed -i 's/docker_compose_success=0/docker_compose_success=1/' "$ENV_FILE"
}



# Install required dependencies
install_dependencies() {
    if [[ "$INSTALL_DEPENDANCIES_SUCCESS" == "1" ]]; then
        echo "Docker Compose stack is already deployed. Skipping."
        return
    fi

    # Install required dependencies, including git
    echo "Installing dependencies..."
    sudo apt update
    sudo apt install -y curl jq git

    echo "Uninstalling any conflicting Docker packages..."
    for pkg in docker.io docker-doc docker-compose podman-docker containerd runc; do
        sudo apt-get remove -y "$pkg"
    done

    echo "Adding Docker's official GPG key and repository for Docker..."
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update

    echo "Installing Docker Engine, Docker Compose, and related packages..."
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    echo "Installing other required dependencies: curl, jq, git..."
    sudo apt-get install -y curl jq git

    echo "Verifying Docker installation..."
    sudo docker run hello-world

    echo "All dependencies installed successfully."

    sed -i 's/INSTALL_DEPENDANCIES_SUCCESS=0/INSTALL_DEPENDANCIES_SUCCESS=1/' "$ENV_FILE"
}


# Set up Docker network for VPN containers
setup_docker_network() {
    if [[ "$DOCKER_NETWORK_SUCCESS" == "1" ]]; then
        echo "Docker Network is already deployed. Skipping."
        return
    fi
    echo "Creating Docker network for VPN..."
    if ! systemctl is-active --quiet docker; then
        echo "Docker is not running. Starting Docker..."
        sudo systemctl start docker
    fi

    if sudo docker network ls | grep -q "$CONTAINER_NETWORK"; then
        echo "Docker network '$CONTAINER_NETWORK' already exists."
    else
        sudo docker network create "$CONTAINER_NETWORK"
        echo "Docker network '$CONTAINER_NETWORK' created."
        sed -i 's/DOCKER_NETWORK_SUCCESS=0/DOCKER_NETWORK_SUCCESS=1/' "$ENV_FILE"
    fi
}


# Deploy Docker Compose stack
deploy_docker_compose() {
    echo "Deploying Docker Compose stack..."
    
    # Check Docker group membership
    if ! groups "$USER" | grep -q "docker"; then
        echo "User '$USER' is not yet in the 'docker' group. Adding to group..."
        sudo usermod -aG docker "$USER"
        echo "User '$USER' has been added to the 'docker' group."
        echo "Please log out and log back in, then restart this script."
        exit 1
    fi

    # Attempt to deploy Docker Compose stack
    if ! docker compose --env-file "$ENV_FILE" -f "$DOCKER_DIR/docker-compose.yml" up -d; then
        echo "Error: Failed to deploy Docker Compose stack."
        echo "This is likely due to recent changes to Docker permissions."
        echo "Please log out and log back in to refresh your user session, then restart this script."
        exit 1
    fi

    echo "Docker Compose stack deployed successfully."
}


setup_mount_and_docker_start() {
    echo "Configuring drives to mount at boot and Docker to start afterwards..."

    # Variables for mount points and device paths
    STORAGE_MOUNT="/mnt/storage"
    DOWNLOAD_MOUNT="/mnt/downloads"

    # Get device UUIDs for fstab
    STORAGE_UUID=$(blkid -s UUID -o value "$(findmnt -nT "$STORAGE_MOUNT" | awk '{print $2}')")
    DOWNLOAD_UUID=$(blkid -s UUID -o value "$(findmnt -nT "$DOWNLOAD_MOUNT" | awk '{print $2}')")

    if [[ -z "$STORAGE_UUID" || -z "$DOWNLOAD_UUID" ]]; then
        echo "Error: Could not determine UUIDs for storage or download drives."
        exit 1
    fi

    # Update /etc/fstab for persistent mount
    echo "Updating /etc/fstab..."
    sudo bash -c "cat >> /etc/fstab" <<EOF
UUID=$STORAGE_UUID $STORAGE_MOUNT ext4 defaults 0 2
UUID=$DOWNLOAD_UUID $DOWNLOAD_MOUNT ext4 defaults 0 2
EOF

    # Test the fstab changes
    sudo mount -a
    if [[ $? -ne 0 ]]; then
        echo "Error: Failed to mount drives. Please check /etc/fstab."
        exit 1
    fi

    echo "Drives are configured to mount at boot."

    # Create systemd service for Docker start
    echo "Creating systemd service to start Docker containers after mounts..."
    sudo bash -c "cat > /etc/systemd/system/docker-compose-start.service" <<EOF
[Unit]
Description=Ensure drives are mounted and start Docker containers
Requires=local-fs.target
After=local-fs.target docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/check_mount_and_start.sh
RemainAfterExit=yes
Environment=HOME=$HOME

[Install]
WantedBy=multi-user.target
EOF

    # Create the script to check mounts and start Docker
    sudo bash -c "cat > /usr/local/bin/check_mount_and_start.sh" <<'EOF'
#!/bin/bash

STORAGE_MOUNT="/mnt/storage"
DOWNLOAD_MOUNT="/mnt/downloads"
DOCKER_COMPOSE_FILE="$HOME/docker/docker-compose.yml"

# Wait until mounts are ready
until mountpoint -q "$STORAGE_MOUNT" && mountpoint -q "$DOWNLOAD_MOUNT"; do
    echo "Waiting for drives to be mounted..."
    sleep 5
done

echo "Drives are mounted. Starting Docker containers..."
docker compose -f "$DOCKER_COMPOSE_FILE" up -d
EOF

    # Make the script executable
    sudo chmod +x /usr/local/bin/check_mount_and_start.sh

    # Enable and start the systemd service
    sudo systemctl enable docker-compose-start.service
    sudo systemctl start docker-compose-start.service

    echo "Configuration complete. Docker containers will start after drives are mounted on reboot."
}


# Function to pull the latest docker-compose.yml
update_compose_file() {
    echo "Checking for updates to docker-compose.yml..."
    TEMP_COMPOSE_FILE=$(mktemp)

    # URL for your GitHub-hosted docker-compose.yml
    DOCKER_COMPOSE_URL="${DOCKER_COMPOSE_URL}"

    # Download the latest docker-compose.yml from GitHub
    curl -fsSL "$DOCKER_COMPOSE_URL" -o "$TEMP_COMPOSE_FILE"

    if [[ $? -ne 0 ]]; then
        echo "Error: Failed to fetch the latest docker-compose.yml from GitHub."
        rm -f "$TEMP_COMPOSE_FILE"
        exit 1
    fi

    # Compare checksums of the current and new files
    LOCAL_COMPOSE_FILE="$DOCKER_DIR/docker-compose.yml"
    LOCAL_CHECKSUM=$(md5sum "$LOCAL_COMPOSE_FILE" 2>/dev/null | awk '{print $1}')
    REMOTE_CHECKSUM=$(md5sum "$TEMP_COMPOSE_FILE" | awk '{print $1}')

    if [[ "$LOCAL_CHECKSUM" == "$REMOTE_CHECKSUM" ]]; then
        echo "No updates found for docker-compose.yml."
        rm -f "$TEMP_COMPOSE_FILE"
    else
        echo "Update found. Applying changes..."
        mv "$TEMP_COMPOSE_FILE" "$LOCAL_COMPOSE_FILE"
        echo "Redeploying Docker stack..."
        docker compose -f "$LOCAL_COMPOSE_FILE" pull
        docker compose -f "$LOCAL_COMPOSE_FILE" up -d
        echo "Docker stack updated successfully."
    fi
}




# Main setup function
main() {
    # Parse command-line arguments
    for arg in "$@"; do
        case $arg in
            --update)
                update_compose_file
                exit 0
                ;;
            --debug)
                DEBUG=true
                ;;
            *)
                echo "Unknown option: $arg"
                echo "Usage: $0 [--update] [--debug]"
                exit 1
                ;;
        esac
    done
    echo "Starting setup..."
    create_env_file
    # Source the .env file after creating it
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi
    setup_tailscale
    install_dependencies
    setup_pia_vpn
    create_docker_compose
    create_config_json
    choose_storage_configuration
    setup_docker_network
    deploy_docker_compose
    setup_mount_and_docker_start
    echo "Setup complete. Update the .env file with credentials if not already done."
    echo "Setup Summary:"
    echo "Docker services are running:"

    # Define the base URL using the server IP
    BASE_URL="http://${SERVER_IP}"

    # Define a list of services with their ports and URLs
    declare -A SERVICES_AND_PORTS=(
        ["VPN"]="${BASE_URL}"
        ["Jackett"]="${BASE_URL}:${JACKET_PORT}"
        ["Sonarr"]="${BASE_URL}:${SONARR_PORT}"
        ["Radarr"]="${BASE_URL}:${RADARR_PORT}"
        ["Transmission"]="${BASE_URL}:${TRANSMISSION_PORT}"
        ["NZBGet"]="${BASE_URL}:${NZBGET_PORT}"
        ["Get_IPlayer"]="${BASE_URL}:${GET_IPLAYER_PORT}"
        ["JellyFin"]="${BASE_URL}:${JELLYFIN_PORT}"
        ["Watchtower"]="(Auto-Updater - no web UI)"
    )

    # Display services and clickable URLs
    echo "Services and their URLs:"
    for SERVICE in "${!SERVICES_AND_PORTS[@]}"; do
        echo "  - $SERVICE: ${SERVICES_AND_PORTS[$SERVICE]}"
    done


    echo "File shares available:"
    if [[ "$SHARE_METHOD" == "1" ]]; then
        echo "  Samba Shares:"
        printf '    \\\\%s\\\\Movies\n' "$SERVER_IP"
        printf '    \\\\%s\\\\TVShows\n' "$SERVER_IP"
        printf '    \\\\%s\\\\Downloads\n' "$SERVER_IP"

    elif [[ "$SHARE_METHOD" == "2" ]]; then
        echo "  NFS Shares:"
        echo "    $SERVER_IP:$STORAGE_DIR"
        echo "    $SERVER_IP:$DOWNLOAD_DIR"

    for SERVICE in "${!SERVICES_AND_PORTS[@]}"; do
        echo "$SERVICE: ${SERVICES_AND_PORTS[$SERVICE]}" >> "$HOME/services_urls.txt"
    done
    echo "URLs saved to $HOME/services_urls.txt"



    fi

}

main
