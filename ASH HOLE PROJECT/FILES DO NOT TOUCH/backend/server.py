"""REST API and static-file host for the Central Channel application."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sqlite3
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from . import config, database, security


ROLE_FOR_TYPE = {"Hotel": "Hotel Personnel", "Parking": "Parking Personnel"}
TABLE_FOR_TYPE = {"Hotel": "HotelBookings", "Parking": "ParkingBookings"}
STATUSES = {"Pending", "Processing", "Approved", "Rejected", "Cancelled", "Checked In", "Completed"}


class APIError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def as_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def require_fields(body: dict[str, Any], *fields: str) -> None:
    missing = [field for field in fields if not str(body.get(field, "")).strip()]
    if missing:
        raise APIError(HTTPStatus.BAD_REQUEST, f"Required fields: {', '.join(missing)}")


def current_user(connection: sqlite3.Connection, handler: "CentralHandler") -> dict[str, Any]:
    header = handler.headers.get("Authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    user = security.find_session_user(connection, token) if token else None
    if not user:
        raise APIError(HTTPStatus.UNAUTHORIZED, "Sign in to continue.")
    return dict(user)


def require_admin(actor: dict[str, Any]) -> None:
    if actor["role"] != "Admin":
        raise APIError(HTTPStatus.FORBIDDEN, "Administrator access is required.")


def can_manage(actor: dict[str, Any], booking_type: str) -> bool:
    return actor["role"] == "Admin" or actor["role"] == ROLE_FOR_TYPE[booking_type]


def require_booking_access(actor: dict[str, Any], booking_type: str, booking: sqlite3.Row) -> None:
    if not can_manage(actor, booking_type) and actor["id"] != booking["user_id"]:
        raise APIError(HTTPStatus.FORBIDDEN, "You cannot access this reservation.")


def find_booking(connection: sqlite3.Connection, booking_type: str, booking_id: str) -> sqlite3.Row:
    table = TABLE_FOR_TYPE[booking_type]
    row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (booking_id,)).fetchone()
    if row is None:
        raise APIError(HTTPStatus.NOT_FOUND, "Reservation not found.")
    return row


def assigned_name(connection: sqlite3.Connection, user_id: str | None) -> str:
    if not user_id:
        return "Unassigned"
    row = connection.execute("SELECT display_name FROM Users WHERE id = ?", (user_id,)).fetchone()
    return row["display_name"] if row else "Unassigned"


def serialize_booking(connection: sqlite3.Connection, booking_type: str, row: sqlite3.Row) -> dict[str, Any]:
    user = connection.execute(
        "SELECT display_name, email FROM Users WHERE id = ?", (row["user_id"],)
    ).fetchone()
    guest_name = row["guest_name"] if "guest_name" in row.keys() else user["display_name"]
    guest_email = row["guest_email"] if "guest_email" in row.keys() else user["email"]
    guest_phone = row["guest_phone"] if "guest_phone" in row.keys() else ""
    common = {
        "id": row["id"], "type": booking_type, "userId": row["user_id"],
        "name": guest_name, "email": guest_email, "phone": guest_phone,
        "property": row["property_name"], "status": row["status"],
        "assigned": assigned_name(connection, row["assigned_personnel_id"]),
        "assignedPersonnelId": row["assigned_personnel_id"], "notes": row["notes"],
        "internalNotes": row["internal_notes"], "requestedAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    if booking_type == "Hotel":
        room = connection.execute("SELECT room_number FROM Rooms WHERE id = ?", (row["room_id"],)).fetchone()
        common.update({
            "roomType": row["room_type"], "checkIn": row["check_in"], "checkOut": row["check_out"],
            "guests": row["guest_count"], "room": f"Room {room['room_number']}" if room else "",
            "roomId": row["room_id"],
        })
    else:
        vehicle = connection.execute("SELECT vehicle_type, plate_number FROM Vehicles WHERE id = ?", (row["vehicle_id"],)).fetchone()
        slot = connection.execute("SELECT slot_code FROM ParkingSlots WHERE id = ?", (row["parking_slot_id"],)).fetchone()
        start = datetime.fromisoformat(row["start_at"])
        end = datetime.fromisoformat(row["end_at"])
        common.update({
            "vehicle": vehicle["vehicle_type"], "plate": vehicle["plate_number"],
            "parkingDate": start.date().isoformat(), "parkingTime": start.strftime("%H:%M"),
            "duration": f"{max(1, round((end - start).total_seconds() / 3600))} hours",
            "parkingSlot": slot["slot_code"] if slot else "", "slotId": row["parking_slot_id"],
        })
    return common


def log_history(
    connection: sqlite3.Connection, booking_type: str, booking_id: str,
    actor_id: str | None, action: str, old_status: str | None,
    new_status: str | None, details: str = "",
) -> None:
    connection.execute(
        """INSERT INTO BookingHistory
           (booking_type, booking_id, actor_user_id, action, old_status, new_status, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (booking_type, booking_id, actor_id, action, old_status, new_status, details, utc_now()),
    )


