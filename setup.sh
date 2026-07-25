#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="${SUDO_USER:-${USER:-$(id -un)}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${REPO_DIR}/.venv"
SERVICE_FILE="/etc/systemd/system/pi-health.service"
PREFLIGHT_SCRIPT="${LIMEOS_PREFLIGHT_SCRIPT:-${REPO_DIR}/scripts/onboarding-preflight.sh}"
ALLOW_UNSUPPORTED_HOST="${LIMEOS_ALLOW_UNSUPPORTED_HOST:-0}"
LEGACY_ENV_FILE="/etc/pi-health.env"
LIMEOS_CONFIG_DIR="${LIMEOS_CONFIG_DIR:-/etc/limeos}"
LIMEOS_STATE_DIR="${LIMEOS_STATE_DIR:-/var/lib/limeos}"
LIMEOS_LOG_DIR="${LIMEOS_LOG_DIR:-/var/log/limeos}"
CREDENTIALS_FILE="${LIMEOS_CREDENTIALS_FILE:-${LIMEOS_CONFIG_DIR}/credentials.env}"
HELPER_SERVICE_FILE="/etc/systemd/system/pihealth-helper.service"
HELPER_LINK="/usr/local/bin/pihealth_helper.py"
METRICS_SERVICE_FILE="/etc/systemd/system/limeos-metrics-collector.service"
METRICS_TIMER_FILE="/etc/systemd/system/limeos-metrics-collector.timer"
INSTALL_CHECK_SCRIPT="${LIMEOS_INSTALL_CHECK_SCRIPT:-${REPO_DIR}/scripts/onboarding-install-check.sh}"

if [[ -z "${CONFIG_DIR+x}" ]]; then
  if [[ -f "${SERVICE_FILE}" ]] &&
    grep -Fq "Environment=DOCKER_COMPOSE_PATH=/home/pi/docker/docker-compose.yml" \
      "${SERVICE_FILE}"; then
    CONFIG_DIR="/home/pi/docker"
  else
    CONFIG_DIR="${LIMEOS_STATE_DIR}/apps"
  fi
fi
DOCKER_COMPOSE_PATH="${DOCKER_COMPOSE_PATH:-${CONFIG_DIR}/docker-compose.yml}"
STACKS_PATH="${STACKS_PATH:-/opt/stacks}"
INSTALL_DOCKER="${INSTALL_DOCKER:-1}"
ENABLE_TAILSCALE="${ENABLE_TAILSCALE:-0}"
ENABLE_VPN="${ENABLE_VPN:-0}"
TAILSCALE_AUTH_KEY="${TAILSCALE_AUTH_KEY:-}"
PIA_USERNAME="${PIA_USERNAME:-}"
PIA_PASSWORD="${PIA_PASSWORD:-}"
INSTALL_SNAPRAID="${INSTALL_SNAPRAID:-0}"
INSTALL_MERGERFS="${INSTALL_MERGERFS:-0}"
INSTALL_SMARTMONTOOLS="${INSTALL_SMARTMONTOOLS:-1}"
INSTALL_SSHFS="${INSTALL_SSHFS:-0}"
INSTALL_LEGACY_EXAMPLE_STACKS="${INSTALL_LEGACY_EXAMPLE_STACKS:-0}"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (sudo)." >&2
  exit 1
fi

fct_run_onboarding_preflight() {
  local preflight_args=()

  if [[ ! -x "${PREFLIGHT_SCRIPT}" ]]; then
    printf 'Onboarding preflight is missing or not executable: %s\n' \
      "${PREFLIGHT_SCRIPT}" >&2
    exit 2
  fi

  if [[ -f "${SERVICE_FILE}" ]]; then
    preflight_args+=("--allow-existing-install")
  elif [[ "${ALLOW_UNSUPPORTED_HOST}" == "1" ]]; then
    preflight_args+=("--allow-unsupported")
  fi

  printf '>>> Checking host compatibility before installation...\n'
  if ! "${PREFLIGHT_SCRIPT}" "${preflight_args[@]}"; then
    printf '%s\n' \
      "Host preflight failed. Resolve the blockers above before rerunning setup." >&2
    exit 2
  fi
}

fct_run_onboarding_preflight

fct_validate_install_options() {
  local option_name=""
  local option_value=""

  for option_name in \
    INSTALL_DOCKER ENABLE_TAILSCALE INSTALL_SNAPRAID \
    INSTALL_MERGERFS INSTALL_SMARTMONTOOLS INSTALL_SSHFS; do
    option_value="${!option_name}"
    if [[ "${option_value}" != "0" && "${option_value}" != "1" &&
      "${option_value}" != "auto" ]]; then
      printf '%s must be 0, 1, or auto; received %s.\n' \
        "${option_name}" "${option_value}" >&2
      exit 2
    fi
  done
  for option_name in ENABLE_VPN INSTALL_LEGACY_EXAMPLE_STACKS; do
    option_value="${!option_name}"
    if [[ "${option_value}" != "0" && "${option_value}" != "1" ]]; then
      printf '%s must be 0 or 1; received %s.\n' \
        "${option_name}" "${option_value}" >&2
      exit 2
    fi
  done
}

