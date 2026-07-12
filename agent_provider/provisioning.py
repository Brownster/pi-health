"""Fixed paths and helper-owned systemd templates for the AA-004 sandbox."""

from __future__ import annotations

AGENT_CONFIG_PATH = "/etc/limeos/integrations/agents.json"
AGENT_ENV_PATH = "/etc/limeos/integrations/agents.env"
AGENT_POLICY_PATH = "/etc/limeos/agent-policy.json"
AGENT_STATE_DIR = "/var/lib/limeos/integrations/agents"
CLAUDE_CONFIG_DIR = "/var/lib/lime-agent/.claude"
AGENT_LIB_DIR = "/usr/lib/limeos-agent"
AGENT_VENV_DIR = "/var/lib/lime-agent/venv"
LIMEOPS_SOCKET_DIR = "/run/limeos"
LIMEOPS_AUDIT_PATH = "/var/log/limeos/agent-audit.jsonl"
AGENT_UNIT_PATH = "/etc/systemd/system/limeos-agent.service"
LIMEOPS_UNIT_PATH = "/etc/systemd/system/limeopsd.service"


def render_agent_unit(repo_dir: str, python_bin: str) -> str:
    return f"""[Unit]
Description=LimeOS provider-neutral Mattermost assistant
After=network-online.target limeopsd.service
Wants=network-online.target
Requires=limeopsd.service

[Service]
Type=simple
User=lime-agent
Group=lime-agent
SupplementaryGroups=limeops-client
WorkingDirectory={AGENT_STATE_DIR}
Environment=PYTHONPATH={AGENT_LIB_DIR}
Environment=CLAUDE_CONFIG_DIR={CLAUDE_CONFIG_DIR}
Environment=HOME=/var/lib/lime-agent
EnvironmentFile={AGENT_ENV_PATH}
LoadCredential=agent-settings:{AGENT_CONFIG_PATH}
Environment=LIMEOS_AGENT_CONFIG=%d/agent-settings
ExecStart={AGENT_VENV_DIR}/bin/python -m agent_runtime
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadOnlyPaths={AGENT_LIB_DIR}
ReadWritePaths={AGENT_STATE_DIR} {CLAUDE_CONFIG_DIR}
InaccessiblePaths=/root {repo_dir} /run/pihealth /var/run/docker.sock /etc/limeos/credentials.env
CapabilityBoundingSet=
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
"""


def render_limeops_unit(repo_dir: str, python_bin: str) -> str:
    return f"""[Unit]
Description=LimeOS read-only operations broker
After=docker.service pihealth-helper.service

[Service]
Type=simple
User=limeops
Group=limeops
SupplementaryGroups=docker pihealth
RuntimeDirectory=limeos
RuntimeDirectoryMode=0750
WorkingDirectory={repo_dir}
Environment=PYTHONPATH={repo_dir}
ExecStart={python_bin} -m limeops.server --policy {AGENT_POLICY_PATH} --audit {LIMEOPS_AUDIT_PATH} --group limeops-client
Restart=on-failure
RestartSec=5
UMask=0007
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=false
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadOnlyPaths={repo_dir} {AGENT_POLICY_PATH}
ReadWritePaths={LIMEOPS_SOCKET_DIR} /var/log/limeos
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
"""
