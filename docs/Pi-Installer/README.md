🐳 Raspberry Pi Docker Stack with VPN, Tailscale, and Media Management

This project automates the setup of a Docker-based media server stack on a Raspberry Pi or any Linux-based system. It includes VPN integration, Tailscale for secure remote access, and popular media management tools. The stack is highly customizable, uses Docker Compose for easy deployment, and supports automatic updates via GitHub.
Features

    VPN Integration: Routes external traffic through a secure VPN container (using Gluetun).
    Tailscale: Enables secure remote access to the server and Docker containers via Tailscale IP.
    Media Management Tools:
        🗂️ Jackett: Indexer proxy for torrent and Usenet sites.
        🎥 Radarr: Movies download manager.
        📺 Sonarr: TV shows download manager.
        🌐 Transmission: Torrent downloader.
        📦 NZBGet: Usenet downloader.
        📻 Get IPlayer: BBC iPlayer downloader with SonarrAutoImport enabled.
        🎛️ Jellyfin: Media server for streaming.
    Watchtower: Automatically updates Docker containers running outside the VPN.
    File Sharing:
        Samba for Windows/macOS/Linux.
        NFS for Linux-only environments.
    Customizable: Easily modify container names, ports, and settings.
    Automatic Updates: Pull the latest docker-compose.yml from GitHub and redeploy with a single command.

Requirements

    Raspberry Pi or Linux-based system (tested on Raspberry Pi 5 with 8GB RAM).
    Docker and Docker Compose installed (handled by the script if not already installed).
    Private Internet Access as the VPN provider (others coming soon: AirVPN, Mullvad, NordVPN, etc.).
    Tailscale account for secure remote access.

Installation

    Clone this repository:

git clone https://github.com/Brownster/PI-PVR.git
cd yourrepo

Make the setup script executable:

chmod +x setup.sh

Run the setup script:

    ./setup.sh

    Follow the on-screen prompts to configure the environment, VPN, and file sharing.

Usage
Debug Mode

Run with --debug to see detailed command outputs:

./setup.sh --debug

Update Docker Compose Stack

Automatically fetch the latest docker-compose.yml from GitHub and redeploy:

./setup.sh --update

Configuration
Environment Variables

The script creates an .env file for managing sensitive data. Update this file as needed:

nano ~/docker/.env

Example .env file:

PIA_USERNAME=your_pia_username
PIA_PASSWORD=your_pia_password
TAILSCALE_AUTH_KEY=your_tailscale_auth_key
TIMEZONE=Europe/London
MOVIES_FOLDER="Movies"
TVSHOWS_FOLDER="TVShows"
DOWNLOADS="/mnt/storage/downloads"

File Sharing

The script supports:

    Samba: Ideal for cross-platform file sharing.
    NFS: Recommended for Linux-only environments.

Configure the method during setup or edit the .env file.
Updating from GitHub

The script supports pulling updates directly from a GitHub repository. Ensure DOCKER_COMPOSE_URL is set to your hosted docker-compose.yml file:

DOCKER_COMPOSE_URL=https://raw.githubusercontent.com/yourusername/yourrepo/main/docker-compose.yml

Services and Ports
Service	Default Port	URL
VPN	N/A	N/A
Jackett	9117	http://<IP>:9117
Sonarr	8989	http://<IP>:8989
Radarr	7878	http://<IP>:7878
Transmission	9091	http://<IP>:9091
NZBGet	6789	http://<IP>:6789
Get IPlayer	1935	http://<IP>:1935
Jellyfin	8096	http://<IP>:8096
Watchtower	N/A	(No Web UI)

Generated URLs are saved to:

~/services_urls.txt

How It Works

    VPN Routing: All media applications route traffic through the VPN container. If the VPN disconnects, traffic is blocked for privacy.
    Tailscale: Provides secure access to all services, bypassing the VPN when needed.
    Watchtower: Updates Docker containers outside the VPN network for unrestricted registry access.

Testing

    Local Access: Open http://<local-IP>:<port> in a browser.

    Tailscale Access: Replace <local-IP> with your Tailscale IP.

    VPN Routing: Verify traffic routes through the VPN:

docker exec -it transmission curl ifconfig.me

Logs: Check Watchtower logs for updates:

    docker logs watchtower

Troubleshooting

    VPN Issues: Ensure PIA credentials are correct in .env. Check VPN logs:

docker logs vpn

Tailscale Authentication:

    sudo tailscale up

Contributing

Contributions are welcome! Open an issue or submit a pull request to enhance the project.
License

This project is licensed under the MIT License.
Acknowledgements

Special thanks to:

    Docker
    Gluetun VPN
    LinuxServer.io
    Sonarr
    Radarr
    Tailscale