def notify(
    connection: sqlite3.Connection, booking_type: str, booking_id: str,
    category: str, title: str, message: str, user_id: str | None = None,
) -> None:
    connection.execute(
        """INSERT INTO Notifications
           (id, recipient_user_id, audience_role, category, booking_type, booking_id, title, message, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), user_id, ROLE_FOR_TYPE[booking_type], category, booking_type, booking_id, title, message, utc_now()),
    )


def booking_list(connection: sqlite3.Connection, actor: dict[str, Any], booking_type: str | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    types = [booking_type] if booking_type else ["Hotel", "Parking"]
    for kind in types:
        table = TABLE_FOR_TYPE[kind]
        if can_manage(actor, kind):
            rows = connection.execute(f"SELECT * FROM {table} ORDER BY created_at DESC").fetchall()
        else:
            rows = connection.execute(f"SELECT * FROM {table} WHERE user_id = ? ORDER BY created_at DESC", (actor["id"],)).fetchall()
        result.extend(serialize_booking(connection, kind, row) for row in rows)
    return sorted(result, key=lambda booking: booking["requestedAt"], reverse=True)


def create_booking(connection: sqlite3.Connection, actor: dict[str, Any], booking_type: str, body: dict[str, Any]) -> dict[str, Any]:
    if actor["role"] not in {"User", "Admin", ROLE_FOR_TYPE[booking_type]}:
        raise APIError(HTTPStatus.FORBIDDEN, "Your role cannot create this type of reservation.")
    require_fields(body, "name", "email", "property")
    stamp = utc_now()
    prefix = "HTL" if booking_type == "Hotel" else "PKG"
    booking_id = f"{prefix}-{secrets.token_hex(3).upper()}"
    if booking_type == "Hotel":
        require_fields(body, "roomType", "checkIn", "checkOut")
        try:
            check_in = date.fromisoformat(str(body["checkIn"]))
            check_out = date.fromisoformat(str(body["checkOut"]))
            guests = int(body.get("guests", 1))
        except (ValueError, TypeError):
            raise APIError(HTTPStatus.BAD_REQUEST, "Enter valid hotel dates and guest count.") from None
        if check_out <= check_in or guests < 1 or guests > 16:
            raise APIError(HTTPStatus.BAD_REQUEST, "Check-out must follow check-in and guests must be between 1 and 16.")
        connection.execute(
            """INSERT INTO HotelBookings
               (id, user_id, property_name, guest_name, guest_email, guest_phone, room_type,
                check_in, check_out, guest_count, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (booking_id, actor["id"], body["property"], body["name"], body["email"], body.get("phone", ""),
             body["roomType"], check_in.isoformat(), check_out.isoformat(), guests, body.get("notes", ""), stamp, stamp),
        )
    else:
        require_fields(body, "vehicle", "plate", "parkingDate", "parkingTime")
        try:
            start = datetime.combine(date.fromisoformat(str(body["parkingDate"])), time.fromisoformat(str(body["parkingTime"]))).replace(tzinfo=timezone.utc)
            hours = float(body.get("durationHours", 1))
        except (ValueError, TypeError):
            raise APIError(HTTPStatus.BAD_REQUEST, "Enter a valid parking date, time, and duration.") from None
        if hours <= 0 or hours > 168:
            raise APIError(HTTPStatus.BAD_REQUEST, "Parking duration must be between 1 hour and 7 days.")
        plate = str(body["plate"]).strip().upper()
        if len(plate) > 20:
            raise APIError(HTTPStatus.BAD_REQUEST, "Vehicle plate must be 20 characters or fewer.")
        vehicle = connection.execute("SELECT * FROM Vehicles WHERE plate_number = ?", (plate,)).fetchone()
        if vehicle and vehicle["owner_user_id"] != actor["id"]:
            raise APIError(HTTPStatus.CONFLICT, "That vehicle plate is already registered to another account.")
        if vehicle:
            vehicle_id = vehicle["id"]
            connection.execute("UPDATE Vehicles SET vehicle_type = ? WHERE id = ?", (body["vehicle"], vehicle_id))
        else:
            vehicle_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO Vehicles (id, owner_user_id, vehicle_type, plate_number, created_at) VALUES (?, ?, ?, ?, ?)",
                (vehicle_id, actor["id"], body["vehicle"], plate, stamp),
            )
        connection.execute(
            """INSERT INTO ParkingBookings
               (id, user_id, vehicle_id, property_name, start_at, end_at, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (booking_id, actor["id"], vehicle_id, body["property"], start.isoformat(),
             (start + timedelta(hours=hours)).isoformat(), body.get("notes", ""), stamp, stamp),
        )
    log_history(connection, booking_type, booking_id, actor["id"], "created", None, "Pending", "Customer submitted a request.")
    notify(connection, booking_type, booking_id, "new_request", "New booking request", f"{body['name']} submitted a {booking_type.lower()} request.", actor["id"])
    row = find_booking(connection, booking_type, booking_id)
    return serialize_booking(connection, booking_type, row)


def available_room(connection: sqlite3.Connection, booking: sqlite3.Row, requested_id: str | None = None) -> sqlite3.Row:
    params: list[Any] = [booking["check_out"], booking["check_in"], booking["id"]]
    requested_clause = "AND Rooms.id = ?" if requested_id else ""
    if requested_id:
        params.append(requested_id)
    room = connection.execute(
        f"""SELECT Rooms.* FROM Rooms WHERE Rooms.status != 'Maintenance' {requested_clause}
            AND NOT EXISTS (
                SELECT 1 FROM HotelBookings AS conflicts
                WHERE conflicts.room_id = Rooms.id AND conflicts.id != ?
                  AND conflicts.status IN ('Approved', 'Checked In')
                  AND conflicts.check_in < ? AND conflicts.check_out > ?
            ) ORDER BY Rooms.room_number LIMIT 1""",
        ([requested_id] if requested_id else []) + [booking["id"], booking["check_out"], booking["check_in"]],
    ).fetchone()
    if room is None:
        raise APIError(HTTPStatus.CONFLICT, "No room is available for those dates.")
    return room


def available_slot(connection: sqlite3.Connection, booking: sqlite3.Row, requested_id: str | None = None) -> sqlite3.Row:
    requested_clause = "AND ParkingSlots.id = ?" if requested_id else ""
    params: list[Any] = [booking["end_at"], booking["start_at"], booking["id"]]
    if requested_id:
        params.append(requested_id)
    slot = connection.execute(
        f"""SELECT ParkingSlots.* FROM ParkingSlots WHERE ParkingSlots.status != 'Maintenance' {requested_clause}
            AND NOT EXISTS (
                SELECT 1 FROM ParkingBookings AS conflicts
                WHERE conflicts.parking_slot_id = ParkingSlots.id AND conflicts.id != ?
                  AND conflicts.status IN ('Approved', 'Checked In')
                  AND conflicts.start_at < ? AND conflicts.end_at > ?
            ) ORDER BY ParkingSlots.slot_code LIMIT 1""",
        ([requested_id] if requested_id else []) + [booking["id"], booking["end_at"], booking["start_at"]],
    ).fetchone()
    if slot is None:
        raise APIError(HTTPStatus.CONFLICT, "No parking slot is available for that time.")
    return slot


def apply_action(connection: sqlite3.Connection, actor: dict[str, Any], booking_type: str, booking_id: str, action: str, body: dict[str, Any]) -> dict[str, Any]:
    # Serialize status transitions and resource selection to prevent double assignment.
    connection.execute("BEGIN IMMEDIATE")
    booking = find_booking(connection, booking_type, booking_id)
    if not can_manage(actor, booking_type) and not (action == "cancel" and booking["user_id"] == actor["id"]):
        raise APIError(HTTPStatus.FORBIDDEN, "Your role cannot manage this reservation type.")
    old_status = booking["status"]
    table = TABLE_FOR_TYPE[booking_type]
    stamp = utc_now()
    new_status = old_status
    title = "Reservation updated"
    category = "reservation_changed"
    details = ""
    resource_id: str | None = None
    assigned_override: str | None = None

    if action == "accept":
        if old_status not in {"Pending", "Processing"}:
            raise APIError(HTTPStatus.CONFLICT, "Only pending requests can be accepted.")
        new_status, title, category = "Processing", "Request accepted", "booking_accepted"
        details = f"Accepted by {actor['display_name']}."
    elif action == "assign":
        require_fields(body, "personnelId")
        target = connection.execute(
            """SELECT Users.id, Users.display_name, Personnel.department, Personnel.active
               FROM Users JOIN Personnel ON Personnel.user_id = Users.id WHERE Users.id = ?""",
            (body["personnelId"],),
        ).fetchone()
        if not target or target["department"] != booking_type or not target["active"]:
            raise APIError(HTTPStatus.BAD_REQUEST, "Choose an active team member from the matching department.")
        assigned_override = target["id"]
        title, details = "Request assigned", f"Assigned to {target['display_name']}."
        category = "reservation_changed"
    elif action in {"approve", "assign-room", "assign-slot"}:
        if old_status not in {"Pending", "Processing", "Approved"}:
            raise APIError(HTTPStatus.CONFLICT, "This reservation can no longer be approved or assigned.")
        if action == "assign-room" and booking_type != "Hotel" or action == "assign-slot" and booking_type != "Parking":
            raise APIError(HTTPStatus.BAD_REQUEST, "That resource type does not match the reservation.")
        if booking_type == "Hotel":
            room = available_room(connection, booking, body.get("roomId"))
            resource_id = room["id"]
            connection.execute("UPDATE Rooms SET status = 'Reserved' WHERE id = ?", (resource_id,))
            category, title = "room_assignment", "Room assigned"
            details = f"Room {room['room_number']} assigned."
        else:
            slot = available_slot(connection, booking, body.get("slotId"))
            resource_id = slot["id"]
            connection.execute("UPDATE ParkingSlots SET status = 'Reserved' WHERE id = ?", (resource_id,))
            category, title = "parking_assignment", "Parking slot assigned"
            details = f"Parking slot {slot['slot_code']} assigned."
        new_status = "Approved"
    elif action == "reject":
        if old_status not in {"Pending", "Processing"}:
            raise APIError(HTTPStatus.CONFLICT, "Only pending requests can be rejected.")
        new_status, title, category = "Rejected", "Booking rejected", "booking_rejected"
        details = body.get("reason", "Request rejected by personnel.")
    elif action == "cancel":
        if old_status not in {"Pending", "Processing", "Approved"}:
            raise APIError(HTTPStatus.CONFLICT, "This reservation cannot be cancelled in its current status.")
        new_status, title, category = "Cancelled", "Booking cancelled", "booking_cancelled"
        details = body.get("reason", "Reservation cancelled.")
    elif action == "check-in":
        if old_status != "Approved":
            raise APIError(HTTPStatus.CONFLICT, "Only approved reservations can be checked in.")
        new_status, title, details = "Checked In", "Guest checked in", "Guest checked in."
        category = "reservation_changed"
    elif action == "check-out":
        if old_status != "Checked In":
            raise APIError(HTTPStatus.CONFLICT, "Only checked-in reservations can be checked out.")
        new_status, title, details = "Completed", "Reservation checked out", "Reservation checked out."
        category = "reservation_changed"
    elif action == "complete":
        if old_status not in {"Approved", "Checked In"}:
            raise APIError(HTTPStatus.CONFLICT, "This reservation cannot be completed in its current status.")
        new_status, title, details = "Completed", "Reservation completed", "Marked completed."
        category = "reservation_changed"
    else:
        raise APIError(HTTPStatus.NOT_FOUND, "Unknown reservation action.")

    assignment_id = assigned_override or (actor["id"] if action == "accept" else booking["assigned_personnel_id"] or (actor["id"] if can_manage(actor, booking_type) else None))
    if booking_type == "Hotel":
        if action in {"approve", "assign-room", "assign-slot"}:
            if booking["room_id"] and booking["room_id"] != resource_id:
                connection.execute("UPDATE Rooms SET status = 'Available' WHERE id = ?", (booking["room_id"],))
            connection.execute(
                f"UPDATE {table} SET status = ?, assigned_personnel_id = ?, room_id = ?, updated_at = ? WHERE id = ?",
                (new_status, assignment_id, resource_id, stamp, booking_id),
            )
        else:
            connection.execute(
                f"UPDATE {table} SET status = ?, assigned_personnel_id = ?, updated_at = ? WHERE id = ?",
                (new_status, assignment_id, stamp, booking_id),
            )
        if new_status == "Checked In":
            connection.execute("UPDATE Rooms SET status = 'Occupied' WHERE id = ?", (booking["room_id"],))
        if new_status in {"Cancelled", "Rejected", "Completed"} and booking["room_id"]:
            connection.execute("UPDATE Rooms SET status = 'Available' WHERE id = ?", (booking["room_id"],))
    else:
        if action in {"approve", "assign-room", "assign-slot"}:
            if booking["parking_slot_id"] and booking["parking_slot_id"] != resource_id:
                connection.execute("UPDATE ParkingSlots SET status = 'Available' WHERE id = ?", (booking["parking_slot_id"],))
            connection.execute(
                f"UPDATE {table} SET status = ?, assigned_personnel_id = ?, parking_slot_id = ?, updated_at = ? WHERE id = ?",
                (new_status, assignment_id, resource_id, stamp, booking_id),
            )
        else:
            connection.execute(
                f"UPDATE {table} SET status = ?, assigned_personnel_id = ?, updated_at = ? WHERE id = ?",
                (new_status, assignment_id, stamp, booking_id),
            )
        if new_status == "Checked In":
            connection.execute("UPDATE ParkingSlots SET status = 'Occupied' WHERE id = ?", (booking["parking_slot_id"],))
        if new_status in {"Cancelled", "Rejected", "Completed"} and booking["parking_slot_id"]:
            connection.execute("UPDATE ParkingSlots SET status = 'Available' WHERE id = ?", (booking["parking_slot_id"],))

    log_history(connection, booking_type, booking_id, actor["id"], action, old_status, new_status, details)
    notify(connection, booking_type, booking_id, category, title, f"{booking['guest_name']}: {details}", booking["user_id"])
    return serialize_booking(connection, booking_type, find_booking(connection, booking_type, booking_id))


def update_booking(connection: sqlite3.Connection, actor: dict[str, Any], booking_type: str, booking_id: str, body: dict[str, Any]) -> dict[str, Any]:
    booking = find_booking(connection, booking_type, booking_id)
    require_booking_access(actor, booking_type, booking)
    staff_access = can_manage(actor, booking_type)
    if not staff_access and booking["status"] != "Pending":
        raise APIError(HTTPStatus.FORBIDDEN, "Only pending reservations can be changed by the customer.")
    allowed = {"guest_name": "name", "guest_email": "email", "guest_phone": "phone", "property_name": "property", "notes": "notes"}
    if staff_access:
        if booking_type == "Hotel":
            allowed.update({"room_type": "roomType", "check_in": "checkIn", "check_out": "checkOut", "guest_count": "guests"})
        else:
            allowed.update({"parking_date": "parkingDate", "parking_time": "parkingTime", "duration_hours": "durationHours"})
    changes = {column: body[field] for column, field in allowed.items() if field in body}
    if not changes and "internalNotes" not in body:
        raise APIError(HTTPStatus.BAD_REQUEST, "No editable fields were provided.")
    if booking_type == "Hotel":
        check_in = changes.get("check_in", booking["check_in"])
        check_out = changes.get("check_out", booking["check_out"])
        if check_out <= check_in:
            raise APIError(HTTPStatus.BAD_REQUEST, "Check-out must be after check-in.")
        if "guest_count" in changes:
            changes["guest_count"] = max(1, min(16, int(changes["guest_count"])))
    elif any(key in changes for key in ("parking_date", "parking_time", "duration_hours")):
        current = serialize_booking(connection, booking_type, booking)
        start = datetime.combine(
            date.fromisoformat(str(changes.get("parking_date", current["parkingDate"]))),
            time.fromisoformat(str(changes.get("parking_time", current["parkingTime"]))),
        ).replace(tzinfo=timezone.utc)
        hours = float(changes.get("duration_hours", current["duration"].split()[0]))
        changes["start_at"] = start.isoformat()
        changes["end_at"] = (start + timedelta(hours=hours)).isoformat()
        changes.pop("parking_date", None)
        changes.pop("parking_time", None)
        changes.pop("duration_hours", None)
    if staff_access and "internalNotes" in body:
        changes["internal_notes"] = str(body["internalNotes"])
    if not changes:
        raise APIError(HTTPStatus.BAD_REQUEST, "No editable fields were provided.")
    assignments = ", ".join(f"{column} = ?" for column in changes)
    connection.execute(
        f"UPDATE {TABLE_FOR_TYPE[booking_type]} SET {assignments}, updated_at = ? WHERE id = ?",
        (*changes.values(), utc_now(), booking_id),
    )
    details = "Reservation details changed."
    log_history(connection, booking_type, booking_id, actor["id"], "modified", booking["status"], booking["status"], details)
    notify(connection, booking_type, booking_id, "reservation_changed", "Reservation changed", f"{booking['guest_name']}: reservation details changed.", booking["user_id"])
    return serialize_booking(connection, booking_type, find_booking(connection, booking_type, booking_id))


def list_resources(connection: sqlite3.Connection, booking_type: str, query: dict[str, list[str]]) -> list[dict[str, Any]]:
    if booking_type == "Hotel":
        check_in = query.get("checkIn", [date.today().isoformat()])[0]
        check_out = query.get("checkOut", [(date.today() + timedelta(days=1)).isoformat()])[0]
        rows = connection.execute("SELECT * FROM Rooms ORDER BY room_number").fetchall()
        result = []
        for row in rows:
            conflict = connection.execute(
                """SELECT 1 FROM HotelBookings WHERE room_id = ? AND status IN ('Approved', 'Checked In')
                   AND check_in < ? AND check_out > ? LIMIT 1""", (row["id"], check_out, check_in),
            ).fetchone()
            result.append({**dict(row), "available": row["status"] != "Maintenance" and conflict is None})
        return result
    start = query.get("startAt", [datetime.now(timezone.utc).isoformat()])[0]
    end = query.get("endAt", [(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()])[0]
    rows = connection.execute("SELECT * FROM ParkingSlots ORDER BY slot_code").fetchall()
    result = []
    for row in rows:
        conflict = connection.execute(
            """SELECT 1 FROM ParkingBookings WHERE parking_slot_id = ? AND status IN ('Approved', 'Checked In')
               AND start_at < ? AND end_at > ? LIMIT 1""", (row["id"], end, start),
        ).fetchone()
        result.append({**dict(row), "available": row["status"] != "Maintenance" and conflict is None})
    return result


class CentralHandler(SimpleHTTPRequestHandler):
    server_version = "CentralChannel/1.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(config.WORKSPACE_ROOT), **kwargs)

    def end_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if "*" in config.ALLOWED_ORIGINS:
            allowed_origin = "*"
        elif origin in config.ALLOWED_ORIGINS:
            allowed_origin = origin
        else:
            allowed_origin = ""
        if allowed_origin:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
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

    def do_DELETE(self) -> None:
        self.handle_api("DELETE")

    def read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise APIError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body is too large.")
        if length == 0:
            return {}
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise APIError(HTTPStatus.BAD_REQUEST, "Request body must be valid JSON.") from None
        if not isinstance(value, dict):
            raise APIError(HTTPStatus.BAD_REQUEST, "Request body must be a JSON object.")
        return value

    def respond(self, status: int, payload: dict[str, Any] | list[Any]) -> None:
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
        except sqlite3.IntegrityError as error:
            message = "The requested change conflicts with existing data."
            if "Vehicles.plate_number" in str(error):
                message = "That vehicle plate is already registered."
            self.respond(HTTPStatus.CONFLICT, {"error": message})
        except (ValueError, TypeError) as error:
            self.respond(HTTPStatus.BAD_REQUEST, {"error": str(error) or "Invalid request."})
        except Exception as error:
            self.log_error("Unexpected API error: %s", repr(error))
            self.respond(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "The server could not complete this request."})
        finally:
            connection.close()

    def dispatch(self, connection: sqlite3.Connection, method: str) -> tuple[Any, int]:
        parsed = urlsplit(self.path)
        path = unquote(parsed.path).rstrip("/") or "/"
        query = parse_qs(parsed.query)
        parts = path.strip("/").split("/")
        body = self.read_body() if method in {"POST", "PUT", "PATCH"} else {}

        if path == "/api/health" and method == "GET":
            return {"status": "ok", "apiBase": config.EXTERNAL_API_BASE}, HTTPStatus.OK
        if path == "/api/auth/register" and method == "POST":
            require_fields(body, "username", "email", "password")
            if len(str(body["password"])) < 10:
                raise APIError(HTTPStatus.BAD_REQUEST, "Password must be at least 10 characters.")
            display_name = str(body.get("displayName") or body["username"]).strip()
            user_id = str(uuid.uuid4())
            stamp = utc_now()
            connection.execute(
                """INSERT INTO Users (id, username, email, display_name, password_hash, role, created_at)
                   VALUES (?, ?, ?, ?, ?, 'User', ?)""",
                (user_id, str(body["username"]).strip(), str(body["email"]).strip().lower(), display_name,
                 security.hash_password(str(body["password"])), stamp),
            )
            token = security.issue_session(connection, user_id)
            user = connection.execute("SELECT id, username, email, display_name, role FROM Users WHERE id = ?", (user_id,)).fetchone()
            return {"token": token, "user": dict(user)}, HTTPStatus.CREATED
        if path == "/api/auth/login" and method == "POST":
            require_fields(body, "username", "password")
            user = connection.execute(
                "SELECT * FROM Users WHERE (username = ? OR email = ?) AND active = 1",
                (str(body["username"]).strip(), str(body["username"]).strip().lower()),
            ).fetchone()
            if not user or not security.verify_password(str(body["password"]), user["password_hash"]):
                raise APIError(HTTPStatus.UNAUTHORIZED, "Username or password is incorrect.")
            token = security.issue_session(connection, user["id"])
            return {"token": token, "user": {key: user[key] for key in ("id", "username", "email", "display_name", "role")}}, HTTPStatus.OK
        if path == "/api/auth/me" and method == "GET":
            return {"user": current_user(connection, self)}, HTTPStatus.OK
        if path == "/api/auth/logout" and method == "POST":
            header = self.headers.get("Authorization", "")
            token = header[7:].strip() if header.lower().startswith("bearer ") else ""
            if token:
                security.revoke_session(connection, token)
            return {"ok": True}, HTTPStatus.OK

        actor = current_user(connection, self)
        if path == "/api/bookings" and method == "GET":
            return booking_list(connection, actor, None), HTTPStatus.OK
        if path in {"/api/hotel/bookings", "/api/parking/bookings"}:
            booking_type = "Hotel" if "/hotel/" in path else "Parking"
            if method == "GET":
                return booking_list(connection, actor, booking_type), HTTPStatus.OK
            if method == "POST":
                return create_booking(connection, actor, booking_type, body), HTTPStatus.CREATED
        if path == "/api/rooms" and method == "GET":
            if actor["role"] == "Parking Personnel":
                raise APIError(HTTPStatus.FORBIDDEN, "Hotel personnel or users can view room availability.")
            return list_resources(connection, "Hotel", query), HTTPStatus.OK
        if path == "/api/parking/slots" and method == "GET":
            if actor["role"] == "Hotel Personnel":
                raise APIError(HTTPStatus.FORBIDDEN, "Parking personnel or users can view parking availability.")
            return list_resources(connection, "Parking", query), HTTPStatus.OK
        if path == "/api/personnel" and method == "GET":
            if actor["role"] == "User":
                raise APIError(HTTPStatus.FORBIDDEN, "Personnel records are not available to user accounts.")
            rows = connection.execute(
                """SELECT Users.id, Users.username, Users.email, Users.display_name, Users.role,
                          Personnel.department, Personnel.active
                   FROM Personnel JOIN Users ON Users.id = Personnel.user_id ORDER BY Users.display_name"""
            ).fetchall()
            return [dict(row) for row in rows if actor["role"] == "Admin" or row["department"] == actor.get("department")], HTTPStatus.OK
        if path == "/api/personnel" and method == "POST":
            require_admin(actor)
            require_fields(body, "userId", "department")
            department = str(body["department"])
            if department not in {"Hotel", "Parking"}:
                raise APIError(HTTPStatus.BAD_REQUEST, "Department must be Hotel or Parking.")
            role = ROLE_FOR_TYPE[department]
            target = connection.execute("SELECT * FROM Users WHERE id = ?", (body["userId"],)).fetchone()
            if not target:
                raise APIError(HTTPStatus.NOT_FOUND, "User account not found.")
            connection.execute("UPDATE Users SET role = ? WHERE id = ?", (role, target["id"]))
            connection.execute(
                "INSERT INTO Personnel (user_id, department, active, created_at) VALUES (?, ?, 1, ?)",
                (target["id"], department, utc_now()),
            )
            return {"userId": target["id"], "department": department, "role": role}, HTTPStatus.CREATED
        if path == "/api/users" and method == "GET":
            require_admin(actor)
            rows = connection.execute(
                "SELECT id, username, email, display_name, role FROM Users WHERE active = 1 ORDER BY display_name"
            ).fetchall()
            return [dict(row) for row in rows], HTTPStatus.OK
        if path == "/api/notifications" and method == "GET":
            rows = connection.execute(
                """SELECT * FROM Notifications WHERE recipient_user_id = ? OR audience_role = ? OR ? = 'Admin'
                   ORDER BY created_at DESC LIMIT 100""",
                (actor["id"], actor["role"], actor["role"]),
            ).fetchall()
            return [dict(row) for row in rows], HTTPStatus.OK
        if len(parts) == 4 and parts[:2] == ["api", "notifications"] and parts[3] == "read" and method == "PUT":
            changed = connection.execute(
                """UPDATE Notifications SET read_at = ? WHERE id = ?
                   AND (recipient_user_id = ? OR audience_role = ? OR ? = 'Admin')""",
                (utc_now(), parts[2], actor["id"], actor["role"], actor["role"]),
            ).rowcount
            if not changed:
                raise APIError(HTTPStatus.NOT_FOUND, "Notification not found.")
            return {"ok": True}, HTTPStatus.OK
        if path == "/api/history" and method == "GET":
            booking_id = query.get("bookingId", [""])[0]
            booking_type = query.get("type", [""])[0]
            if booking_id:
                if booking_type not in TABLE_FOR_TYPE:
                    raise APIError(HTTPStatus.BAD_REQUEST, "History requires a valid reservation type.")
                booking = find_booking(connection, booking_type, booking_id)
                require_booking_access(actor, booking_type, booking)
                rows = connection.execute(
                    """SELECT BookingHistory.*, Users.display_name AS actor_name FROM BookingHistory
                       LEFT JOIN Users ON Users.id = BookingHistory.actor_user_id
                       WHERE booking_type = ? AND booking_id = ? ORDER BY created_at DESC""",
                    (booking_type, booking_id),
                ).fetchall()
            elif actor["role"] == "Admin":
                rows = connection.execute(
                    """SELECT BookingHistory.*, Users.display_name AS actor_name FROM BookingHistory
                       LEFT JOIN Users ON Users.id = BookingHistory.actor_user_id ORDER BY created_at DESC LIMIT 200"""
                ).fetchall()
            else:
                raise APIError(HTTPStatus.BAD_REQUEST, "A bookingId and type are required.")
            return [dict(row) for row in rows], HTTPStatus.OK
        if len(parts) >= 4 and parts[0:2] == ["api", "bookings"]:
            booking_id = parts[2]
            booking_type = "Hotel" if booking_id.startswith("HTL-") else "Parking" if booking_id.startswith("PKG-") else ""
            if not booking_type:
                raise APIError(HTTPStatus.NOT_FOUND, "Reservation not found.")
            action = parts[3]
            if method in {"PUT", "POST"}:
                result = apply_action(connection, actor, booking_type, booking_id, action, body)
                return result, HTTPStatus.OK
        if len(parts) == 5 and parts[0] == "api" and parts[2] == "bookings":
            booking_type = "Hotel" if parts[1] == "hotel" else "Parking" if parts[1] == "parking" else ""
            if not booking_type:
                raise APIError(HTTPStatus.NOT_FOUND, "Reservation not found.")
            if method == "PUT":
                return apply_action(connection, actor, booking_type, parts[3], parts[4], body), HTTPStatus.OK
        if len(parts) == 4 and parts[0] == "api" and parts[1] in {"hotel", "parking"} and parts[2] == "bookings":
            booking_type = "Hotel" if parts[1] == "hotel" else "Parking"
            if method in {"PATCH", "PUT"}:
                return update_booking(connection, actor, booking_type, parts[3], body), HTTPStatus.OK
        if len(parts) == 3 and parts[0:2] == ["api", "bookings"] and method in {"PATCH", "PUT"}:
            booking_id = parts[2]
            booking_type = "Hotel" if booking_id.startswith("HTL-") else "Parking" if booking_id.startswith("PKG-") else ""
            if not booking_type:
                raise APIError(HTTPStatus.NOT_FOUND, "Reservation not found.")
            return update_booking(connection, actor, booking_type, booking_id, body), HTTPStatus.OK
        raise APIError(HTTPStatus.NOT_FOUND, "API route not found.")

    def log_message(self, format_string: str, *args: Any) -> None:
        sys.stdout.write(f"{self.address_string()} - {format_string % args}\n")


def create_admin() -> None:
    import getpass

    email = input("Admin email: ").strip().lower()
    username = input("Admin username: ").strip()
    display_name = input("Display name: ").strip()
    password = getpass.getpass("Admin password (10+ characters): ")
    if len(password) < 10:
        raise SystemExit("Password must be at least 10 characters.")
    database.initialize()
    with database.connect() as connection:
        user_id = str(uuid.uuid4())
        connection.execute(
            """INSERT INTO Users (id, username, email, display_name, password_hash, role, created_at)
               VALUES (?, ?, ?, ?, ?, 'Admin', ?)""",
            (user_id, username, email, display_name, security.hash_password(password), utc_now()),
        )
    print(f"Administrator account created for {email}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Central Channel API and local static web host")
    parser.add_argument("--create-admin", action="store_true", help="Create the first administrator account interactively")
    args = parser.parse_args()
    database.initialize()
    if args.create_admin:
        create_admin()
        return
    server = ThreadingHTTPServer((config.HOST, config.PORT), CentralHandler)
    print(f"Central Channel running at http://{config.HOST}:{config.PORT}")
    print(f"SQLite database: {config.DATABASE_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Central Channel.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()