"""Supabase PostgreSQL-backed Central Channel REST API and static web host."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from getpass import getpass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import pg8000

from . import config, database, security

ROLE_FOR = {"Hotel": "Hotel Personnel", "Parking": "Parking Personnel"}
TABLE_FOR = {"Hotel": "HotelBookings", "Parking": "ParkingBookings"}
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_@*]{1,32}\Z")
EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+\Z")


class APIError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def require(body: dict[str, Any], *fields: str) -> None:
    missing = [key for key in fields if not str(body.get(key, "")).strip()]
    if missing:
        raise APIError(400, f"Required fields: {', '.join(missing)}")


def validate_username(value: Any, allow_email: bool = False) -> str:
    username = str(value).strip()
    if USERNAME_PATTERN.fullmatch(username) or (allow_email and EMAIL_PATTERN.fullmatch(username)):
        return username
    raise APIError(400, "Username may contain only letters, numbers, underscore, asterisk, and at-sign.")


def actor_for(connection: database.DatabaseConnection, handler: "CentralHandler") -> dict[str, Any]:
    authorization = handler.headers.get("Authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    user = security.find_session_user(connection, token) if token else None
    if not user:
        raise APIError(401, "Sign in to continue.")
    return dict(user)


def manages(actor: dict[str, Any], booking_type: str) -> bool:
    return actor["role"] == "Admin" or actor["role"] == ROLE_FOR[booking_type]


def booking_row(connection: database.DatabaseConnection, booking_type: str, booking_id: str) -> dict[str, Any]:
    row = connection.execute(f"SELECT * FROM {TABLE_FOR[booking_type]} WHERE id = ?", (booking_id,)).fetchone()
    if not row:
        raise APIError(404, "Reservation not found.")
    return row


def serialize(connection: database.DatabaseConnection, booking_type: str, row: dict[str, Any]) -> dict[str, Any]:
    owner = connection.execute("SELECT display_name,email FROM Users WHERE id = ?", (row["user_id"],)).fetchone()
    guest_name = row["guest_name"] if "guest_name" in row.keys() else owner["display_name"]
    guest_email = row["guest_email"] if "guest_email" in row.keys() else owner["email"]
    assigned = connection.execute("SELECT display_name FROM Users WHERE id = ?", (row["assigned_personnel_id"],)).fetchone()
    result: dict[str, Any] = {
        "id": row["id"], "type": booking_type, "userId": row["user_id"], "name": guest_name,
        "email": guest_email, "phone": row["guest_phone"] if "guest_phone" in row.keys() else "",
        "property": row["property_name"], "status": row["status"],
        "assigned": assigned["display_name"] if assigned else "Unassigned",
        "assignedPersonnelId": row["assigned_personnel_id"], "notes": row["notes"],
        "internalNotes": row["internal_notes"], "requestedAt": row["created_at"], "updatedAt": row["updated_at"],
    }
    if booking_type == "Hotel":
        room = connection.execute("SELECT * FROM Rooms WHERE id = ?", (row["room_id"],)).fetchone()
        result.update({
            "roomType": row["room_type"], "checkIn": row["check_in"], "checkOut": row["check_out"],
            "guests": row["guest_count"], "room": f"Room {room['room_number']}" if room else "",
            "roomId": row["room_id"],
        })
    else:
        vehicle = connection.execute("SELECT * FROM Vehicles WHERE id = ?", (row["vehicle_id"],)).fetchone()
        slot = connection.execute("SELECT * FROM ParkingSlots WHERE id = ?", (row["parking_slot_id"],)).fetchone()
        start, end = datetime.fromisoformat(row["start_at"]), datetime.fromisoformat(row["end_at"])
        result.update({
            "vehicle": vehicle["vehicle_type"], "plate": vehicle["plate_number"],
            "parkingDate": start.date().isoformat(), "parkingTime": start.strftime("%H:%M"),
            "duration": f"{max(1, round((end - start).total_seconds() / 3600))} hours",
            "parkingSlot": slot["slot_code"] if slot else "", "slot": slot["slot_code"] if slot else "",
            "slotId": row["parking_slot_id"],
        })
    return result


def history(connection: database.DatabaseConnection, booking_type: str, booking_id: str, actor_id: str | None,
             action: str, old_status: str | None, new_status: str | None, details: str) -> None:
    connection.execute(
        """INSERT INTO BookingHistory(booking_type,booking_id,actor_user_id,action,old_status,new_status,details,created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (booking_type, booking_id, actor_id, action, old_status, new_status, details, now()),
    )


