"""Supabase Auth requests and bearer-token profile lookup."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import config


class SupabaseAuthError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _auth_request(path: str, method: str = "GET", body: dict[str, Any] | None = None,
                  access_token: str = "", admin: bool = False) -> dict[str, Any]:
    key = config.SUPABASE_SECRET_KEY if admin else config.SUPABASE_PUBLISHABLE_KEY
    if not config.SUPABASE_URL or not key:
        raise SupabaseAuthError(503, "Supabase Auth is not configured on the server.")
    headers = {"Accept": "application/json", "apikey": key}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    elif admin:
        headers["Authorization"] = f"Bearer {key}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(f"{config.SUPABASE_URL}/auth/v1/{path.lstrip('/')}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            response_body = response.read()
    except HTTPError as error:
        try:
            payload = json.loads(error.read())
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        message = payload.get("msg") or payload.get("message") or payload.get("error_description") or "Supabase Auth rejected the request."
        raise SupabaseAuthError(error.code, str(message)) from None
    except (URLError, TimeoutError):
        raise SupabaseAuthError(503, "Supabase Auth could not be reached.") from None
    if not response_body:
        return {}
    try:
        payload = json.loads(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SupabaseAuthError(502, "Supabase Auth returned an invalid response.") from None
    if not isinstance(payload, dict):
        raise SupabaseAuthError(502, "Supabase Auth returned an invalid response.")
    return payload


def register(email: str, password: str, username: str, display_name: str) -> dict[str, Any]:
    return _auth_request("signup", method="POST", body={
        "email": email,
        "password": password,
        "data": {"username": username, "display_name": display_name},
    })


def verify_signup_email(email: str, token: str) -> dict[str, Any]:
    return _auth_request("verify", method="POST", body={
        "email": email,
        "token": token,
        "type": "signup",
    })


def resend_signup_email(email: str) -> dict[str, Any]:
    return _auth_request("resend", method="POST", body={
        "email": email,
        "type": "signup",
    })


def create_user(email: str, password: str, username: str, display_name: str) -> dict[str, Any]:
    return _auth_request("admin/users", method="POST", admin=True, body={
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": {"username": username, "display_name": display_name},
    })


def delete_user(user_id: str) -> None:
    _auth_request(f"admin/users/{user_id}", method="DELETE", admin=True)


def sign_in(email: str, password: str) -> dict[str, Any]:
    return _auth_request("token?grant_type=password", method="POST", body={"email": email, "password": password})

def refresh_session(refresh_token: str) -> dict[str, Any]:
    return _auth_request("token?grant_type=refresh_token", method="POST", body={"refresh_token": refresh_token})

def find_session_user(connection: Any, token: str) -> dict[str, Any] | None:
    try:
        auth_user = _auth_request("user", access_token=token)
    except SupabaseAuthError as error:
        expired_jwt = error.status == 403 and "invalid jwt" in str(error).lower() and "token is expired" in str(error).lower()
        if error.status == 401 or expired_jwt:
            return None
        raise
    user_id = auth_user.get("id")
    if not user_id:
        return None
    return connection.execute(
        """SELECT Users.id, Users.username, Users.email, Users.display_name, Users.role,
                  Personnel.department, Personnel.active AS personnel_active
           FROM Users
           LEFT JOIN Personnel ON Personnel.user_id = Users.id
           WHERE Users.id = ? AND Users.active = 1""",
        (user_id,),
    ).fetchone()


def revoke_session(connection: Any, token: str) -> None:
    del connection
    try:
        _auth_request("logout?scope=local", method="POST", access_token=token)
    except SupabaseAuthError as error:
        if error.status != 401:
            raise