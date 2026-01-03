#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${REPO_DIR}/.venv"
SERVICE_FILE="/etc/systemd/system/pi-health.service"
ENV_FILE="/etc/pi-health.env"
HELPER_SERVICE_FILE="/etc/systemd/system/pihealth-helper.service"
HELPER_LINK="/usr/local/bin/pihealth_helper.py"

CONFIG_DIR="${CONFIG_DIR:-/home/pi/docker}"
DOCKER_COMPOSE_PATH="${DOCKER_COMPOSE_PATH:-${CONFIG_DIR}/docker-compose.yml}"
STACKS_PATH="${STACKS_PATH:-/opt/stacks}"
INSTALL_DOCKER="${INSTALL_DOCKER:-auto}"
ENABLE_TAILSCALE="${ENABLE_TAILSCALE:-auto}"
ENABLE_VPN="${ENABLE_VPN:-0}"
TAILSCALE_AUTH_KEY="${TAILSCALE_AUTH_KEY:-}"
PIA_USERNAME="${PIA_USERNAME:-}"
PIA_PASSWORD="${PIA_PASSWORD:-}"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (sudo)." >&2
  exit 1
fi

prompt_install() {
  local label="$1"
  local var_name="$2"
  local installed_check="$3"

  if eval "$installed_check"; then
    printf ">>> %s already installed.\n" "$label"
    return 1
  fi

  local current="${!var_name}"
  if [[ "$current" == "1" ]]; then
    return 0
  fi
  if [[ "$current" == "0" ]]; then
    printf ">>> Skipping %s install (%s=0).\n" "$label" "$var_name"
    return 1
  fi

  read -r -p "Install ${label}? [y/N] " reply
  if [[ "$reply" =~ ^[Yy]$ ]]; then
    return 0
  fi
  return 1
}

echo ">>> Installing system dependencies..."
apt-get update
apt-get install -y \
  "${PYTHON_BIN}" python3-venv python3-pip \
  git curl jq zstd

if prompt_install "Docker" INSTALL_DOCKER "command -v docker >/dev/null 2>&1"; then
  echo ">>> Installing Docker CE from official repository..."
  apt-get remove -y docker.io docker-doc docker-compose podman-docker containerd runc || true
  apt-get install -y ca-certificates
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" \
    | tee /etc/apt/sources.list.d/docker.list > /dev/null
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi

if command -v docker >/dev/null 2>&1 && ! id -nG "$RUN_USER" | grep -q "\bdocker\b"; then
  echo ">>> Adding ${RUN_USER} to docker group..."
  usermod -aG docker "$RUN_USER"
  echo "NOTE: ${RUN_USER} must re-login for docker group to take effect."
fi

if prompt_install "Tailscale" ENABLE_TAILSCALE "command -v tailscale >/dev/null 2>&1"; then
  echo ">>> Installing Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | sh
  echo ">>> Starting Tailscale..."
  if [[ -z "$TAILSCALE_AUTH_KEY" ]]; then
    tailscale up --accept-routes=false
  else
    tailscale up --accept-routes=false --authkey="$TAILSCALE_AUTH_KEY"
  fi
fi

if prompt_install "SnapRAID" INSTALL_SNAPRAID "command -v snapraid >/dev/null 2>&1"; then
  apt-get install -y snapraid
fi

if prompt_install "MergerFS" INSTALL_MERGERFS "command -v mergerfs >/dev/null 2>&1"; then
  apt-get install -y mergerfs mergerfs-tools
fi

if prompt_install "smartmontools" INSTALL_SMARTMONTOOLS "command -v smartctl >/dev/null 2>&1"; then
  apt-get install -y smartmontools
fi

if [[ "$ENABLE_VPN" == "1" ]]; then
  echo ">>> Configuring VPN network..."
  if docker network ls --format '{{.Name}}' | grep -q '^vpn_network$'; then
    echo "vpn_network already exists."
  else
    docker network create vpn_network
  fi

  if [[ -n "$PIA_USERNAME" && -n "$PIA_PASSWORD" ]]; then
    mkdir -p "${CONFIG_DIR}/vpn"
    if [[ ! -f "${CONFIG_DIR}/vpn/.env" ]]; then
      cat > "${CONFIG_DIR}/vpn/.env" <<EOF
