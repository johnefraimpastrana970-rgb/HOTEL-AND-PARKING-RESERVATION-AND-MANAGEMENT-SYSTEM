from __future__ import annotations

import json
import threading
import unittest
import uuid
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import config, database, security
from .server import CentralHandler, now


@unittest.skipUnless(
    config.SUPABASE_DATABASE_URL and config.SUPABASE_URL and config.SUPABASE_PUBLISHABLE_KEY and config.SUPABASE_SECRET_KEY,
    "Set Supabase database, URL, publishable, and secret keys to run API integration tests.",
)
class CentralApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth_user_ids = []
        self.old_schema = config.SUPABASE_DATABASE_SCHEMA
        self.test_schema = f"central_test_{uuid.uuid4().hex}"
        config.SUPABASE_DATABASE_SCHEMA = "public"
        with database.connect() as connection:
            connection.execute(f'CREATE SCHEMA "{self.test_schema}"')
        config.SUPABASE_DATABASE_SCHEMA = self.test_schema
        database.initialize()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), CentralHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.accounts = {}
        self.add_user("guest", "User")
        self.add_user("hotel", "Hotel Personnel", "Hotel")
        self.add_user("parking", "Parking Personnel", "Parking")
        self.add_user("admin", "Admin")
        for key in self.accounts:
            self.accounts[key]["token"] = self.login(key)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        config.SUPABASE_DATABASE_SCHEMA = "public"
        with database.connect() as connection:
            connection.execute(f'DROP SCHEMA "{self.test_schema}" CASCADE')
        config.SUPABASE_DATABASE_SCHEMA = self.old_schema
        for user_id in self.auth_user_ids:
            try:
                security.delete_user(user_id)
            except security.SupabaseAuthError:
                pass

    def add_user(self, username: str, role: str, department: str = "") -> None:
        email = f"{username}@example.test"
        auth_result = security.create_user(email, "correct-horse-battery", username, username.title())
        auth_user = auth_result.get("user") or auth_result
        user_id = auth_user["id"]
        self.auth_user_ids.append(user_id)
        with database.connect() as connection:
            connection.execute(
                """INSERT INTO Users(id,username,email,display_name,password_hash,role,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (user_id, username, email, username.title(), "", role, now()),
            )
            if department:
                connection.execute("INSERT INTO Personnel(user_id,department,created_at) VALUES(?,?,?)", (user_id, department, now()))
        self.accounts[username] = {"id": user_id}

    def request(self, method: str, path: str, body: dict | None = None, token: str = ""):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(f"{self.base}{path}", data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urlopen(request, timeout=3) as response:
                return json.loads(response.read()), response.status
        except HTTPError as error:
            payload, status = json.loads(error.read()), error.code
            error.close()
            return payload, status

    def login(self, username: str) -> str:
        payload, status = self.request("POST", "/api/auth/login", {"username": username, "password": "correct-horse-battery"})
        self.assertEqual(status, 200)
        return payload["token"]

    def test_hotel_room_lifecycle_history_and_notifications(self) -> None:
        check_in = (date.today() + timedelta(days=5)).isoformat()
        check_out = (date.today() + timedelta(days=7)).isoformat()
        guest = self.accounts["guest"]["token"]
        staff = self.accounts["hotel"]["token"]
        booking, status = self.request("POST", "/api/hotel/bookings", {
            "name": "Guest One", "email": "guest@example.test", "property": "Central Hotel",
            "roomType": "Deluxe", "checkIn": check_in, "checkOut": check_out, "guests": 2,
        }, guest)
        self.assertEqual(status, 201)

        booking, status = self.request("PUT", f"/api/bookings/{booking['id']}/approve", {}, staff)
        self.assertEqual(status, 200)
        room_id = booking["roomId"]
        self.assertEqual(booking["status"], "Approved")
        rooms, status = self.request("GET", f"/api/rooms?checkIn={check_in}&checkOut={check_out}&bookingId={booking['id']}", token=staff)
        self.assertEqual(status, 200)
        self.assertTrue(next(room for room in rooms if room["id"] == room_id)["available"])

        booking, _ = self.request("PUT", f"/api/bookings/{booking['id']}/check-in", {}, staff)
        self.assertEqual(booking["status"], "Checked In")
        with database.connect() as connection:
            self.assertEqual(connection.execute("SELECT status FROM Rooms WHERE id=?", (room_id,)).fetchone()["status"], "Occupied")
        booking, _ = self.request("PUT", f"/api/bookings/{booking['id']}/check-out", {}, staff)
        self.assertEqual(booking["status"], "Completed")
        with database.connect() as connection:
            self.assertEqual(connection.execute("SELECT status FROM Rooms WHERE id=?", (room_id,)).fetchone()["status"], "Available")

        history, _ = self.request("GET", f"/api/history?type=Hotel&bookingId={booking['id']}", token=guest)
        self.assertEqual([item["action"] for item in history], ["check-out", "check-in", "approve", "created"])
        notices, _ = self.request("GET", "/api/notifications", token=guest)
        self.assertIn("booking_approved", [item["category"] for item in notices])

    def test_parking_assignment_role_scope_and_customer_cancel(self) -> None:
        guest = self.accounts["guest"]["token"]
        parking_staff = self.accounts["parking"]["token"]
        hotel_staff = self.accounts["hotel"]["token"]
        body = {
            "name": "Guest Two", "email": "guest2@example.test", "property": "Main Garage",
            "vehicle": "Car", "plate": "TEST-42", "parkingDate": (date.today() + timedelta(days=3)).isoformat(),
            "parkingTime": "10:00", "durationHours": 2,
        }
        booking, status = self.request("POST", "/api/parking/bookings", body, guest)
        self.assertEqual(status, 201)
        _, status = self.request("PUT", f"/api/bookings/{booking['id']}/approve", {}, hotel_staff)
        self.assertEqual(status, 403)
        _, status = self.request("GET", "/api/parking/bookings", token=hotel_staff)
        self.assertEqual(status, 403)
        hotel_queue, status = self.request("GET", "/api/bookings", token=hotel_staff)
        self.assertEqual(status, 200)
        self.assertTrue(all(item["type"] == "Hotel" for item in hotel_queue))
        booking, status = self.request("PUT", f"/api/bookings/{booking['id']}/approve", {}, parking_staff)
        self.assertEqual(status, 200)
        slot_id = booking["slotId"]
        self.assertTrue(booking["slot"])
        cancelled, status = self.request("PUT", f"/api/bookings/{booking['id']}/cancel", {}, guest)
        self.assertEqual(status, 200)
        self.assertEqual(cancelled["status"], "Cancelled")
        with database.connect() as connection:
            self.assertEqual(connection.execute("SELECT status FROM ParkingSlots WHERE id=?", (slot_id,)).fetchone()["status"], "Available")
        self.add_user("other", "User")
        other_token = self.login("other")
        _, status = self.request("PUT", f"/api/bookings/{booking['id']}/cancel", {}, other_token)
        self.assertEqual(status, 403)

    def test_fresh_database_bootstraps_only_first_signup_as_admin(self) -> None:
        with database.connect() as connection:
            connection.execute("DELETE FROM Sessions")
            connection.execute("DELETE FROM Personnel")
            connection.execute("DELETE FROM Users")
        first, status = self.request("POST", "/api/auth/register", {
            "username": "owner", "email": "owner@example.test", "password": "a-long-enough-password",
        })
        self.assertEqual(status, 201)
        self.assertEqual(first["user"]["role"], "Admin")
        self.auth_user_ids.append(first["user"]["id"])
        second, status = self.request("POST", "/api/auth/register", {
            "username": "member", "email": "member@example.test", "password": "another-long-password",
        })
        self.assertEqual(status, 201)
        self.assertEqual(second["user"]["role"], "User")
        self.auth_user_ids.append(second["user"]["id"])

    def test_username_character_allowlist(self) -> None:
        _, status = self.request("POST", "/api/auth/register", {
            "username": "no spaces", "email": "invalid-name@example.test", "password": "a-long-enough-password",
        })
        self.assertEqual(status, 400)
        valid, status = self.request("POST", "/api/auth/register", {
            "username": "valid_*@name", "email": "valid-name@example.test", "password": "a-long-enough-password",
        })
        self.assertEqual(status, 201)
        self.assertEqual(valid["user"]["username"], "valid_*@name")
        self.auth_user_ids.append(valid["user"]["id"])


if __name__ == "__main__":
    unittest.main()