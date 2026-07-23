"""Fixed paths and helper-owned systemd templates for the AA-004 sandbox."""

from __future__ import annotations

AGENT_CONFIG_PATH = "/etc/limeos/integrations/agents.json"
AGENT_ENV_PATH = "/etc/limeos/integrations/agents.env"
AGENT_POLICY_PATH = "/etc/limeos/agent-policy.json"
AGENT_STATE_DIR = "/var/lib/lime-agent/state"
CLAUDE_CONFIG_DIR = "/var/lib/lime-agent/.claude"
AGENT_LIB_DIR = "/usr/lib/limeos-agent"
AGENT_VENV_DIR = "/var/lib/lime-agent/venv"
LIMEOPS_SOCKET_DIR = "/run/limeos"
LIMEOPS_SOCKET_PATH = "/run/limeos/limeops.sock"
LIMEOPS_STATE_DIR = "/var/lib/limeops"
LIMEOPS_AUDIT_PATH = "/var/log/limeos/agent-audit.jsonl"
ACTION_POLICY_PATH = "/etc/limeos/agent-action-policy.json"
ACTION_BROKER_POLICY_PATH = "/etc/limeos/agent-actuator-policy.json"
ACTION_STATE_DIR = "/var/lib/limeos/agent-actions"
ACTION_SOCKET_DIR = "/run/limeos-actions"
ACTION_SOCKET_PATH = "/run/limeos-actions/actions.sock"
ACTION_AUDIT_PATH = "/var/log/limeos/agent-action-audit.jsonl"
REPORT_SCHEDULER_STATE_DIR = "/var/lib/limeops-report"
REPORT_SCHEDULER_VENV_DIR = f"{REPORT_SCHEDULER_STATE_DIR}/venv"
REPORT_SCHEDULER_UNIT_PATH = "/etc/systemd/system/limeops-report-scheduler.service"
REPORT_DELIVERY_CONFIG_DIR = "/etc/limeos/integrations/agent-report"
REPORT_MATTERMOST_WEBHOOK_PATH = f"{REPORT_DELIVERY_CONFIG_DIR}/mattermost-webhook.env"
SUPERVISOR_STATE_DIR = "/var/lib/limeos/agent-supervisor"
SUPERVISOR_VENV_DIR = f"{SUPERVISOR_STATE_DIR}/venv"
SUPERVISOR_CONFIG_DIR = "/etc/limeos/integrations/agent-supervisor"
SUPERVISOR_DELIVERY_CONFIG_PATH = f"{SUPERVISOR_CONFIG_DIR}/delivery.json"
SUPERVISOR_MATTERMOST_ENV_PATH = f"{SUPERVISOR_CONFIG_DIR}/mattermost.env"
SUPERVISOR_UNIT_PATH = (
    "/etc/systemd/system/limeops-supervised-repair.service"
)
STACK_LOCK_DIR = "/opt/stacks/.locks"
AGENT_UNIT_PATH = "/etc/systemd/system/limeos-agent.service"
LIMEOPS_UNIT_PATH = "/etc/systemd/system/limeopsd.service"
ACTION_BROKER_UNIT_PATH = "/etc/systemd/system/limeops-actuatord.service"
ACTION_WORKER_UNIT_PATH = "/etc/systemd/system/limeops-action-worker.service"
AGENT_REPAIR_UNIT_PATH = "/etc/systemd/system/limeos-agent-repair.service"
EXTENSION_REPAIR_UNIT_PATH = "/etc/systemd/system/limeos-extension-repair@.service"
MATTERMOST_REPAIR_UNIT_PATH = "/etc/systemd/system/limeos-mattermost-repair.service"

AGENT_RUNTIME_PACKAGES = (
    "agent_actions",
    "agent_automation",
    "agent_findings",
    "agent_gateway",
    "agent_provider",
    "agent_runtime",
    "agent_supervision",
    "agent_transport",
    "limeops",
)
AGENT_RUNTIME_MODULES = (
    "container_operations_service.py",
    "helper_client.py",
    "ports.py",
    "runtime_paths.py",
    "stack_operations_service.py",
    "stack_read_service.py",
)


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
InaccessiblePaths=/root {repo_dir} /run/pihealth -{ACTION_SOCKET_DIR} /var/run/docker.sock /etc/limeos/credentials.env
CapabilityBoundingSet=
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
"""


def render_limeops_unit(repo_dir: str) -> str:
    return f"""[Unit]
