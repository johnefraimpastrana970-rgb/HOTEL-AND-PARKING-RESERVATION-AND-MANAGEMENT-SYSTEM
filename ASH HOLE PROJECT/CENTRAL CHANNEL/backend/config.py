"""Environment-driven settings for the local Central Channel service."""

from __future__ import annotations

import os
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
SUPABASE_DATABASE_URL = os.environ.get("SUPABASE_DATABASE_URL", "")
SUPABASE_DATABASE_SCHEMA = os.environ.get("SUPABASE_DATABASE_SCHEMA", "public")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
HOST = os.environ.get("CENTRAL_HOST", "127.0.0.1")
PORT = int(os.environ.get("CENTRAL_PORT", "8000"))
SESSION_TTL_HOURS = int(os.environ.get("CENTRAL_SESSION_TTL_HOURS", "12"))
FIRST_SIGNUP_ADMIN = os.environ.get("CENTRAL_FIRST_SIGNUP_ADMIN", "1").lower() in {"1", "true", "yes"}
ALLOWED_ORIGINS = tuple(item.strip() for item in os.environ.get("CENTRAL_ALLOWED_ORIGINS", "*").split(",") if item.strip())
EXTERNAL_API_BASE = os.environ.get("CENTRAL_EXTERNAL_API_BASE", "")