fct_prompt_install() {
  local label="${1}"
  local var_name="${2}"
  local installed_command="${3}"
  local require_compose="${4:-0}"
  local current=""
  local reply=""

  if command -v "${installed_command}" >/dev/null 2>&1 &&
    { [[ "${require_compose}" == "0" ]] ||
      "${installed_command}" compose version >/dev/null 2>&1; }; then
    printf '>>> %s already installed.\n' "${label}"
    return 1
  fi

  current="${!var_name}"
  if [[ "${current}" == "1" ]]; then
    return 0
  fi
  if [[ "${current}" == "0" ]]; then
    printf '>>> Skipping %s install (%s=0).\n' "${label}" "${var_name}"
    return 1
  fi

  if [[ ! -t 0 ]]; then
    printf '>>> Skipping %s install (%s=auto without a terminal).\n' \
      "${label}" "${var_name}"
    return 1
  fi
  read -r -p "Install ${label}? [y/N] " reply
  if [[ "${reply}" =~ ^[Yy]$ ]]; then
    return 0
  fi
  return 1
}

fct_install_legacy_example_stacks() {
  local stack=""

  if [[ "${INSTALL_LEGACY_EXAMPLE_STACKS}" != "1" ]]; then
    return
  fi
  if [[ ! -d "${REPO_DIR}/examples/stacks" ]]; then
    printf 'Legacy example stacks not found under %s.\n' \
      "${REPO_DIR}/examples/stacks" >&2
    exit 2
  fi

  printf '>>> Installing legacy example stacks into %s...\n' "${STACKS_PATH}"
  install -d -m 0750 -o "${RUN_USER}" -g pihealth "${STACKS_PATH}"
  for stack in vpn-stack media-stack; do
    if [[ -d "${REPO_DIR}/examples/stacks/${stack}" &&
      ! -d "${STACKS_PATH}/${stack}" ]]; then
      cp -R "${REPO_DIR}/examples/stacks/${stack}" "${STACKS_PATH}/"
      chown -R "${RUN_USER}:pihealth" "${STACKS_PATH}/${stack}"
      printf 'Copied %s to %s/%s.\n' \
        "${stack}" "${STACKS_PATH}" "${stack}"
    fi
    if [[ -d "${STACKS_PATH}/${stack}" &&
      ! -f "${STACKS_PATH}/${stack}/.env" ]]; then
      install -m 0640 -o "${RUN_USER}" -g pihealth \
        "${REPO_DIR}/examples/stacks/.env.example" \
        "${STACKS_PATH}/${stack}/.env"
      printf 'Created %s/%s/.env.\n' "${STACKS_PATH}" "${stack}"
    fi
  done
}

fct_validate_install_options

echo ">>> Installing system dependencies..."
apt-get update
apt-get install -y \
  "${PYTHON_BIN}" python3-venv python3-pip \
  git curl jq zstd

if fct_prompt_install "Docker and Compose" INSTALL_DOCKER docker 1; then
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
fi

if [[ "${INSTALL_DOCKER}" != "0" ]] && command -v docker >/dev/null 2>&1; then
  systemctl enable --now docker
  if ! id -nG "${RUN_USER}" | grep -q "\bdocker\b"; then
    echo ">>> Adding ${RUN_USER} to docker group..."
    usermod -aG docker "${RUN_USER}"
    echo "NOTE: ${RUN_USER} must re-login for docker group to take effect."
  fi
fi

if fct_prompt_install "Tailscale" ENABLE_TAILSCALE tailscale; then
  echo ">>> Installing Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | sh
  echo ">>> Starting Tailscale..."
  if [[ -z "$TAILSCALE_AUTH_KEY" ]]; then
    tailscale up --accept-routes=false
  else
    tailscale up --accept-routes=false --authkey="$TAILSCALE_AUTH_KEY"
  fi
fi

if fct_prompt_install "SnapRAID" INSTALL_SNAPRAID snapraid; then
  apt-get install -y snapraid
fi

if fct_prompt_install "MergerFS" INSTALL_MERGERFS mergerfs; then
  apt-get install -y mergerfs
  apt-get install -y mergerfs-tools 2>/dev/null || echo ">>> mergerfs-tools not available (optional)"
fi

if fct_prompt_install "smartmontools" INSTALL_SMARTMONTOOLS smartctl; then
  apt-get install -y smartmontools
fi

if fct_prompt_install "SSHFS (seedbox mounts)" INSTALL_SSHFS sshfs; then
  apt-get install -y sshfs sshpass
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