def notification(connection: database.DatabaseConnection, booking_type: str, booking_id: str, category: str,
                  title: str, message: str, user_id: str) -> None:
    connection.execute(
        """INSERT INTO Notifications(id,recipient_user_id,audience_role,category,booking_type,booking_id,title,message,created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), user_id, ROLE_FOR[booking_type], category, booking_type, booking_id, title, message, now()),
    )


def make_booking(connection: database.DatabaseConnection, actor: dict[str, Any], booking_type: str,
                 body: dict[str, Any]) -> dict[str, Any]:
    if actor["role"] not in {"User", "Admin", ROLE_FOR[booking_type]}:
        raise APIError(403, "Your role cannot create this reservation type.")
    require(body, "name", "email", "property")
    stamp = now()
    booking_id = f"{'HTL' if booking_type == 'Hotel' else 'PKG'}-{secrets.token_hex(3).upper()}"
    if booking_type == "Hotel":
        require(body, "roomType", "checkIn", "checkOut")
        try:
            check_in, check_out = date.fromisoformat(body["checkIn"]), date.fromisoformat(body["checkOut"])
            guests = int(body.get("guests", 1))
        except (TypeError, ValueError):
            raise APIError(400, "Enter valid hotel dates and guest count.") from None
        if check_out <= check_in or not 1 <= guests <= 16:
            raise APIError(400, "Check-out must follow check-in and guests must be between 1 and 16.")
        connection.execute(
            """INSERT INTO HotelBookings(id,user_id,property_name,guest_name,guest_email,guest_phone,room_type,
               check_in,check_out,guest_count,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (booking_id, actor["id"], body["property"], body["name"], body["email"], body.get("phone", ""),
             body["roomType"], check_in.isoformat(), check_out.isoformat(), guests, body.get("notes", ""), stamp, stamp),
        )
    else:
        require(body, "vehicle", "plate", "parkingDate", "parkingTime")
        try:
            start = datetime.combine(date.fromisoformat(body["parkingDate"]), time.fromisoformat(body["parkingTime"])).replace(tzinfo=timezone.utc)
            hours = float(body.get("durationHours", 1))
        except (TypeError, ValueError):
            raise APIError(400, "Enter a valid parking date, time, and duration.") from None
        if not 0 < hours <= 168:
            raise APIError(400, "Parking duration must be between 1 hour and 7 days.")
        plate = str(body["plate"]).strip().upper()
        vehicle = connection.execute("SELECT * FROM Vehicles WHERE plate_number = ?", (plate,)).fetchone()
        if vehicle and vehicle["owner_user_id"] != actor["id"]:
            raise APIError(409, "That vehicle plate is registered to another account.")
        if vehicle:
            vehicle_id = vehicle["id"]
            connection.execute("UPDATE Vehicles SET vehicle_type = ? WHERE id = ?", (body["vehicle"], vehicle_id))
        else:
            vehicle_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO Vehicles(id,owner_user_id,vehicle_type,plate_number,created_at) VALUES(?,?,?,?,?)",
                (vehicle_id, actor["id"], body["vehicle"], plate, stamp),
            )
        connection.execute(
            """INSERT INTO ParkingBookings(id,user_id,vehicle_id,property_name,start_at,end_at,notes,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (booking_id, actor["id"], vehicle_id, body["property"], start.isoformat(),
             (start + timedelta(hours=hours)).isoformat(), body.get("notes", ""), stamp, stamp),
        )
    history(connection, booking_type, booking_id, actor["id"], "created", None, "Pending", "Customer submitted a request.")
    notification(connection, booking_type, booking_id, "new_request", "New booking request",
                 f"{body['name']} submitted a {booking_type.lower()} request.", actor["id"])
    return serialize(connection, booking_type, booking_row(connection, booking_type, booking_id))


def available_resource(connection: database.DatabaseConnection, booking_type: str, booking: dict[str, Any],
                       requested_id: str | None = None) -> dict[str, Any]:
    if booking_type == "Hotel":
        condition = "AND Rooms.id = ?" if requested_id else ""
        params: list[Any] = [requested_id] if requested_id else []
        params.extend([booking["id"], booking["check_out"], booking["check_in"]])
        row = connection.execute(
            f"""SELECT Rooms.* FROM Rooms WHERE status != 'Maintenance' {condition}
               AND NOT EXISTS(SELECT 1 FROM HotelBookings AS other WHERE other.room_id = Rooms.id
               AND other.id != ? AND other.status IN ('Approved','Checked In') AND other.check_in < ? AND other.check_out > ?)
               ORDER BY room_number LIMIT 1""", params,
        ).fetchone()
    else:
        condition = "AND ParkingSlots.id = ?" if requested_id else ""
        params = [requested_id] if requested_id else []
        params.extend([booking["id"], booking["end_at"], booking["start_at"]])
        row = connection.execute(
            f"""SELECT ParkingSlots.* FROM ParkingSlots WHERE status != 'Maintenance' {condition}
               AND NOT EXISTS(SELECT 1 FROM ParkingBookings AS other WHERE other.parking_slot_id = ParkingSlots.id
               AND other.id != ? AND other.status IN ('Approved','Checked In') AND other.start_at < ? AND other.end_at > ?)
               ORDER BY slot_code LIMIT 1""", params,
        ).fetchone()
    if not row:
        raise APIError(409, f"No {booking_type.lower()} resource is available for that time.")
    return row


def perform_action(connection: database.DatabaseConnection, actor: dict[str, Any], booking_type: str,
                   booking_id: str, action: str, body: dict[str, Any]) -> dict[str, Any]:
    connection.execute("LOCK TABLE HotelBookings, ParkingBookings, Rooms, ParkingSlots IN SHARE ROW EXCLUSIVE MODE")
    booking = booking_row(connection, booking_type, booking_id)
    personnel = manages(actor, booking_type)
    if not personnel and not (action == "cancel" and booking["user_id"] == actor["id"]):
        raise APIError(403, "Your role cannot manage this reservation type.")
    old_status, new_status = booking["status"], booking["status"]
    stamp = now()
    resource_id = None
    assigned_id = booking["assigned_personnel_id"]
    title, category, details = "Reservation updated", "reservation_changed", ""

    if action == "accept":
        if old_status not in {"Pending", "Processing"}:
            raise APIError(409, "Only pending requests can be accepted.")
        new_status, assigned_id, title, category = "Processing", actor["id"], "Request accepted", "booking_accepted"
        details = f"Accepted by {actor['display_name']}."
    elif action == "assign":
        require(body, "personnelId")
        member = connection.execute(
            """SELECT Users.id,Users.display_name,Personnel.department,Personnel.active FROM Users
               JOIN Personnel ON Personnel.user_id=Users.id WHERE Users.id=?""", (body["personnelId"],),
        ).fetchone()
        if not member or member["department"] != booking_type or not member["active"]:
            raise APIError(400, "Choose an active team member from the matching department.")
        assigned_id, title = member["id"], "Request assigned"
        details = f"Assigned to {member['display_name']}."
    elif action in {"approve", "assign-room", "assign-slot"}:
        if old_status not in {"Pending", "Processing", "Approved"}:
            raise APIError(409, "This reservation can no longer be approved or assigned.")
        if action == "assign-room" and booking_type != "Hotel" or action == "assign-slot" and booking_type != "Parking":
            raise APIError(400, "That resource type does not match this reservation.")
        resource = available_resource(connection, booking_type, booking, body.get("roomId" if booking_type == "Hotel" else "slotId"))
        resource_id = resource["id"]
        table = "Rooms" if booking_type == "Hotel" else "ParkingSlots"
        connection.execute(f"UPDATE {table} SET status='Reserved' WHERE id=?", (resource_id,))
        old_resource = booking["room_id"] if booking_type == "Hotel" else booking["parking_slot_id"]
        if old_resource and old_resource != resource_id:
            connection.execute(f"UPDATE {table} SET status='Available' WHERE id=?", (old_resource,))
        new_status = "Approved"
        assigned_id = assigned_id or actor["id"]
        resource_name = resource["room_number"] if booking_type == "Hotel" else resource["slot_code"]
        category = "room_assignment" if booking_type == "Hotel" else "parking_assignment"
        title = "Room assigned" if booking_type == "Hotel" else "Parking slot assigned"
        details = f"{'Room ' if booking_type == 'Hotel' else 'Parking slot '}{resource_name} assigned."
    elif action == "reject":
        if old_status not in {"Pending", "Processing"}:
            raise APIError(409, "Only pending requests can be rejected.")
        new_status, title, category = "Rejected", "Booking rejected", "booking_rejected"
        details = body.get("reason", "Request rejected by personnel.")
    elif action == "cancel":
        if old_status not in {"Pending", "Processing", "Approved"}:
            raise APIError(409, "This reservation cannot be cancelled in its current status.")
        new_status, title, category = "Cancelled", "Booking cancelled", "booking_cancelled"
        details = body.get("reason", "Reservation cancelled.")
    elif action == "check-in":
        if old_status != "Approved":
            raise APIError(409, "Only approved reservations can be checked in.")
        new_status, title, details = "Checked In", "Guest checked in", "Guest checked in."
    elif action in {"check-out", "complete"}:
        if old_status not in ({"Checked In"} if action == "check-out" else {"Approved", "Checked In"}):
            raise APIError(409, "This reservation cannot be completed in its current status.")
        new_status, title, details = "Completed", "Reservation checked out", "Reservation checked out."
    else:
        raise APIError(404, "Unknown reservation action.")

    table = TABLE_FOR[booking_type]
    resource_column = "room_id" if booking_type == "Hotel" else "parking_slot_id"
    resource_table = "Rooms" if booking_type == "Hotel" else "ParkingSlots"
    if action in {"approve", "assign-room", "assign-slot"}:
        connection.execute(
            f"UPDATE {table} SET status=?,assigned_personnel_id=?,{resource_column}=?,updated_at=? WHERE id=?",
            (new_status, assigned_id, resource_id, stamp, booking_id),
        )
    else:
        connection.execute(
            f"UPDATE {table} SET status=?,assigned_personnel_id=?,updated_at=? WHERE id=?",
            (new_status, assigned_id, stamp, booking_id),
        )
    if new_status == "Checked In" and booking[resource_column]:
        connection.execute(f"UPDATE {resource_table} SET status='Occupied' WHERE id=?", (booking[resource_column],))
    if new_status in {"Cancelled", "Rejected", "Completed"} and booking[resource_column]:
        connection.execute(f"UPDATE {resource_table} SET status='Available' WHERE id=?", (booking[resource_column],))
    history(connection, booking_type, booking_id, actor["id"], action, old_status, new_status, details)
    notification(connection, booking_type, booking_id, category, title, f"{booking['id']}: {details}", booking["user_id"])
    if action in {"approve", "assign-room", "assign-slot"}:
        notification(connection, booking_type, booking_id, "booking_approved", "Booking approved", f"{booking['id']} was approved.", booking["user_id"])
    return serialize(connection, booking_type, booking_row(connection, booking_type, booking_id))


def update_booking(connection: database.DatabaseConnection, actor: dict[str, Any], booking_type: str,
                   booking_id: str, body: dict[str, Any]) -> dict[str, Any]:
    booking = booking_row(connection, booking_type, booking_id)
    personnel = manages(actor, booking_type)
    if not personnel and (booking["user_id"] != actor["id"] or booking["status"] != "Pending"):
        raise APIError(403, "Only your pending reservations can be changed.")
    mapping = {"name": "guest_name", "email": "guest_email", "phone": "guest_phone", "property": "property_name", "notes": "notes"}
    if personnel:
        if booking_type == "Hotel":
            mapping.update({"roomType": "room_type", "checkIn": "check_in", "checkOut": "check_out", "guests": "guest_count"})
        else:
            mapping.update({"parkingDate": "parking_date", "parkingTime": "parking_time", "durationHours": "duration_hours"})
    changes = {column: body[key] for key, column in mapping.items() if key in body}
    if personnel and booking_type == "Parking" and ("vehicle" in body or "plate" in body):
        vehicle = connection.execute("SELECT * FROM Vehicles WHERE id=?", (booking["vehicle_id"],)).fetchone()
        vehicle_type = str(body.get("vehicle", vehicle["vehicle_type"]))
        plate = str(body.get("plate", vehicle["plate_number"])).strip().upper()
        if not plate or len(plate) > 20:
            raise APIError(400, "Enter a valid vehicle plate (1 to 20 characters).")
        connection.execute("UPDATE Vehicles SET vehicle_type=?,plate_number=? WHERE id=?", (vehicle_type, plate, vehicle["id"]))
    if booking_type == "Hotel":
        check_in = str(changes.get("check_in", booking["check_in"]))
        check_out = str(changes.get("check_out", booking["check_out"]))
        if check_out <= check_in:
            raise APIError(400, "Check-out must be after check-in.")
        if "guest_count" in changes:
            changes["guest_count"] = max(1, min(16, int(changes["guest_count"])))
    elif "parkingDate" in body or "parkingTime" in body or "durationHours" in body:
        start = datetime.combine(
            date.fromisoformat(body.get("parkingDate", booking["start_at"][:10])),
            time.fromisoformat(body.get("parkingTime", booking["start_at"][11:16])),
        ).replace(tzinfo=timezone.utc)
        hours = float(body.get("durationHours", max(1, round((datetime.fromisoformat(booking["end_at"]) - datetime.fromisoformat(booking["start_at"])).total_seconds() / 3600))))
        changes["start_at"], changes["end_at"] = start.isoformat(), (start + timedelta(hours=hours)).isoformat()
    if personnel and "internalNotes" in body:
        changes["internal_notes"] = str(body["internalNotes"])
    if not changes:
        raise APIError(400, "No editable fields were provided.")
    assignments = ",".join(f"{column}=?" for column in changes)
    connection.execute(f"UPDATE {TABLE_FOR[booking_type]} SET {assignments},updated_at=? WHERE id=?", (*changes.values(), now(), booking_id))
    history(connection, booking_type, booking_id, actor["id"], "modified", booking["status"], booking["status"], "Reservation details changed.")
    notification(connection, booking_type, booking_id, "reservation_changed", "Reservation changed", "Reservation details were updated.", booking["user_id"])
    return serialize(connection, booking_type, booking_row(connection, booking_type, booking_id))


def list_bookings(connection: database.DatabaseConnection, actor: dict[str, Any], booking_type: str | None) -> list[dict[str, Any]]:
    result = []
    for kind in ([booking_type] if booking_type else ["Hotel", "Parking"]):
        table = TABLE_FOR[kind]
        if manages(actor, kind):
            rows = connection.execute(f"SELECT * FROM {table} ORDER BY created_at DESC").fetchall()
        elif actor["role"] in ROLE_FOR.values():
            continue
        else:
            rows = connection.execute(f"SELECT * FROM {table} WHERE user_id=? ORDER BY created_at DESC", (actor["id"],)).fetchall()
        result.extend(serialize(connection, kind, row) for row in rows)
    return sorted(result, key=lambda row: row["requestedAt"], reverse=True)


def resources(connection: database.DatabaseConnection, booking_type: str, query: dict[str, list[str]]) -> list[dict[str, Any]]:
    if booking_type == "Hotel":
        check_in = query.get("checkIn", [date.today().isoformat()])[0]
        check_out = query.get("checkOut", [(date.today() + timedelta(days=1)).isoformat()])[0]
        booking_id = query.get("bookingId", [""])[0]
        rows = connection.execute("SELECT * FROM Rooms ORDER BY room_number").fetchall()
        result = []
        for row in rows:
            conflict = connection.execute(
                """SELECT 1 FROM HotelBookings WHERE room_id=? AND id != ? AND status IN ('Approved','Checked In')
                   AND check_in < ? AND check_out > ? LIMIT 1""", (row["id"], booking_id, check_out, check_in),
            ).fetchone()
            result.append({**dict(row), "available": row["status"] != "Maintenance" and not conflict})
        return result
    start = query.get("startAt", [datetime.now(timezone.utc).isoformat()])[0]
    end = query.get("endAt", [(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()])[0]
    booking_id = query.get("bookingId", [""])[0]
    rows = connection.execute("SELECT * FROM ParkingSlots ORDER BY slot_code").fetchall()
    result = []
    for row in rows:
        conflict = connection.execute(
            """SELECT 1 FROM ParkingBookings WHERE parking_slot_id=? AND id != ? AND status IN ('Approved','Checked In')
               AND start_at < ? AND end_at > ? LIMIT 1""", (row["id"], booking_id, end, start),
        ).fetchone()
        result.append({**dict(row), "available": row["status"] != "Maintenance" and not conflict})
    return result


class CentralHandler(SimpleHTTPRequestHandler):
    server_version = "CentralChannel/1.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(config.WORKSPACE_ROOT), **kwargs)

    def end_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if "*" in config.ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif origin in config.ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        if urlsplit(self.path).path.startswith("/api/"):
            self.handle_api("GET")
        else:
            super().do_GET()

    def do_POST(self) -> None:
        self.handle_api("POST")

    def do_PUT(self) -> None:
        self.handle_api("PUT")

    def do_PATCH(self) -> None:
        self.handle_api("PATCH")

    def read_body(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length", "0"))
        if size > 1_000_000:
            raise APIError(413, "Request body is too large.")
        if not size:
            return {}
        try:
            value = json.loads(self.rfile.read(size))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise APIError(400, "Request body must be valid JSON.") from None
        if not isinstance(value, dict):
            raise APIError(400, "Request body must be a JSON object.")
        return value

    def respond(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def handle_api(self, method: str) -> None:
        connection = database.connect()
        try:
            with connection:
                result, status = self.dispatch(connection, method)
            self.respond(status, result)
        except APIError as error:
            self.respond(error.status, {"error": str(error)})
        except security.SupabaseAuthError as error:
            status = error.status if 400 <= error.status < 500 else 502
            self.respond(status, {"error": str(error)})
        except pg8000.dbapi.IntegrityError as error:
            message = "That vehicle plate is already registered." if "vehicles_plate_number_ci_idx" in str(error) else "The requested change conflicts with existing data."
            self.respond(409, {"error": message})
        except (TypeError, ValueError) as error:
            self.respond(400, {"error": str(error) or "Invalid request."})
        except Exception as error:
            self.log_error("Unexpected API error: %r", error)
            self.respond(500, {"error": "The server could not complete this request."})
        finally:
            connection.close()

    def dispatch(self, connection: database.DatabaseConnection, method: str) -> tuple[Any, int]:
        parsed = urlsplit(self.path)
        path = unquote(parsed.path).rstrip("/") or "/"
        parts, query = path.strip("/").split("/"), parse_qs(parsed.query)
        body = self.read_body() if method in {"POST", "PUT", "PATCH"} else {}
        if path == "/api/health" and method == "GET":
            return {"status": "ok", "externalApiBase": config.EXTERNAL_API_BASE}, 200
        if path == "/api/auth/register" and method == "POST":
            require(body, "username", "email", "password")
            username = validate_username(body["username"])
            if len(body["password"]) < 10:
                raise APIError(400, "Password must be at least 10 characters.")
            email = str(body["email"]).strip().lower()
            display_name = str(body.get("displayName") or username).strip()
            connection.execute("LOCK TABLE Users IN SHARE ROW EXCLUSIVE MODE")
            exists = connection.execute(
                "SELECT 1 FROM Users WHERE lower(username)=lower(?) OR lower(email)=? LIMIT 1",
                (username, email),
            ).fetchone()
            if exists:
                raise APIError(409, "That username or email is already registered.")
            auth_result = security.register(email, str(body["password"]), username, display_name)
            auth_user = auth_result.get("user") or auth_result
            user_id = auth_user.get("id")
            if not user_id:
                raise APIError(502, "Supabase Auth did not return a user ID.")
            first_user = connection.execute("SELECT COUNT(*) AS count FROM Users").fetchone()["count"] == 0
            role = "Admin" if config.FIRST_SIGNUP_ADMIN and first_user else "User"
            stamp = now()
            connection.execute(
                "INSERT INTO Users(id,username,email,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?,?,?)",
                (user_id, username, email, display_name, "", role, stamp),
            )
            user = connection.execute("SELECT id,username,email,display_name,role FROM Users WHERE id=?", (user_id,)).fetchone()
            token = auth_result.get("access_token") or (auth_result.get("session") or {}).get("access_token", "")
            return {
                "token": token,
                "refreshToken": auth_result.get("refresh_token", ""),
                "user": dict(user),
                "requiresEmailConfirmation": not bool(token),
            }, 201
        if path == "/api/auth/login" and method == "POST":
            require(body, "username", "password")
            username = validate_username(body["username"], allow_email=True)
            user = connection.execute(
                "SELECT * FROM Users WHERE (lower(username)=lower(?) OR lower(email)=?) AND active=1",
                (username, username.lower()),
            ).fetchone()
            if not user:
                raise APIError(401, "Username or password is incorrect.")
            auth_result = security.sign_in(user["email"], str(body["password"]))
            auth_user = auth_result.get("user") or {}
            if auth_user.get("id") != user["id"]:
                raise APIError(401, "Username or password is incorrect.")
            return {
                "token": auth_result.get("access_token", ""),
                "refreshToken": auth_result.get("refresh_token", ""),
                "user": {key: user[key] for key in ("id", "username", "email", "display_name", "role")},
            }, 200
        if path == "/api/auth/me" and method == "GET":
            return {"user": actor_for(connection, self)}, 200
        if path == "/api/auth/refresh" and method == "POST":
            require(body, "refreshToken")
            auth_result = security.refresh_session(str(body["refreshToken"]))
            return {
                "token": auth_result.get("access_token", ""),
                "refreshToken": auth_result.get("refresh_token", ""),
            }, 200
        if path == "/api/auth/logout" and method == "POST":
            header = self.headers.get("Authorization", "")
            if header.lower().startswith("bearer "):
                security.revoke_session(connection, header[7:].strip())
            return {"ok": True}, 200

        actor = actor_for(connection, self)
        if path == "/api/bookings" and method == "GET":
            return list_bookings(connection, actor, None), 200
        if path in {"/api/hotel/bookings", "/api/parking/bookings"}:
            kind = "Hotel" if "/hotel/" in path else "Parking"
            if method == "GET":
                if actor["role"] in ROLE_FOR.values() and not manages(actor, kind):
                    raise APIError(403, "Your role cannot view that department's reservations.")
                return list_bookings(connection, actor, kind), 200
            if method == "POST":
                return make_booking(connection, actor, kind, body), 201
        if path == "/api/rooms" and method == "GET":
            if actor["role"] == "Parking Personnel":
                raise APIError(403, "Hotel staff cannot view room inventory.")
            return resources(connection, "Hotel", query), 200
        if path == "/api/parking/slots" and method == "GET":
            if actor["role"] == "Hotel Personnel":
                raise APIError(403, "Parking staff cannot view slot inventory.")
            return resources(connection, "Parking", query), 200
        if path == "/api/users" and method == "GET":
            if actor["role"] != "Admin":
                raise APIError(403, "Administrator access is required.")
            rows = connection.execute("SELECT id,username,email,display_name,role FROM Users WHERE active=1 ORDER BY display_name").fetchall()
            return [dict(row) for row in rows], 200
        if path == "/api/personnel" and method == "GET":
            if actor["role"] == "User":
                raise APIError(403, "Personnel records are not available to user accounts.")
            rows = connection.execute(
                """SELECT Users.id,Users.username,Users.email,Users.display_name,Users.role,Personnel.department,Personnel.active
                   FROM Personnel JOIN Users ON Users.id=Personnel.user_id ORDER BY Users.display_name"""
            ).fetchall()
            return [dict(row) for row in rows if actor["role"] == "Admin" or row["department"] == actor.get("department")], 200
        if path == "/api/personnel" and method == "POST":
            if actor["role"] != "Admin":
                raise APIError(403, "Administrator access is required.")
            require(body, "userId", "department")
            department = body["department"]
            if department not in ROLE_FOR:
                raise APIError(400, "Department must be Hotel or Parking.")
            target = connection.execute("SELECT * FROM Users WHERE id=?", (body["userId"],)).fetchone()
            if not target or target["role"] != "User":
                raise APIError(404, "Choose an existing user account.")
            connection.execute("UPDATE Users SET role=? WHERE id=?", (ROLE_FOR[department], target["id"]))
            connection.execute("INSERT INTO Personnel(user_id,department,created_at) VALUES(?,?,?)", (target["id"], department, now()))
            return {"userId": target["id"], "department": department, "role": ROLE_FOR[department]}, 201
        if path == "/api/notifications" and method == "GET":
            rows = connection.execute(
                """SELECT * FROM Notifications WHERE recipient_user_id=? OR audience_role=? OR ?='Admin'
                   ORDER BY created_at DESC LIMIT 100""", (actor["id"], actor["role"], actor["role"]),
            ).fetchall()
            return [dict(row) for row in rows], 200
        if len(parts) == 4 and parts[:2] == ["api", "notifications"] and parts[3] == "read" and method == "PUT":
            updated = connection.execute(
                """UPDATE Notifications SET read_at=? WHERE id=? AND
                   (recipient_user_id=? OR audience_role=? OR ?='Admin')""",
                (now(), parts[2], actor["id"], actor["role"], actor["role"]),
            ).rowcount
            if not updated:
                raise APIError(404, "Notification not found.")
            return {"ok": True}, 200
        if path == "/api/history" and method == "GET":
            booking_id, kind = query.get("bookingId", [""])[0], query.get("type", [""])[0]
            if not booking_id or kind not in TABLE_FOR:
                raise APIError(400, "History requires a bookingId and valid type.")
            booking = booking_row(connection, kind, booking_id)
            if not manages(actor, kind) and booking["user_id"] != actor["id"]:
                raise APIError(403, "You cannot view this booking history.")
            rows = connection.execute(
                """SELECT BookingHistory.*,Users.display_name AS actor_name FROM BookingHistory
                   LEFT JOIN Users ON Users.id=BookingHistory.actor_user_id WHERE booking_type=? AND booking_id=? ORDER BY created_at DESC""",
                (kind, booking_id),
            ).fetchall()
            return [dict(row) for row in rows], 200
        if len(parts) == 3 and parts[:2] == ["api", "bookings"] and method in {"PUT", "PATCH"}:
            booking_id = parts[2]
            kind = "Hotel" if booking_id.startswith("HTL-") else "Parking" if booking_id.startswith("PKG-") else ""
            if not kind:
                raise APIError(404, "Reservation not found.")
            return update_booking(connection, actor, kind, booking_id, body), 200
        if len(parts) == 4 and parts[:2] == ["api", "bookings"] and method in {"PUT", "POST"}:
            booking_id, action = parts[2], parts[3]
            kind = "Hotel" if booking_id.startswith("HTL-") else "Parking" if booking_id.startswith("PKG-") else ""
            if not kind:
                raise APIError(404, "Reservation not found.")
            return perform_action(connection, actor, kind, booking_id, action, body), 200
        if len(parts) == 5 and parts[0] == "api" and parts[2] == "bookings" and method == "PUT":
            kind = "Hotel" if parts[1] == "hotel" else "Parking" if parts[1] == "parking" else ""
            if not kind:
                raise APIError(404, "Reservation not found.")
            return perform_action(connection, actor, kind, parts[3], parts[4], body), 200
        if len(parts) == 4 and parts[0] == "api" and parts[1] in {"hotel", "parking"} and parts[2] == "bookings" and method in {"PUT", "PATCH"}:
            return update_booking(connection, actor, "Hotel" if parts[1] == "hotel" else "Parking", parts[3], body), 200
        raise APIError(404, "API route not found.")

    def log_message(self, format_string: str, *args: Any) -> None:
        sys.stdout.write(f"{self.address_string()} - {format_string % args}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Central Channel REST API and web host")
    parser.add_argument("--create-admin", action="store_true", help="Create an administrator account interactively")
    args = parser.parse_args()
    database.initialize()
    if args.create_admin:
        email, username, display_name = input("Admin email: ").strip(), input("Admin username: ").strip(), input("Display name: ").strip()
        password = getpass("Admin password (10+ characters): ")
        if len(password) < 10:
            raise SystemExit("Password must be at least 10 characters.")
        auth_result = security.register(email.lower(), password, username, display_name)
        auth_user = auth_result.get("user") or auth_result
        user_id = auth_user.get("id")
        if not user_id:
            raise SystemExit("Supabase Auth did not return a user ID.")
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO Users(id,username,email,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?,'Admin',?)",
                (user_id, username, email.lower(), display_name, "", now()),
            )
        print(f"Administrator account created for {email}.")
        return
    server = ThreadingHTTPServer((config.HOST, config.PORT), CentralHandler)
    print(f"Central Channel running at http://{config.HOST}:{config.PORT}")
    print(f"Supabase PostgreSQL schema: {config.SUPABASE_DATABASE_SCHEMA}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Central Channel.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()