Description=LimeOS read-only operations broker
After=docker.service pihealth-helper.service

[Service]
Type=simple
User=limeops
Group=limeops
SupplementaryGroups=docker pihealth limeops-client
RuntimeDirectory=limeos
RuntimeDirectoryMode=0750
WorkingDirectory={LIMEOPS_STATE_DIR}
Environment=PYTHONPATH={AGENT_LIB_DIR}
ExecStart=/usr/bin/python3 -m limeops.server --policy {AGENT_POLICY_PATH} --audit {LIMEOPS_AUDIT_PATH} --group limeops-client
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
ReadOnlyPaths={AGENT_LIB_DIR} {AGENT_POLICY_PATH}
ReadWritePaths={LIMEOPS_SOCKET_DIR} /var/log/limeos {ACTION_STATE_DIR}
InaccessiblePaths=/root {repo_dir} /run/pihealth /etc/limeos/credentials.env
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
"""


def render_action_broker_unit(repo_dir: str) -> str:
    return f"""[Unit]
Description=LimeOS isolated action broker
After=docker.service

[Service]
Type=simple
User=limeops-actuator
Group=limeops-actuator
SupplementaryGroups=docker pihealth limeops-action
RuntimeDirectory=limeos-actions
RuntimeDirectoryMode=0750
WorkingDirectory={ACTION_STATE_DIR}
Environment=PYTHONPATH={AGENT_LIB_DIR}
ExecStart=/usr/bin/python3 -m agent_actions.server --socket {ACTION_SOCKET_PATH} --broker-policy {ACTION_BROKER_POLICY_PATH} --action-policy {ACTION_POLICY_PATH} --ledger {ACTION_STATE_DIR}/actions.sqlite3 --audit {ACTION_AUDIT_PATH} --group limeops-action
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
RestrictAddressFamilies=AF_UNIX
ReadOnlyPaths={AGENT_LIB_DIR} {ACTION_POLICY_PATH} {ACTION_BROKER_POLICY_PATH}
ReadWritePaths={ACTION_SOCKET_DIR} {ACTION_STATE_DIR} /var/log/limeos {STACK_LOCK_DIR}
InaccessiblePaths=/root {repo_dir} /run/pihealth /etc/limeos/credentials.env
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
"""


def render_action_worker_unit(repo_dir: str) -> str:
    return f"""[Unit]
Description=LimeOS authorised action queue worker
After=limeops-actuatord.service
Requires=limeops-actuatord.service

[Service]
Type=simple
User=limeops-action-worker
Group=limeops-action-worker
SupplementaryGroups=pihealth limeops-action
WorkingDirectory={ACTION_STATE_DIR}
Environment=PYTHONPATH={AGENT_LIB_DIR}
ExecStart=/usr/bin/python3 -m agent_actions.worker --socket {ACTION_SOCKET_PATH} --ledger {ACTION_STATE_DIR}/actions.sqlite3
Restart=on-failure
RestartSec=5
UMask=0007
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
RestrictAddressFamilies=AF_UNIX
ReadOnlyPaths={AGENT_LIB_DIR}
ReadWritePaths={ACTION_STATE_DIR}
InaccessiblePaths=/root {repo_dir} /run/pihealth /var/run/docker.sock /etc/limeos/credentials.env
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
"""


def render_report_scheduler_unit(repo_dir: str) -> str:
    return f"""[Unit]
Description=LimeOS report-only automation scheduler
After=network-online.target limeopsd.service
Wants=network-online.target
Requires=limeopsd.service

[Service]
Type=simple
User=limeops-report
Group=limeops-report
SupplementaryGroups=limeops-client pihealth
WorkingDirectory={REPORT_SCHEDULER_STATE_DIR}
Environment=PYTHONPATH={AGENT_LIB_DIR}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart={REPORT_SCHEDULER_VENV_DIR}/bin/python -m agent_automation.runner
Restart=on-failure
RestartSec=5
UMask=0007
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
ReadOnlyPaths={AGENT_LIB_DIR} -{REPORT_MATTERMOST_WEBHOOK_PATH}
ReadWritePaths={ACTION_STATE_DIR}
InaccessiblePaths=/root {repo_dir} /run/pihealth {ACTION_SOCKET_DIR} /var/run/docker.sock /etc/limeos/credentials.env
CapabilityBoundingSet=
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
"""


def render_supervisor_unit(repo_dir: str) -> str:
    """Render the model-free supervised repair boundary."""
    return f"""[Unit]
