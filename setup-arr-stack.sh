#!/bin/bash

# Pi-Health Arr Stack Setup - Complete Media Server Deployment
# Automated setup for the full Arr stack with Docker Compose

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Print colored output
print_banner() {
    echo -e "${PURPLE}"
    echo "  ██████╗ ██╗      ██╗  ██╗███████╗ █████╗ ██╗  ████████╗██╗  ██╗"
    echo "  ██╔══██╗██║      ██║  ██║██╔════╝██╔══██╗██║  ╚══██╔══╝██║  ██║"
    echo "  ██████╔╝██║██████╗███████║█████╗  ███████║██║     ██║   ███████║"
    echo "  ██╔═══╝ ██║╚═════╝██╔══██║██╔══╝  ██╔══██║██║     ██║   ██╔══██║"
    echo "  ██║     ██║      ██║  ██║███████╗██║  ██║███████╗██║   ██║  ██║"
    echo "  ╚═╝     ╚═╝      ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝╚═╝   ╚═╝  ╚═╝"
    echo -e "${NC}"
    echo -e "${CYAN}           Complete Arr Stack Setup with Docker Compose${NC}"
    echo ""
}

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."

    # Check if running as root (not recommended)
    if [[ $EUID -eq 0 ]]; then
        print_warning "Running as root is not recommended for security reasons"
        print_warning "Consider creating a dedicated user for Pi-Health"
    fi

    # Check Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker is required but not installed."
        print_status "Install Docker with: curl -fsSL https://get.docker.com | sh"
        print_status "Then add your user to docker group: sudo usermod -aG docker $USER"
        exit 1
    fi
    print_success "Docker found: $(docker --version)"

    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        print_error "Docker Compose is required but not installed."
        print_status "Install with: pip install docker-compose"
        exit 1
    fi
    print_success "Docker Compose found"

    # Check available disk space (need at least 10GB free for media)
    available_space=$(df . | awk 'NR==2 {print $4}')
    available_gb=$((available_space / 1024 / 1024))
    if [[ $available_gb -lt 10 ]]; then
        print_warning "Less than 10GB free space available (${available_gb}GB found)"
        print_warning "Media server setup requires significant storage space"
    else
        print_success "Available disk space: ${available_gb}GB"
    fi

    # Check RAM (recommend at least 4GB for full stack)
    total_ram=$(free -m | awk 'NR==2{print $2}')
    total_ram_gb=$((total_ram / 1024))
    if [[ $total_ram -lt 4096 ]]; then
        print_warning "Less than 4GB RAM detected (${total_ram_gb}GB found)"
        print_warning "Consider optimizing container resource limits"
    else
        print_success "Available RAM: ${total_ram_gb}GB"
    fi
}

# Interactive configuration
configure_setup() {
    print_status "Interactive configuration setup..."
    echo ""

    # Get user/group IDs
    current_uid=$(id -u)
    current_gid=$(id -g)
    echo -e "${CYAN}Your current user ID: ${current_uid}, group ID: ${current_gid}${NC}"

    # Get paths from user
    echo ""
    print_status "Please configure your storage paths:"

    # Docker config path
    read -p "Enter Docker config path (default: $HOME/docker): " docker_config_path
    docker_config_path=${docker_config_path:-"$HOME/docker"}

    # Media path
    read -p "Enter media storage path (default: /mnt/storage): " media_path
    media_path=${media_path:-"/mnt/storage"}

    # Downloads path
    read -p "Enter downloads path (default: /mnt/downloads): " downloads_path
    downloads_path=${downloads_path:-"/mnt/downloads"}

    # Timezone
    current_tz=$(timedatectl show --property=Timezone --value 2>/dev/null || echo "UTC")
    read -p "Enter timezone (default: $current_tz): " timezone
    timezone=${timezone:-"$current_tz"}

    # Create directories
    print_status "Creating directory structure..."
    mkdir -p "$docker_config_path"
    mkdir -p "$docker_config_path"/{vpn,sonarr,radarr,lidarr,jellyfin,jellyseerr,jackett,transmission,sabnzbd,navidrome,audiobookshelf}
    mkdir -p "$media_path"/{Movies,TV,Music,Books,AudioBooks,Podcasts}
    mkdir -p "$downloads_path"/{completed,incomplete}

    print_success "Directory structure created"

    # Export variables for template processing
    export DOCKER_CONFIG_PATH="$docker_config_path"
    export MEDIA_PATH="$media_path"
    export DOWNLOADS_PATH="$downloads_path"
    export TIMEZONE="$timezone"
    export PUID="$current_uid"
    export PGID="$current_gid"
}

