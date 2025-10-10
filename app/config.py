from __future__ import annotations

import os
import secrets


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
    # Flask Session Configuration
    SECRET_KEY = os.getenv('SECRET_KEY', secrets.token_hex(32))
    PERMANENT_SESSION_LIFETIME = 86400  # 24 hours in seconds

    # Core OpenAI Configuration
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    OPENAI_API_MODEL = os.getenv('OPENAI_API_MODEL', 'gpt-4o-mini')

    # AI Agent Control - disabled by default to save resources
    ENABLE_AI_AGENT = _env_bool('ENABLE_AI_AGENT', False)

    # System Monitoring Paths
    DISK_PATH = os.getenv('DISK_PATH', '/')
    DISK_PATH_2 = os.getenv('DISK_PATH_2', '/mnt/backup')

    # System Actions (disabled by default for security)
    ENABLE_SYSTEM_ACTIONS = _env_bool('ENABLE_SYSTEM_ACTIONS', False)

    # Logging and Audit
    APPROVAL_AUDIT_LOG = os.getenv('APPROVAL_AUDIT_LOG', 'logs/ops_copilot_approvals.log')

    # AI Agent Features
    ENABLE_LEGACY_SUGGESTIONS = _env_bool('ENABLE_LEGACY_SUGGESTIONS', True)

    # MCP Service URLs (optional - only loaded if ENABLE_AI_AGENT is True)
    DOCKER_MCP_BASE_URL = os.getenv('DOCKER_MCP_BASE_URL')
    DOCKER_MCP_COMPOSE_FILE = os.getenv('DOCKER_MCP_COMPOSE_FILE', 'docker-compose.yml')
    SONARR_MCP_BASE_URL = os.getenv('SONARR_MCP_BASE_URL')
    RADARR_MCP_BASE_URL = os.getenv('RADARR_MCP_BASE_URL')
    LIDARR_MCP_BASE_URL = os.getenv('LIDARR_MCP_BASE_URL')
    SABNZBD_MCP_BASE_URL = os.getenv('SABNZBD_MCP_BASE_URL')
    JELLYFIN_MCP_BASE_URL = os.getenv('JELLYFIN_MCP_BASE_URL')
    JELLYSEERR_MCP_BASE_URL = os.getenv('JELLYSEERR_MCP_BASE_URL')

    # MCP Service Timeouts
    MCP_READ_TIMEOUT = _env_float('MCP_READ_TIMEOUT', 5.0)
    MCP_WRITE_TIMEOUT = _env_float('MCP_WRITE_TIMEOUT', 30.0)

    # Placeholders for future rate limiting configuration (Phase 4+)
    RATE_LIMITS_CHAT = os.getenv('RATE_LIMITS_CHAT')
    RATE_LIMITS_APPROVE = os.getenv('RATE_LIMITS_APPROVE')
