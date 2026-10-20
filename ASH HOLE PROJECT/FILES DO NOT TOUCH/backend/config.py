"""Environment-driven settings for the Central Channel service."""

from __future__ import annotations

import os
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = Path(os.environ.get("CENTRAL_DATABASE_PATH", WORKSPACE_ROOT / "data" / "central-channel.sqlite3"))
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = WORKSPACE_ROOT / DATABASE_PATH

HOST = os.environ.get("CENTRAL_HOST", "127.0.0.1")
PORT = int(os.environ.get("CENTRAL_PORT", "8000"))
SESSION_TTL_HOURS = int(os.environ.get("CENTRAL_SESSION_TTL_HOURS", "12"))
ALLOWED_ORIGINS = tuple(
    origin.strip()
    for origin in os.environ.get("CENTRAL_ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
)
EXTERNAL_API_BASE = os.environ.get("CENTRAL_EXTERNAL_API_BASE", "")