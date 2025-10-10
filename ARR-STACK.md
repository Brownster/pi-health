# Pi-Health Arr Stack Setup 🚀

Complete automated setup for a full media server stack with VPN protection, managed through Pi-Health's intelligent dashboard.

## 🎯 What You Get

### Media Management Stack
- **Sonarr** (TV Series) - Automatically downloads and manages TV shows
- **Radarr** (Movies) - Automatically downloads and manages movies
- **Lidarr** (Music) - Automatically downloads and manages music
- **Readarr** (Books) - Automatically downloads and manages ebooks
- **Jellyseerr** - Beautiful request interface for family/friends

### Download Clients
- **Transmission** - BitTorrent client
- **SABnzbd** - Usenet client
- **RDTClient** - Real-Debrid integration
- **Jackett** - Torrent indexer aggregator

### Media Servers
- **Jellyfin** - Open-source media streaming server
- **Navidrome** - Music streaming server
- **AudioBookshelf** - Audiobook and podcast server

### Management & Monitoring
- **Pi-Health Dashboard** - Central control panel with AI assistant
- **VPN Protection** - All downloads routed through VPN
- **Auto-updates** - Containers kept up to date automatically

## 🛠 Quick Setup

### One-Command Installation
```bash
git clone https://github.com/Brownster/pi-health.git
cd pi-health
./setup-arr-stack.sh
```

### Manual Setup Steps
1. **Prerequisites**
   ```bash
   # Install Docker
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER

   # Install Docker Compose
   pip install docker-compose
   ```

2. **Configure Environment**
   ```bash
   # Copy and edit configuration
   cp .env.arr-stack .env
   cp docker-compose.arr-stack.yml docker-compose.yml

   # Edit paths in .env file
   nano .env
   ```

3. **Set Up VPN** (Required)
   ```bash
   # Create VPN config directory
   mkdir -p docker/vpn

   # Configure your VPN provider
   nano docker/vpn/.env
   ```

4. **Launch Stack**
   ```bash
   docker-compose up -d
   ```

## ⚙️ Configuration

### Essential Settings in `.env`

```bash
# Your storage paths
DOCKER_CONFIG_PATH=/home/your-user/docker
MEDIA_PATH=/mnt/storage
DOWNLOADS_PATH=/mnt/downloads

# VPN is mandatory for download clients
# Configure in docker/vpn/.env

# User permissions
PUID=1000  # Your user ID
PGID=1000  # Your group ID

# Timezone
TIMEZONE=Europe/London
```

### VPN Configuration (`docker/vpn/.env`)

Choose your provider and configure accordingly:

**Surfshark Example:**
```bash
VPN_SERVICE_PROVIDER=surfshark
OPENVPN_USER=your_username
OPENVPN_PASSWORD=your_password
SERVER_COUNTRIES=Netherlands
```

**NordVPN Example:**
```bash
VPN_SERVICE_PROVIDER=nordvpn
OPENVPN_USER=your_username
OPENVPN_PASSWORD=your_password
SERVER_COUNTRIES=Netherlands
```

**Custom Provider:**
```bash
VPN_SERVICE_PROVIDER=custom
VPN_TYPE=openvpn
# Place your .ovpn files in docker/vpn/
```

## 🔗 Service URLs

Once running, access your services:

| Service | URL | Purpose |
|---------|-----|---------|
| Pi-Health Dashboard | http://localhost:8100 | Central management |
| Sonarr | http://localhost:8989 | TV show management |
| Radarr | http://localhost:7878 | Movie management |
| Lidarr | http://localhost:8686 | Music management |
| Jellyfin | http://localhost:8096 | Media streaming |
| Jellyseerr | http://localhost:5055 | Media requests |
| Transmission | http://localhost:9091 | Torrent client |

## 🔧 Pi-Health Integration

Pi-Health automatically detects and manages your Arr stack:

### AI Assistant Features
- **Smart monitoring** - Detects issues and suggests fixes
- **Automated troubleshooting** - Can restart services, clear logs
- **Intelligent suggestions** - Recommends optimizations
- **Natural language control** - "Restart Sonarr" or "Check Radarr status"