VPN_SERVICE_PROVIDER=private internet access
OPENVPN_USER=${PIA_USERNAME}
OPENVPN_PASSWORD=${PIA_PASSWORD}
SERVER_REGIONS=Netherlands
EOF
      echo ">>> Created ${CONFIG_DIR}/vpn/.env"
    else
      echo ">>> ${CONFIG_DIR}/vpn/.env already exists. Skipping."
    fi
  else
    echo ">>> PIA credentials not set. Skipping VPN .env creation."
  fi
fi

if [[ -d "${REPO_DIR}/examples/stacks" ]]; then
  needs_seed=0
  for stack in vpn-stack media-stack; do
    if [[ -d "${REPO_DIR}/examples/stacks/${stack}" && ! -f "${REPO_DIR}/examples/stacks/${stack}/.env" ]]; then
      needs_seed=1
    fi
  done

  if [[ "$needs_seed" == "1" ]]; then
    read -r -p "Create example stack .env files now? [y/N] " reply
    if [[ "$reply" =~ ^[Yy]$ ]]; then
      for stack in vpn-stack media-stack; do
        if [[ -d "${REPO_DIR}/examples/stacks/${stack}" && ! -f "${REPO_DIR}/examples/stacks/${stack}/.env" ]]; then
          cp "${REPO_DIR}/examples/stacks/.env.example" "${REPO_DIR}/examples/stacks/${stack}/.env"
          echo "Created ${REPO_DIR}/examples/stacks/${stack}/.env"
        fi
      done
    fi
  fi

  read -r -p "Copy example stacks to ${STACKS_PATH}? [y/N] " copy_reply
  if [[ "$copy_reply" =~ ^[Yy]$ ]]; then
    mkdir -p "${STACKS_PATH}"
    for stack in vpn-stack media-stack; do
      if [[ -d "${REPO_DIR}/examples/stacks/${stack}" && ! -d "${STACKS_PATH}/${stack}" ]]; then
        cp -r "${REPO_DIR}/examples/stacks/${stack}" "${STACKS_PATH}/"
        echo "Copied ${stack} to ${STACKS_PATH}/${stack}"
      fi
      if [[ -d "${STACKS_PATH}/${stack}" && ! -f "${STACKS_PATH}/${stack}/.env" ]]; then
        cp "${REPO_DIR}/examples/stacks/.env.example" "${STACKS_PATH}/${stack}/.env"
        echo "Created ${STACKS_PATH}/${stack}/.env"
      fi
    done
  fi
fi

echo ">>> Setting up virtual environment..."
if [[ ! -d "$VENV_DIR" ]]; then
  "${PYTHON_BIN}" -m venv "$VENV_DIR"
fi

"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${REPO_DIR}/requirements.txt"

echo ">>> Installing helper service..."
if [[ ! -e "$HELPER_LINK" ]]; then
  ln -s "${REPO_DIR}/pihealth_helper.py" "$HELPER_LINK"
fi

if ! getent group pihealth >/dev/null 2>&1; then
  groupadd pihealth
fi
usermod -aG pihealth "$RUN_USER"

cat > "$HELPER_SERVICE_FILE" <<EOF
[Unit]
Description=Pi-Health Privileged Helper Service
Documentation=https://github.com/Brownster/pi-health
After=local-fs.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 ${HELPER_LINK}
ExecReload=/bin/kill -HUP \$MAINPID
Restart=on-failure
RestartSec=5

# Security hardening
NoNewPrivileges=false
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/etc/fstab /mnt /run/pihealth /var/log
ReadWritePaths=/backups
PrivateTmp=true

# Socket permissions
RuntimeDirectory=pihealth
RuntimeDirectoryMode=0755

[Install]
WantedBy=multi-user.target
EOF

echo ">>> Writing systemd service..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Pi-Health Dashboard
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${REPO_DIR}
EnvironmentFile=-${ENV_FILE}
Environment=DOCKER_COMPOSE_PATH=${DOCKER_COMPOSE_PATH}
ExecStart=${VENV_DIR}/bin/python ${REPO_DIR}/app.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now pi-health.service
systemctl enable --now pihealth-helper.service

echo ">>> Pi-Health is running."
echo "Open: http://$(hostname -I | awk '{print $1}'):80"
echo "Optional config env: ${ENV_FILE}"
echo "Helper service: pihealth-helper.service"