echo ">>> Setting up virtual environment..."
if [[ ! -d "$VENV_DIR" ]]; then
  runuser -u "${RUN_USER}" -- "${PYTHON_BIN}" -m venv "$VENV_DIR"
else
  # Repair environments created by releases that populated the venv as root.
  chown -R --no-dereference "${RUN_USER}:" "$VENV_DIR"
fi

runuser -u "${RUN_USER}" -- "${VENV_DIR}/bin/pip" install --upgrade pip
runuser -u "${RUN_USER}" -- \
  "${VENV_DIR}/bin/pip" install -r "${REPO_DIR}/requirements.txt"

echo ">>> Installing helper service..."
if [[ ! -e "$HELPER_LINK" ]]; then
  ln -s "${REPO_DIR}/pihealth_helper.py" "$HELPER_LINK"
fi

if ! getent group pihealth >/dev/null 2>&1; then
  groupadd pihealth
fi
usermod -aG pihealth "$RUN_USER"
fct_install_legacy_example_stacks

# Create directories required by helper service (ReadWritePaths needs them to exist)
mkdir -p /backups /run/pihealth /etc/sshfs /mnt
touch /etc/.pwd.lock
install -d -m 0750 -o "${RUN_USER}" -g pihealth \
  "${LIMEOS_CONFIG_DIR}" "${LIMEOS_CONFIG_DIR}/storage_plugins" \
  "${LIMEOS_STATE_DIR}" "${LIMEOS_STATE_DIR}/storage_plugins" \
  "${LIMEOS_LOG_DIR}" "${LIMEOS_LOG_DIR}/snapraid" \
  "${CONFIG_DIR}" "${STACKS_PATH}"
# These fixed roots must exist before systemd builds the helper's write sandbox.
# Agent setup assigns their final service ownership when the integration is enabled.
install -d -m 0750 /var/lib/lime-agent /var/lib/limeops

echo ">>> Migrating legacy runtime data..."
"${PYTHON_BIN}" "${REPO_DIR}/scripts/migrate_runtime_state.py" \
  --source-root "${REPO_DIR}" \
  --config-dir "${LIMEOS_CONFIG_DIR}" \
  --state-dir "${LIMEOS_STATE_DIR}" \
  --log-dir "${LIMEOS_LOG_DIR}" \
  --legacy-credentials "${LEGACY_ENV_FILE}" \
  --credentials-file "${CREDENTIALS_FILE}"
LIMEOS_CREDENTIALS_FILE="${CREDENTIALS_FILE}" \
LIMEOS_CREDENTIAL_OWNER="${RUN_USER}" \
LIMEOS_CREDENTIAL_GROUP="pihealth" \
LIMEOS_PYTHON_BIN="${PYTHON_BIN}" \
LIMEOS_PASSWORD_HASH_GENERATOR="${REPO_DIR}/scripts/generate_password_hash.py" \
  "${REPO_DIR}/scripts/onboarding-credentials.sh"
chown -R "${RUN_USER}:pihealth" \
  "${LIMEOS_CONFIG_DIR}" "${LIMEOS_STATE_DIR}" "${LIMEOS_LOG_DIR}"
find "${LIMEOS_CONFIG_DIR}" "${LIMEOS_STATE_DIR}" "${LIMEOS_LOG_DIR}" \
  -type d -exec chmod 0750 {} +
find "${LIMEOS_CONFIG_DIR}" "${LIMEOS_STATE_DIR}" "${LIMEOS_LOG_DIR}" \
  -type f -exec chmod 0640 {} +
install -d -o root -g root -m 0700 "${LIMEOS_STATE_DIR}/integration-recovery"
if [[ -f "${LIMEOS_STATE_DIR}/integration-recovery/mattermost.env" ]]; then
  chown root:root "${LIMEOS_STATE_DIR}/integration-recovery/mattermost.env"
  chmod 0600 "${LIMEOS_STATE_DIR}/integration-recovery/mattermost.env"
fi
if [[ -f "${CREDENTIALS_FILE}" ]]; then
  chown "${RUN_USER}:pihealth" "${CREDENTIALS_FILE}"
  chmod 0640 "${CREDENTIALS_FILE}"
fi

cat > "$HELPER_SERVICE_FILE" <<EOF
[Unit]
Description=Pi-Health Privileged Helper Service
Documentation=https://github.com/Brownster/pi-health
After=local-fs.target
PartOf=pi-health.service

[Service]
Type=simple
Environment=PIHEALTH_REPO_DIR=${REPO_DIR}
ExecStart=/usr/bin/python3 ${HELPER_LINK}
ExecReload=/bin/kill -HUP \$MAINPID
Restart=on-failure
RestartSec=5

