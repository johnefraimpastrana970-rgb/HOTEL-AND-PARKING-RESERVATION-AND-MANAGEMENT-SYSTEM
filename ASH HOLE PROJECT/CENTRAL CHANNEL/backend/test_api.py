from __future__ import annotations

import json
import threading
import unittest
import uuid
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import config, database, security
from .server import APIError, CentralHandler, create_admin_account, make_qr_image, now


class AdminAccountCreationTests(unittest.TestCase):
    def test_admin_creation_endpoint_rejects_non_admin(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.path = "/api/admin/users"
        with patch("backend.server.actor_for", return_value={"role": "User"}), patch.object(
            CentralHandler, "read_body", return_value={},
        ), patch("backend.server.security.register") as register:
            with self.assertRaisesRegex(APIError, "Administrator access"):
                handler.dispatch(None, "POST")
        register.assert_not_called()

    def test_creates_admin_auth_user_and_profile(self) -> None:
        class Cursor:
            def __init__(self, row=None):
                self.row = row

            def fetchone(self):
                return self.row

        class Connection:
            def __init__(self):
                self.statements = []

            def execute(self, query, params=()):
                self.statements.append((query, tuple(params)))
                if query.startswith("SELECT 1 FROM Users"):
                    return Cursor()
                if query.startswith("SELECT id,username,email,display_name,role FROM Users"):
                    user_id, = params
                    return Cursor({
                        "id": user_id, "username": "newadmin", "email": "newadmin@example.test",
                        "display_name": "New Admin", "role": "Admin",
                    })
                return Cursor()

        connection = Connection()
        with patch(
            "backend.server.security.register",
            return_value={"user": {"id": "auth-user-id", "identities": [{"provider": "email"}]}},
        ) as register:
            result = create_admin_account(connection, {
                "username": "newadmin", "email": "NewAdmin@example.test",
                "displayName": "New Admin", "password": "a-unique-long-password",
            })

        register.assert_called_once_with(
            "newadmin@example.test", "a-unique-long-password", "newadmin", "New Admin",
        )
        profile_insert = next(query for query, _ in connection.statements if query.startswith("INSERT INTO Users"))
        self.assertIn("'Admin'", profile_insert)
        self.assertEqual(result["user"]["role"], "Admin")
        self.assertTrue(result["requiresEmailConfirmation"])

    def test_rejects_short_password_before_creating_auth_user(self) -> None:
        class Connection:
            def execute(self, query, params=()):
                raise AssertionError("Database should not be queried for an invalid password.")

        with patch("backend.server.security.register") as register:
            with self.assertRaisesRegex(APIError, "at least 10 characters"):
                create_admin_account(Connection(), {
                    "username": "newadmin", "email": "newadmin@example.test", "password": "short",
                })
        register.assert_not_called()


class QrImageGenerationTests(unittest.TestCase):
    def test_qr_svg_has_explicit_square_dimensions_and_contrast(self) -> None:
        import base64

        data_uri = make_qr_image('{"format":"NEXORA_RESERVATION","receiptCode":"NXR-1234ABCD"}')
        self.assertTrue(data_uri.startswith("data:image/svg+xml;base64,"))
        svg = base64.b64decode(data_uri.partition(",")[2]).decode("utf-8")
        self.assertRegex(svg, r'<svg[^>]*width="\d+"[^>]*height="\d+"[^>]*viewBox="0 0 ([\d.]+) \1"')
        self.assertIn('style="fill:#000"', svg)
        self.assertIn('<rect width="100%" height="100%" fill="#fff"/>', svg)
        self.assertIn('shape-rendering="crispEdges"', svg)


class LegacyReservationPageRedirectTests(unittest.TestCase):
    def test_renamed_page_redirect_preserves_login_profile_parameters(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.path = (
            "/HOME%20PAGE/Test-Site_-reservation-prototype-2.html"
            "?authenticated=1&username=guest&email=guest%40example.test"
        )
        with patch.object(handler, "send_response") as send_response, patch.object(
            handler, "send_header",
        ) as send_header, patch.object(handler, "end_headers"):
            handler.do_GET()

        send_response.assert_called_once_with(302)
        send_header.assert_any_call(
            "Location",
            "/HOME%20PAGE/main.html?authenticated=1&username=guest&email=guest%40example.test",
        )


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
            "paymentMethod": "bank_transfer",
        }, guest)
        self.assertEqual(status, 201)
        with database.connect() as connection:
            saved_booking = connection.execute(
                "SELECT id,user_id,property_name,check_in,check_out,guest_count,payment_method FROM HotelBookings WHERE id=?",
                (booking["id"],),
            ).fetchone()
        self.assertEqual(saved_booking["user_id"], self.accounts["guest"]["id"])
        self.assertEqual(saved_booking["property_name"], "Central Hotel")
        self.assertEqual(saved_booking["check_in"], check_in)
        self.assertEqual(saved_booking["check_out"], check_out)
        self.assertEqual(saved_booking["guest_count"], 2)
        self.assertEqual(saved_booking["payment_method"], "bank_transfer")
        self.assertEqual(booking["paymentMethod"], "Bank Transfer")

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

    def test_customer_bookings_are_visible_in_admin_queue(self) -> None:
        guest_token = self.accounts["guest"]["token"]
        admin_token = self.accounts["admin"]["token"]
        check_in = (date.today() + timedelta(days=8)).isoformat()
        check_out = (date.today() + timedelta(days=10)).isoformat()
        hotel_booking, status = self.request("POST", "/api/hotel/bookings", {
            "name": "Queue Guest", "email": "guest@example.test", "property": "Central Hotel",
            "roomType": "Standard", "checkIn": check_in, "checkOut": check_out, "guests": 1,
        }, guest_token)
        self.assertEqual(status, 201)
        parking_booking, status = self.request("POST", "/api/parking/bookings", {
            "name": "Queue Guest", "email": "guest@example.test", "property": "Main Garage",
            "vehicle": "Car", "plate": "QUEUE-42", "parkingDate": check_in,
            "parkingTime": "10:00", "durationHours": 2,
        }, guest_token)
        self.assertEqual(status, 201)

        queue, status = self.request("GET", "/api/bookings", token=admin_token)
        self.assertEqual(status, 200)
        visible = {booking["id"]: booking for booking in queue}
        self.assertEqual(visible[hotel_booking["id"]]["status"], "Pending")
        self.assertEqual(visible[hotel_booking["id"]]["type"], "Hotel")
        self.assertEqual(visible[parking_booking["id"]]["status"], "Pending")
        self.assertEqual(visible[parking_booking["id"]]["type"], "Parking")

    def test_confirmed_stay_and_parking_receive_one_admin_verifiable_qr_pass(self) -> None:
        guest_token = self.accounts["guest"]["token"]
        admin_token = self.accounts["admin"]["token"]
        check_in = (date.today() + timedelta(days=12)).isoformat()
        check_out = (date.today() + timedelta(days=14)).isoformat()
        hotel_booking, status = self.request("POST", "/api/hotel/bookings", {
            "name": "QR Guest", "email": "guest@example.test", "property": "Central Hotel",
            "roomType": "Standard", "checkIn": check_in, "checkOut": check_out, "guests": 1,
        }, guest_token)
        self.assertEqual(status, 201)
        parking_booking, status = self.request("POST", "/api/parking/bookings", {
            "name": "QR Guest", "email": "guest@example.test", "property": "Main Garage",
            "vehicle": "Car", "plate": "QRTEST-4", "parkingDate": check_in,
            "parkingTime": "10:00", "durationHours": 2,
        }, guest_token)
        self.assertEqual(status, 201)
        passes, status = self.request("GET", "/api/qr/passes", token=guest_token)
        self.assertEqual(status, 200)
        self.assertEqual(len(passes), 2)
        pending_hotel_pass = next(
            qr_pass for qr_pass in passes if qr_pass["hotelBookingId"] == hotel_booking["id"]
        )
        pending_parking_pass = next(
            qr_pass for qr_pass in passes if qr_pass["parkingBookingId"] == parking_booking["id"]
        )
        self.assertEqual(pending_hotel_pass["status"], "Pending")
        self.assertEqual(pending_parking_pass["status"], "Pending")
        self.assertIsNone(pending_hotel_pass["hotel"]["room"])
        self.assertIsNone(pending_parking_pass["parking"]["slot"])
        self.assertTrue(pending_hotel_pass["qrImage"].startswith("data:image/svg+xml;base64,"))
        pending_verification, status = self.request(
            "GET", f"/api/qr/verify/{pending_hotel_pass['receiptCode']}", token=admin_token,
        )
        self.assertEqual(status, 200)
        self.assertFalse(pending_verification["valid"])
        self.assertEqual(pending_verification["status"], "Pending")

        _, status = self.request("PUT", f"/api/bookings/{hotel_booking['id']}/approve", {}, admin_token)
        self.assertEqual(status, 200)
        passes, status = self.request("GET", "/api/qr/passes", token=guest_token)
        self.assertEqual(status, 200)
        self.assertEqual(len(passes), 2)
        hotel_pass = next(
            qr_pass for qr_pass in passes if qr_pass["hotelBookingId"] == hotel_booking["id"]
        )
        self.assertEqual(hotel_pass["status"], "Active")
        self.assertTrue(hotel_pass["hotel"]["room"])
        _, status = self.request("PUT", f"/api/bookings/{parking_booking['id']}/approve", {}, admin_token)
        self.assertEqual(status, 200)

        passes, status = self.request("GET", "/api/qr/passes", token=guest_token)
        self.assertEqual(status, 200)
        self.assertEqual(len(passes), 1)
        qr_pass = passes[0]
        self.assertEqual(qr_pass["hotelBookingId"], hotel_booking["id"])
        self.assertEqual(qr_pass["parkingBookingId"], parking_booking["id"])
        self.assertTrue(qr_pass["hotel"]["room"])
        self.assertEqual(qr_pass["hotel"]["floor"], 1)
        self.assertTrue(qr_pass["parking"]["slot"])
        self.assertTrue(qr_pass["qrImage"].startswith("data:image/svg+xml;base64,"))
        with database.connect() as connection:
            saved = connection.execute(
                """SELECT username,user_email,hotel_room,hotel_floor,parking_slot,receipt_code
                   FROM QRTickets WHERE receipt_code=?""",
                (qr_pass["receiptCode"],),
            ).fetchone()
        self.assertEqual(saved["username"], "guest")
        self.assertEqual(saved["user_email"], "guest@example.test")
        self.assertEqual(saved["hotel_room"], qr_pass["hotel"]["room"])
        self.assertEqual(saved["hotel_floor"], 1)
        self.assertEqual(saved["parking_slot"], qr_pass["parking"]["slot"])

        verified, status = self.request(
            "GET", f"/api/qr/verify/{qr_pass['receiptCode']}", token=admin_token,
        )
        self.assertEqual(status, 200)
        self.assertTrue(verified["valid"])
        self.assertEqual(verified["email"], "guest@example.test")
        _, status = self.request(
            "GET", f"/api/qr/verify/{qr_pass['receiptCode']}", token=guest_token,
        )
        self.assertEqual(status, 403)

        _, status = self.request("PUT", f"/api/bookings/{hotel_booking['id']}/cancel", {}, guest_token)
        self.assertEqual(status, 200)
        passes, status = self.request("GET", "/api/qr/passes", token=guest_token)
        self.assertEqual(status, 200)
        self.assertEqual(len(passes), 1)
        self.assertEqual(passes[0]["status"], "Active")
        self.assertIsNone(passes[0]["hotel"])
        self.assertEqual(passes[0]["parking"]["slot"], qr_pass["parking"]["slot"])
        verified, status = self.request(
            "GET", f"/api/qr/verify/{qr_pass['receiptCode']}", token=admin_token,
        )
        self.assertEqual(status, 200)
        self.assertTrue(verified["valid"])
        self.assertIsNone(verified["hotel"])

        _, status = self.request("PUT", f"/api/bookings/{parking_booking['id']}/cancel", {}, guest_token)
        self.assertEqual(status, 200)
        passes, status = self.request("GET", "/api/qr/passes", token=guest_token)
        self.assertEqual(status, 200)
        self.assertEqual(passes[0]["status"], "Cancelled")

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

    def test_hotel_booking_rejects_unsupported_payment_method(self) -> None:
        check_in = (date.today() + timedelta(days=5)).isoformat()
        check_out = (date.today() + timedelta(days=7)).isoformat()
        _, status = self.request("POST", "/api/hotel/bookings", {
            "name": "Guest One", "email": "guest@example.test", "property": "Central Hotel",
            "roomType": "Standard", "checkIn": check_in, "checkOut": check_out,
            "paymentMethod": "credit_card",
        }, self.accounts["guest"]["token"])
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()