### MCP Service Management
- **Auto-discovery** - Services detected from docker-compose.yml
- **One-click controls** - Start/stop/restart from dashboard
- **Resource monitoring** - RAM, CPU, disk usage tracking
- **Health checks** - Automatic service health monitoring

### Dashboard Features
- **Container management** - Docker container oversight
- **System monitoring** - CPU, memory, disk, temperature
- **Log aggregation** - Centralized logging and analysis
- **Backup management** - Configuration backup and restore

## 📁 Directory Structure

```
/home/your-user/docker/          # Container configurations
├── vpn/                         # VPN configuration
├── sonarr/                      # Sonarr config
├── radarr/                      # Radarr config
├── lidarr/                      # Lidarr config
├── jellyfin/                    # Jellyfin config
└── ...

/mnt/storage/                    # Media library (customize path)
├── Movies/                      # Movie files
├── TV/                          # TV show files
├── Music/                       # Music files
├── Books/                       # Ebook files
└── AudioBooks/                  # Audiobook files

/mnt/downloads/                  # Downloads folder (customize path)
├── completed/                   # Finished downloads
├── incomplete/                  # In-progress downloads
└── ...
```

## 🛡️ Security Features

### Built-in Protection
- **VPN mandatory** - All download traffic routed through VPN
- **Network isolation** - Services containerized and isolated
- **Authentication** - Pi-Health dashboard login protection
- **API security** - MCP endpoints require authentication
- **No exposed secrets** - All credentials in environment files

### Recommended Security
- **Change default passwords** - Update Pi-Health login (admin/password)
- **Firewall configuration** - Block unnecessary ports
- **Regular updates** - Watchtower keeps containers updated
- **Backup encryption** - Encrypt configuration backups

## 🔄 Management Commands

```bash
# View status
docker-compose ps

# View logs
docker-compose logs -f sonarr

# Restart a service
docker-compose restart radarr

# Update containers
docker-compose pull
docker-compose up -d

# Backup configurations
tar -czf backup-$(date +%Y%m%d).tar.gz docker/

# Monitor resources
docker stats
```

## 🆘 Troubleshooting

### Common Issues

**VPN not connecting:**
```bash
# Check VPN logs
docker-compose logs vpn

# Verify credentials in docker/vpn/.env
# Try different server location
```

**Services can't reach each other:**
- Check VPN is running: `docker-compose ps vpn`
- Verify network_mode: "service:vpn" configuration
- Test with: `docker-compose exec sonarr ping jackett`

**Permission issues:**
```bash
# Fix ownership
sudo chown -R $USER:$USER /mnt/storage
sudo chown -R $USER:$USER /mnt/downloads

# Verify PUID/PGID in .env match your user
id
```

**High resource usage:**
- Enable hardware acceleration in Jellyfin
- Adjust quality settings in streaming services
- Limit concurrent downloads in download clients

### Pi-Health Troubleshooting
- **AI Agent not working:** Check OpenAI API key in settings
- **MCP services not detected:** Restart Pi-Health container
- **Settings not saving:** Check file permissions on .env

## 🌟 Advanced Configuration

### Hardware Acceleration (Jellyfin)
Uncomment in docker-compose.yml:
```yaml
devices:
  - /dev/dri:/dev/dri  # Intel QuickSync
  - /dev/vchiq:/dev/vchiq  # RPi hardware decode
```

### Custom Indexers
Add your private trackers to Jackett or Prowlarr, then configure in the Arr services.

### Notifications
Configure Discord/Telegram/Email notifications in each Arr service for downloads and issues.

### Reverse Proxy
Use Nginx Proxy Manager or Traefik to add SSL and custom domains.

## 📈 Monitoring

Pi-Health provides comprehensive monitoring:
- **Container health** - Automatic restart of failed services
- **Disk space** - Alerts when storage is low
- **Network status** - VPN connection monitoring
- **Performance** - Resource usage tracking
- **Log analysis** - AI-powered error detection

## 🎉 Enjoy Your Media Server!

Your complete media automation stack is now running! The AI assistant will help you manage everything, and the web interfaces provide full control over your media library.

**Default Login:** admin / password (change in Pi-Health settings!)

For support and updates, visit: https://github.com/Brownster/pi-health