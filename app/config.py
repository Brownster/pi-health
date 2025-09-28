from __future__ import annotations

import os


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


class Config:
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    OPENAI_API_MODEL = os.getenv('OPENAI_API_MODEL', 'gpt-4o-mini')
    DISK_PATH = os.getenv('DISK_PATH', '/')
    DISK_PATH_2 = os.getenv('DISK_PATH_2', '/mnt/backup')
    ENABLE_SYSTEM_ACTIONS = _env_bool('ENABLE_SYSTEM_ACTIONS', True)
    APPROVAL_AUDIT_LOG = os.getenv('APPROVAL_AUDIT_LOG', 'logs/ops_copilot_approvals.log')
    DOCKER_MCP_BASE_URL = os.getenv('DOCKER_MCP_BASE_URL')
    DOCKER_MCP_COMPOSE_FILE = os.getenv('DOCKER_MCP_COMPOSE_FILE')
    SONARR_MCP_BASE_URL = os.getenv('SONARR_MCP_BASE_URL')
    SABNZBD_MCP_BASE_URL = os.getenv('SABNZBD_MCP_BASE_URL')
    MCP_READ_TIMEOUT = _env_float('MCP_READ_TIMEOUT', 5.0)
    MCP_WRITE_TIMEOUT = _env_float('MCP_WRITE_TIMEOUT', 30.0)

    # Placeholders for future rate limiting configuration (Phase 4+)
    RATE_LIMITS_CHAT = os.getenv('RATE_LIMITS_CHAT')
    RATE_LIMITS_APPROVE = os.getenv('RATE_LIMITS_APPROVE')