# Setup environment file
setup_environment() {
    print_status "Setting up environment configuration..."

    if [[ -f ".env" ]]; then
        print_warning ".env file already exists, creating backup..."
        cp .env .env.backup
    fi

    # Create .env from template with substitutions
    cat > .env << EOF
# Pi-Health Arr Stack Environment Configuration
# Generated by setup script

# ===== BASIC CONFIGURATION =====
TIMEZONE=${TIMEZONE}
PUID=${PUID}
PGID=${PGID}

# ===== PATH CONFIGURATION =====
DOCKER_CONFIG_PATH=${DOCKER_CONFIG_PATH}
MEDIA_PATH=${MEDIA_PATH}
DOWNLOADS_PATH=${DOWNLOADS_PATH}

# ===== PI-HEALTH CONFIGURATION =====
ENABLE_AI_AGENT=false
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_API_MODEL=gpt-4o-mini

# System monitoring
DISK_PATH=${MEDIA_PATH}
DISK_PATH_2=${DOWNLOADS_PATH}

# Security
ENABLE_SYSTEM_ACTIONS=true
ENABLE_LEGACY_SUGGESTIONS=true

# ===== MCP SERVICE URLS =====
SONARR_MCP_BASE_URL=http://localhost:8989
RADARR_MCP_BASE_URL=http://localhost:7878
LIDARR_MCP_BASE_URL=http://localhost:8686
SABNZBD_MCP_BASE_URL=http://localhost:8080
JELLYFIN_MCP_BASE_URL=http://localhost:8096
JELLYSEERR_MCP_BASE_URL=http://localhost:5055
DOCKER_MCP_BASE_URL=unix:///var/run/docker.sock

# ===== MEDIA SERVER SETTINGS =====
LASTFM_API_KEY=
LASTFM_SECRET=
EOF

    print_success "Environment configuration created"
}

# Setup Docker Compose
setup_docker_compose() {
    print_status "Setting up Docker Compose configuration..."

    if [[ -f "docker-compose.yml" ]]; then
        print_warning "docker-compose.yml already exists, creating backup..."
        cp docker-compose.yml docker-compose.yml.backup
    fi

    # Copy the arr-stack template
    if [[ -f "docker-compose.arr-stack.yml" ]]; then
        cp docker-compose.arr-stack.yml docker-compose.yml
        print_success "Docker Compose configuration created"
    else
        print_error "docker-compose.arr-stack.yml template not found!"
        exit 1
    fi
}

# Setup VPN configuration
setup_vpn() {
    print_status "Setting up VPN configuration..."

    vpn_dir="${DOCKER_CONFIG_PATH}/vpn"
    mkdir -p "$vpn_dir"

    if [[ ! -f "$vpn_dir/.env" ]]; then
        cat > "$vpn_dir/.env" << 'EOF'
# VPN Configuration
# Configure for your VPN provider

# Example for most providers:
# VPN_SERVICE_PROVIDER=custom
# VPN_TYPE=openvpn
# OPENVPN_USER=your_username
# OPENVPN_PASSWORD=your_password
# SERVER_COUNTRIES=Netherlands

# Example for Surfshark:
# VPN_SERVICE_PROVIDER=surfshark
# OPENVPN_USER=your_surfshark_user
# OPENVPN_PASSWORD=your_surfshark_password
# SERVER_COUNTRIES=Netherlands

# Example for NordVPN:
# VPN_SERVICE_PROVIDER=nordvpn
# OPENVPN_USER=your_nordvpn_user
# OPENVPN_PASSWORD=your_nordvpn_password
# SERVER_COUNTRIES=Netherlands
EOF
        print_success "VPN configuration template created at $vpn_dir/.env"
        print_warning "Please edit $vpn_dir/.env with your VPN provider settings"
    else
        print_warning "VPN configuration already exists, skipping..."
    fi
}

# Main setup function
main() {
    print_banner

    check_prerequisites
    configure_setup
    setup_environment
    setup_docker_compose
    setup_vpn

    print_success "Setup completed successfully!"
    echo ""
    echo -e "${GREEN}=========================================${NC}"
    echo -e "${GREEN}🚀 Pi-Health Arr Stack is ready!${NC}"
    echo -e "${GREEN}=========================================${NC}"
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    echo "1. Configure VPN settings in ${DOCKER_CONFIG_PATH}/vpn/.env"
    echo "2. Edit .env if needed (OpenAI API key, etc.)"
    echo "3. Start the stack: ${CYAN}docker-compose up -d${NC}"
    echo "4. Monitor startup: ${CYAN}docker-compose logs -f${NC}"
    echo ""
    echo -e "${BLUE}Service URLs (once started):${NC}"
    echo "• Pi-Health Dashboard: ${CYAN}http://localhost:8100${NC}"
    echo "• Sonarr (TV): ${CYAN}http://localhost:8989${NC}"
    echo "• Radarr (Movies): ${CYAN}http://localhost:7878${NC}"
    echo "• Lidarr (Music): ${CYAN}http://localhost:8686${NC}"
    echo "• Jellyfin (Media Server): ${CYAN}http://localhost:8096${NC}"
    echo "• Jellyseerr (Requests): ${CYAN}http://localhost:5055${NC}"
    echo ""
    echo -e "${YELLOW}Default Pi-Health login: admin / password${NC}"
    echo ""
    echo -e "${BLUE}For help and documentation: https://github.com/Brownster/pi-health${NC}"
}

# Run main function
main "$@"