# Security hardening
NoNewPrivileges=false
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/etc/fstab /etc/systemd/system /etc/sshfs /mnt /run/pihealth ${LIMEOS_LOG_DIR}
ReadWritePaths=/backups
# Fixed AI-agent provisioning installs Anthropic's signed apt package and owns
# only the runtime paths compiled into the helper command. Account tools run as
# fixed transient units because shadow-utils requires temporary files in /etc.
ReadWritePaths=/etc/apt
ReadWritePaths=/usr /var/lib/apt /var/lib/dpkg /var/cache/apt
ReadWritePaths=-/var/lib/lime-agent -/var/lib/limeops -/run/limeos
ReadWritePaths=-/etc/limeos/integrations/mattermost.env
ReadWritePaths=-/var/lib/limeos/integration-recovery
# Self-update writes to the checkout (git pull, venv pip, npm build) and the
# LimeOS runtime dirs (migration); ProtectHome/ProtectSystem block these
# without explicit write paths.
ReadWritePaths=${REPO_DIR} ${LIMEOS_CONFIG_DIR} ${LIMEOS_STATE_DIR}
PrivateTmp=true

# Socket permissions
RuntimeDirectory=pihealth
RuntimeDirectoryMode=0750
UMask=0007

[Install]
WantedBy=multi-user.target
EOF

echo ">>> Writing systemd service..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Pi-Health Dashboard
After=network.target docker.service pihealth-helper.service
Wants=docker.service
Requires=pihealth-helper.service

[Service]
Type=simple
User=${RUN_USER}
Group=pihealth
WorkingDirectory=${REPO_DIR}
EnvironmentFile=-${CREDENTIALS_FILE}
Environment=DOCKER_COMPOSE_PATH=${DOCKER_COMPOSE_PATH}
Environment=LIMEOS_CONFIG_DIR=${LIMEOS_CONFIG_DIR}
Environment=LIMEOS_STATE_DIR=${LIMEOS_STATE_DIR}
Environment=LIMEOS_LOG_DIR=${LIMEOS_LOG_DIR}
Environment=LIMEOS_CREDENTIALS_FILE=${CREDENTIALS_FILE}
ExecStart=${VENV_DIR}/bin/python ${REPO_DIR}/app.py
Restart=on-failure
RestartSec=3
UMask=0027
ConfigurationDirectory=limeos
ConfigurationDirectoryMode=0750
StateDirectory=limeos
StateDirectoryMode=0750
LogsDirectory=limeos
LogsDirectoryMode=0750

[Install]
WantedBy=multi-user.target
EOF

echo ">>> Installing metric history timer..."
cat > "$METRICS_SERVICE_FILE" <<EOF
[Unit]
Description=LimeOS system metric collector
After=local-fs.target

[Service]
Type=oneshot
User=${RUN_USER}
Group=pihealth
WorkingDirectory=${REPO_DIR}
EnvironmentFile=-${CREDENTIALS_FILE}
Environment=LIMEOS_STATE_DIR=${LIMEOS_STATE_DIR}
ExecStart=${VENV_DIR}/bin/python ${REPO_DIR}/metric_collector.py
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
ReadWritePaths=${LIMEOS_STATE_DIR}
UMask=0027
StateDirectory=limeos
StateDirectoryMode=0750

[Install]
WantedBy=multi-user.target
EOF

cat > "$METRICS_TIMER_FILE" <<EOF
[Unit]
Description=Collect LimeOS system metrics every five minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s
RandomizedDelaySec=15s
Persistent=true
Unit=limeos-metrics-collector.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now pihealth-helper.service
systemctl enable --now pi-health.service
systemctl enable --now limeos-metrics-collector.timer

if [[ ! -x "${INSTALL_CHECK_SCRIPT}" ]]; then
  printf 'Installation verifier is missing or not executable: %s\n' \
    "${INSTALL_CHECK_SCRIPT}" >&2
  exit 2
fi

install_check_args=()
if [[ "${INSTALL_DOCKER}" == "0" ]]; then
  install_check_args+=("--skip-docker")
fi

echo ">>> Verifying installed services..."
"${INSTALL_CHECK_SCRIPT}" "${install_check_args[@]}"

echo ">>> Pi-Health is running."
echo "Open: http://$(hostname -I | awk '{print $1}'):8002"
echo "Credentials: ${CREDENTIALS_FILE}"
echo "Helper service: pihealth-helper.service"
echo "Metrics timer: limeos-metrics-collector.timer"
echo
echo "Recovery commands:"
echo "  sudo systemctl status pihealth-helper.service pi-health.service --no-pager"
echo "  sudo journalctl -u pihealth-helper.service -u pi-health.service -n 100 --no-pager"
echo "  sudo systemctl restart pihealth-helper.service pi-health.service"
echo "  sudo ${INSTALL_CHECK_SCRIPT}${install_check_args[*]:+ ${install_check_args[*]}}"
