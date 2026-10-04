"""Password hashing and opaque bearer-session management."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from . import config


PASSWORD_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def issue_session(connection: sqlite3.Connection, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=config.SESSION_TTL_HOURS)
    connection.execute("DELETE FROM Sessions WHERE expires_at <= ?", (datetime.now(timezone.utc).isoformat(),))
    connection.execute(
        "INSERT INTO Sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (token_hash, user_id, expires_at.isoformat()),
    )
    return token


def find_session_user(connection: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    return connection.execute(
        """SELECT Users.id, Users.username, Users.email, Users.display_name, Users.role,
                  Personnel.department, Personnel.active AS personnel_active
           FROM Sessions JOIN Users ON Users.id = Sessions.user_id
           LEFT JOIN Personnel ON Personnel.user_id = Users.id
           WHERE Sessions.token_hash = ? AND Sessions.expires_at > ? AND Users.active = 1""",
        (token_hash, now),
    ).fetchone()


def revoke_session(connection: sqlite3.Connection, token: str) -> None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    connection.execute("DELETE FROM Sessions WHERE token_hash = ?", (token_hash,))