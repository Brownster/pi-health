# Pi-Health: Your Personal Server Dashboard

Welcome to Pi-Health, a powerful, lightweight dashboard designed to help you manage your home server, especially on low-power devices like a Raspberry Pi. With Pi-Health, you can monitor system health, manage Docker containers and multi-service stacks, organize your storage, and set up a resilient file pool with parity protection, all from a clean web interface.

This guide will walk you through setting up and using all the features of your Pi-Health instance.

## Table of Contents

1.  [Initial Setup](#1-initial-setup)
2.  [First-Time Login & User Management](#2-first-time-login--user-management)
3.  [Networking: VPN & Tailscale](#3-networking-vpn--tailscale)
4.  [Docker & Stacks Management](#4-docker--stacks-management)
    *   [Understanding Stacks](#understanding-stacks)
    *   [Creating a New Stack](#creating-a-new-stack)
    *   [Managing Existing Stacks](#managing-existing-stacks)
5.  [App Catalog](#5-app-catalog)
6.  [Updating Containers](#6-updating-containers)
7.  [Disk Management](#7-disk-management)
    *   [Viewing and Identifying Disks](#viewing-and-identifying-disks)
    *   [Mounting and Unmounting Disks](#mounting-and-unmounting-disks)
    *   [Auto-mounting on Boot (`fstab`)](#auto-mounting-on-boot-fstab)
8.  [Storage Pooling with MergerFS](#8-storage-pooling-with-mergerfs)
    *   [What is MergerFS?](#what-is-mergerfs)
    *   [Creating a Storage Pool](#creating-a-storage-pool)
9.  [Parity Protection with SnapRAID](#9-parity-protection-with-snapraid)
    *   [What is SnapRAID?](#what-is-snapraid)
    *   [Configuring SnapRAID](#configuring-snapraid)
    *   [Running Sync and Scrub](#running-sync-and-scrub)
    *   [Scheduling SnapRAID Tasks](#scheduling-snapraid-tasks)

---

### 1. Initial Setup

Pi-Health now recommends a **bare-metal install** on Raspberry Pi for the best access to disk and system features. Docker is still supported, but the bare-metal flow is the default.

**Prerequisites:**
*   Raspberry Pi OS (or compatible Debian-based OS).
*   For Raspberry Pi specific features, the `vcgencmd` utility must be available.

**Bare-Metal Install (Recommended):**

```bash
git clone https://github.com/Brownster/pi-health.git
cd pi-health
./start.sh
```

Optional flags:

```bash
# Install Tailscale
ENABLE_TAILSCALE=1 ./start.sh

# Configure VPN (Gluetun) network + PIA credentials
ENABLE_VPN=1 PIA_USERNAME=your_user PIA_PASSWORD=your_pass ./start.sh
```

**Docker Install (Optional):**

Create a `docker-compose.yml` file with the following content:

```yaml
version: "3.7"
services:
  pihealth:
    image: your-repo/pi-health:latest  # Replace with the actual image name
    container_name: pihealth
    ports:
      - "80:80"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock # Required for Docker management
      - /path/to/your/stacks:/opt/stacks         # Your stacks directory
      - /path/to/your/disks:/mnt                   # Your disk mount points
      - /path/to/app/config:/config              # Pi-Health's own config
    environment:
      - PIHEALTH_USER=admin
      - PIHEALTH_PASSWORD=your_secure_password
      - STACKS_PATH=/opt/stacks
      - DISK_PATH=/mnt
    restart: unless-stopped
```

**Key Configuration:**

*   **Ports:** The default web interface will be available on port `80`.
*   **Volumes:**
    *   `docker.sock`: This is **required** to allow Pi-Health to manage your Docker containers.
    *   `/opt/stacks`: This is the directory on your host machine where your Docker stacks (each with its own `compose.yaml`) are stored.
    *   `/mnt`: It's recommended to mount all your physical disks under `/mnt` on your host. This allows Pi-Health to manage them.
*   **Environment Variables:**
    *   `PIHEALTH_USER`: Set your initial administrator username.
    *   `PIHEALTH_PASSWORD`: **Set a strong, unique password for your administrator account.**
    *   `STACKS_PATH`: Must match the volume mount for your stacks.

Run `docker-compose up -d` in the same directory as your `docker-compose.yml` file to start the application.

### 2. First-Time Login & User Management

Once Pi-Health is running, open your web browser and navigate to `http://<your-server-ip>:80`.

*   **Initial Login:** You will be prompted for a username and password. Use the credentials you set in the `PIHEALTH_USER` and `PIHEALTH_PASSWORD` environment variables.

*   **User Management:** Pi-Health supports multiple users. You can configure users by setting the `PIHEALTH_USERS` environment variable in your `docker-compose.yml` file. The format is a comma-separated list of `username:password` pairs.

    **Example:**
    ```yaml
    environment:
      - PIHEALTH_USERS=admin:strong_password,user2:another_password
    ```
    If you update this variable, you will need to restart the Pi-Health container for the changes to take effect.

### 3. Networking: VPN & Tailscale

Pi-Health can bootstrap Tailscale and VPN setup from the **Settings > Setup** card. This keeps setup simple while still allowing manual installs if you prefer.

**Recommended Setup with Tailscale (UI):**

1.  Go to **Settings > Setup**.
2.  Paste your Tailscale auth key (or leave blank for interactive login).
3.  Click **Install & Start**.
4.  Access the dashboard at `http://<your-tailscale-ip>:80`.

This setup ensures that your server management interface is not exposed to the public internet, but is easily accessible to you from anywhere.

### 4. Docker & Stacks Management

Pi-Health provides a powerful interface for managing your Docker containers, organized into "Stacks".

#### Understanding Stacks

A **Stack** is simply a directory containing a `compose.yaml` or `docker-compose.yml` file. Each stack represents a single application or a group of related services (e.g., a "media" stack with Sonarr, Radarr, and Plex).

This approach is much cleaner than managing one giant `docker-compose.yml` file. Your stacks are located in the directory defined by `STACKS_PATH` (default: `/opt/stacks`).

#### Creating a New Stack

1.  Navigate to the **"Stacks"** page from the main navigation.
2.  Click the **"New Stack"** button.
3.  A modal will appear:
    *   **Stack Name:** Give your stack a simple, descriptive name (e.g., `portainer`, `media-stack`).
    *   **compose.yaml:** Write or paste your Docker Compose configuration here. The editor provides syntax highlighting and will validate your YAML to prevent errors.
    *   **.env (optional):** If your stack requires environment variables, you can add them here.
4.  Click **"Create Stack"**. Pi-Health will create a new directory and the compose files in your main stacks folder.

#### Managing Existing Stacks

On the "Stacks" page, you will see a card for each stack you've created.

*   **Quick Actions:** Each card has buttons for `Start`, `Stop`, and `Restart`.
*   **Detailed Management:** Click on a stack card to open the detail view, which has several tabs:
    *   **Compose:** Edit your `compose.yaml` file. The editor has built-in YAML validation. Click "Save" to save your changes, or "Save & Deploy" to save and immediately apply them (`docker compose up -d`).
    *   **Environment:** Edit the `.env` file associated with your stack.
    *   **Logs:** View the logs for all services in the stack.
    *   **Terminal:** This tab shows the real-time output of Docker Compose commands like `up`, `down`, `pull`, and `restart`. This is crucial for debugging.
    *   **Backups:** View and restore from automatic backups of your `compose.yaml` file. Pi-Health creates a backup every time you save changes.

### 5. App Catalog

The "Apps" page provides templates to quickly deploy popular self-hosted applications.

1.  Navigate to the **"Apps"** page.
2.  Browse the list of available applications.
3.  Click **"Deploy"** on the app you want to install.
4.  Pi-Health will automatically pre-fill a new stack with a tested `compose.yaml`. It will also intelligently suggest paths for configuration and media volumes based on your disk setup (see [Disk Management](#7-disk-management)).
5.  Review the configuration, make any desired changes, and click **"Create Stack"**.

### 6. Updating Containers

Pi-Health helps you keep your applications up-to-date.

*   **From the "Containers" Page:**
    *   Click the **"Check"** button on any container to check if a newer image is available on Docker Hub.
    *   If an update is available, an update icon (🔄) will appear next to the container's name.
    *   Click the **"Update"** button to pull the latest image and recreate the container. This uses `docker compose up -d`, so it's safe for stack-managed containers.

*   **From the "Stacks" Page:**
    *   Open the detail view for a stack.
    *   Click the **"Pull"** button to pull the latest images for all services in the stack.
    *   Click the **"Restart"** button to recreate the services with the newly pulled images.

### 7. Disk Management

The "Disks" page is the central hub for managing your server's storage.

#### Viewing and Identifying Disks

Navigate to the **"Disks"** page. You will see a list of all physical storage devices connected to your system (NVMe drives, HDDs, USB sticks).

*   The view is hierarchical, showing disks and the partitions on them.
*   For each disk/partition, you can see its size, UUID, filesystem type, and current mount point.
*   Mounted partitions will show a usage bar indicating used and free space.

#### Mounting and Unmounting Disks

*   **To Mount a Disk:** Find the unmounted partition you want to use and click the **"Mount"** button. Pi-Health will ask for a mount point. **It is strongly recommended to use a mount point inside `/mnt/` (e.g., `/mnt/media`, `/mnt/downloads`).**
*   **To Unmount a Disk:** Click the **"Unmount"** button next to a mounted partition.

#### Auto-mounting on Boot (`fstab`)

To ensure your drives are available after a reboot, you need to configure them to auto-mount.

1.  On the "Disks" page, find the mounted drive you want to configure.
2.  Click the **"Auto-mount on Boot"** toggle.
3.  Pi-Health will safely add an entry to your system's `/etc/fstab` file using the drive's UUID, which is the most reliable way to identify it.
4.  A backup of `/etc/fstab` is automatically created before any changes are made.
5.  If you changed mount points, click **"Regenerate Startup Service"** to ensure Docker waits for mounts on boot.

### 8. Storage Pooling with MergerFS

This feature is for users with multiple physical data disks who want to present them as a single, large virtual drive. This corresponds to your "Setup 2".

#### What is MergerFS?

MergerFS "merges" several filesystems into one. If you have `/mnt/disk1` (1TB) and `/mnt/disk2` (1TB), you can create a MergerFS pool at `/mnt/pool` that appears as a single 2TB drive. When you write a file to `/mnt/pool`, MergerFS decides which of the underlying physical disks to place it on.

**It is NOT RAID. It does not provide redundancy.** If a disk fails, you only lose the data on that disk. This is why we use it with SnapRAID.

#### Creating a Storage Pool

1.  First, ensure all the drives you want to include in the pool are **mounted** and **configured to auto-mount** (see previous section).
2.  Navigate to the **"Storage"** page and open the **"MergerFS"** tab.
3.  Click **"Add Pool"** and enter the pool name, branches, and mount point (e.g., `/mnt/storage_pool`).
4.  Click **"Save Config"**, then **"Apply Config"**.
5.  You can now point your applications (e.g., Plex, Sonarr) to this single pool directory.

### 9. Parity Protection with SnapRAID

SnapRAID provides parity-based backup and recovery for your data pool. It's a perfect companion to MergerFS.

#### What is SnapRAID?

SnapRAID takes a "snapshot" of your data at a point in time and calculates parity information from it. This parity data is stored on a dedicated parity drive. If one of your data drives fails, you can use the parity information to reconstruct the lost data.

*   **It is not real-time RAID.** You must run a `sync` command to update the parity information.
*   It protects against single-disk failure (or more, if you have more parity drives).
*   It allows you to recover accidentally deleted files (if they were present in the last snapshot).

#### Configuring SnapRAID

1.  **Prerequisites:** You need at least one drive dedicated *only* to parity. This drive must be as large as or larger than the largest single data drive in your pool.
2.  Navigate to the **"Storage"** page and open the **"SnapRAID"** tab.
3.  **Drive Selection:**
    *   Designate one or more drives as **Parity**.
    *   Select all the drives that are part of your MergerFS pool as **Data**.
    *   Optionally, select a drive for the **Content** file (a list of all files and their checksums). It's good practice to store this on a data drive.
4.  **Save Config:** Click **"Save Config"**, then **"Apply Config"**. This will generate the `snapraid.conf` file for you.

#### Running Sync and Scrub

*   **`snapraid sync`**: This is the most important command. It reads all your data drives and updates the parity drive with the latest changes. **You must run this regularly.**
    *   Click the **"Sync"** button on the **"Tools"** tab.
    *   The live output of the command will be streamed to the page, so you can monitor its progress. This can take a long time, especially the first time.

*   **`snapraid scrub`**: This command checks your data for "bit rot" (silent corruption) and fixes it if possible using the parity data. It's good practice to run this periodically.
    *   Click the **"Scrub"** button on the **"Tools"** tab to start a scrub job.

#### Scheduling SnapRAID Tasks

Manually running `sync` is tedious. Pi-Health lets you automate it.

1.  On the **"Storage"** page, open the **"Schedules"** tab.
2.  **Sync Schedule:** Set up a schedule for the `sync` command. A daily schedule (e.g., at 3:00 AM) is recommended for most users.
3.  **Scrub Schedule:** Set up a schedule for the `scrub` command. A weekly or monthly schedule is usually sufficient.
4.  Click **"Save Schedule"**. Pi-Health will create systemd timers to run these commands automatically.

You now have a fully-featured, Unraid-style storage system running on your Pi!
