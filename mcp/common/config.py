from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def load_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Load a secret from ``NAME`` or ``NAME_FILE`` environment variables."""
    file_var = os.getenv(f"{name}_FILE")
    if file_var:
        path = Path(file_var)
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    value = os.getenv(name)
    if value is not None:
        return value.strip()
    return default


def load_base_url(name: str, default: str) -> str:
    return (os.getenv(name) or default).rstrip("/")


def load_timeout(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