Description=LimeOS model-free supervised repair scheduler
After=network-online.target limeopsd.service limeops-action-worker.service
Wants=network-online.target
Requires=limeopsd.service limeops-action-worker.service

[Service]
Type=simple
User=limeops-supervisor
Group=limeops-supervisor
SupplementaryGroups=limeops-client pihealth
WorkingDirectory={SUPERVISOR_STATE_DIR}
Environment=PYTHONPATH={AGENT_LIB_DIR}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart={SUPERVISOR_VENV_DIR}/bin/python -m agent_supervision.runner
Restart=on-failure
RestartSec=5
UMask=0007
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
ReadOnlyPaths={AGENT_LIB_DIR} {ACTION_POLICY_PATH} {SUPERVISOR_DELIVERY_CONFIG_PATH} {SUPERVISOR_MATTERMOST_ENV_PATH}
ReadWritePaths={ACTION_STATE_DIR}
InaccessiblePaths=/root {repo_dir} /run/pihealth {ACTION_SOCKET_DIR} /var/run/docker.sock /etc/limeos/credentials.env {AGENT_ENV_PATH}
CapabilityBoundingSet=
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
"""


def render_agent_repair_unit(repo_dir: str) -> str:
    """Render the fixed, helper-backed AI Agents repair job."""
    exec_start = (
        "/usr/bin/python3 -c "
        "'import sys; from helper_client import helper_call; "
        'sys.exit(0 if (helper_call("agent_integration_repair", {}, timeout=1800) '
        'or {}).get("success") else 1)\''
    )
    return f"""[Unit]
Description=LimeOS approved AI Agents integration repair
After=network-online.target pihealth-helper.service
Wants=network-online.target
Requires=pihealth-helper.service

[Service]
Type=oneshot
User=limeops-action-worker
Group=limeops-action-worker
SupplementaryGroups=pihealth
WorkingDirectory={ACTION_STATE_DIR}
Environment=PYTHONPATH={AGENT_LIB_DIR}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart={exec_start}
TimeoutStartSec=1800
UMask=0077
Nice=19
IOSchedulingClass=idle
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
RestrictAddressFamilies=AF_UNIX
ReadOnlyPaths={AGENT_LIB_DIR}
InaccessiblePaths=/root {repo_dir} /var/run/docker.sock /etc/limeos/credentials.env
CapabilityBoundingSet=
SystemCallArchitectures=native
"""


def render_extension_repair_unit(repo_dir: str, user: str) -> str:
    """Render the instance job that repairs one policy-allowlisted extension."""
    python_bin = f"{repo_dir}/.venv/bin/python"
    return f"""[Unit]
Description=LimeOS approved extension repair for %i
After=network-online.target pihealth-helper.service
Wants=network-online.target
Requires=pihealth-helper.service

[Service]
Type=oneshot
User={user}
SupplementaryGroups=pihealth
WorkingDirectory={repo_dir}
Environment=PYTHONPATH={repo_dir}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart={python_bin} -m agent_actions.repair_job extension-repair --name %i
TimeoutStartSec=1800
UMask=0007
Nice=19
IOSchedulingClass=idle
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX
ReadOnlyPaths={repo_dir}
ReadWritePaths={repo_dir}/plugins /etc/limeos
InaccessiblePaths=/root /etc/limeos/credentials.env /run/limeos-actions /var/run/docker.sock
CapabilityBoundingSet=
SystemCallArchitectures=native
"""


def render_mattermost_repair_unit(repo_dir: str, user: str) -> str:
    """Render the fixed job that invokes the Mattermost integration service."""
    python_bin = f"{repo_dir}/.venv/bin/python"
    return f"""[Unit]
Description=LimeOS approved Mattermost integration repair
After=network-online.target docker.service pihealth-helper.service
Wants=network-online.target
Requires=docker.service pihealth-helper.service

[Service]
Type=oneshot
User={user}
SupplementaryGroups=docker pihealth
WorkingDirectory={repo_dir}
Environment=PYTHONPATH={repo_dir}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart={python_bin} -m agent_actions.repair_job mattermost-repair
TimeoutStartSec=1800
UMask=0007
Nice=19
IOSchedulingClass=idle
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
PrivateDevices=false
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadOnlyPaths={repo_dir} /etc/limeos
InaccessiblePaths=/root /etc/limeos/credentials.env /run/limeos-actions
CapabilityBoundingSet=
SystemCallArchitectures=native
"""
