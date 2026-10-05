from __future__ import annotations

import json
import tempfile
import threading
import unittest
import uuid
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import config, database, security
from .server import CentralHandler, utc_now


class ReservationAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = config.DATABASE_PATH
        config.DATABASE_PATH = Path(self.temp_dir.name) / "api-test.sqlite3"
        database.initialize()
        self.users: dict[str, dict[str, str]] = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), CentralHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self._add_user("customer", "User")
        self._add_user("hotel", "Hotel Personnel", "Hotel")
        self._add_user("parking", "Parking Personnel", "Parking")
        self._add_user("admin", "Admin")
        for key in self.users:
            self.users[key]["token"] = self._login(key)

    def tearDown(self) -> None:
        if hasattr(self, "server"):
            self.server.shutdown()
            self.server.server_close()
            self.server_thread.join(timeout=3)
        config.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def _add_user(self, key: str, role: str, department: str = "") -> None:
        user_id = str(uuid.uuid4())
        with database.connect() as connection:
            connection.execute(
                """INSERT INTO Users (id, username, email, display_name, password_hash, role, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, key, f"{key}@example.test", key.title(), security.hash_password("correct-horse-battery"), role, utc_now()),
            )
            if department:
                connection.execute(
                    "INSERT INTO Personnel (user_id, department, created_at) VALUES (?, ?, ?)",
                    (user_id, department, utc_now()),
                )
        self.users[key] = {"id": user_id}

    def _login(self, username: str) -> str:
        result, status = self._request("POST", "/api/auth/login", {"username": username, "password": "correct-horse-battery"})
        self.assertEqual(status, 200)
        return result["token"]

    def _request(self, method: str, path: str, body: dict | None = None, token: str = "") -> tuple[dict | list, int]:
        data = json.dumps(body).encode() if body is not None else None
        request = Request(f"{self.base_url}{path}", data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urlopen(request, timeout=3) as response:
                return json.loads(response.read()), response.status
        except HTTPError as error:
            return json.loads(error.read()), error.code

    def test_hotel_approval_checkin_checkout_and_audit(self) -> None:
        check_in = (date.today() + timedelta(days=4)).isoformat()
        check_out = (date.today() + timedelta(days=6)).isoformat()
        booking, status = self._request("POST", "/api/hotel/bookings", {
            "name": "Guest One", "email": "guest@example.test", "property": "Central Hotel",
            "roomType": "Deluxe", "checkIn": check_in, "checkOut": check_out, "guests": 2,
        }, self.users["customer"]["token"])
        self.assertEqual(status, 201)

        approved, status = self._request(
            "PUT", f"/api/bookings/{booking['id']}/approve", {}, self.users["hotel"]["token"]
        )
        self.assertEqual(status, 200)
        self.assertEqual(approved["status"], "Approved")
        self.assertTrue(approved["room"])
        room_id = approved["roomId"]

        checked_in, status = self._request(
            "PUT", f"/api/bookings/{booking['id']}/check-in", {}, self.users["hotel"]["token"]
        )
        self.assertEqual(status, 200)
        self.assertEqual(checked_in["status"], "Checked In")
        with database.connect() as connection:
            self.assertEqual(connection.execute("SELECT status FROM Rooms WHERE id = ?", (room_id,)).fetchone()[0], "Occupied")

        completed, status = self._request(
            "PUT", f"/api/bookings/{booking['id']}/check-out", {}, self.users["hotel"]["token"]
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["status"], "Completed")
        with database.connect() as connection:
            self.assertEqual(connection.execute("SELECT status FROM Rooms WHERE id = ?", (room_id,)).fetchone()[0], "Available")

        history, status = self._request(
            "GET", f"/api/history?bookingId={booking['id']}&type=Hotel", token=self.users["customer"]["token"]
        )
        self.assertEqual(status, 200)
        self.assertEqual([item["action"] for item in history], ["check-out", "check-in", "approve", "created"])

        notifications, status = self._request("GET", "/api/notifications", token=self.users["customer"]["token"])
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(notifications), 4)

    def test_department_access_and_customer_ownership(self) -> None:
        booking, status = self._request("POST", "/api/parking/bookings", {
            "name": "Guest Two", "email": "guest2@example.test", "property": "Main Garage",
            "vehicle": "Car", "plate": "TEST-42", "parkingDate": (date.today() + timedelta(days=2)).isoformat(),
            "parkingTime": "10:00", "durationHours": 2,
        }, self.users["customer"]["token"])
        self.assertEqual(status, 201)

        _, status = self._request("PUT", f"/api/bookings/{booking['id']}/approve", {}, self.users["hotel"]["token"])
        self.assertEqual(status, 403)
        _, status = self._request("GET", "/api/bookings", token=self.users["parking"]["token"])
        self.assertEqual(status, 200)
        _, status = self._request("GET", "/api/bookings", token=self.users["admin"]["token"])
        self.assertEqual(status, 200)

        other, status = self._request("POST", "/api/auth/register", {
            "username": "new-customer", "email": "new@example.test", "password": "a-long-enough-password",
        })
        self.assertEqual(status, 201)
        own_bookings, status = self._request("GET", "/api/bookings", token=other["token"])
        self.assertEqual(status, 200)
        self.assertEqual(own_bookings, [])
        _, status = self._request("GET", "/api/bookings")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()