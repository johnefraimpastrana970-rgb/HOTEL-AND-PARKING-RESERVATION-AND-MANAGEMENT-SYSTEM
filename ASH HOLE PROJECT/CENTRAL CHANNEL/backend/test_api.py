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

import redis

from . import config, database, mailer, rate_limit, security, server
from .server import APIError, CentralHandler, create_admin_account, make_qr_image, now


class RateLimiterTests(unittest.TestCase):
    def test_local_limiter_blocks_until_the_window_expires(self) -> None:
        limiter = rate_limit.RateLimiter()
        key = f"test:{uuid.uuid4().hex}"

        self.assertIsNone(limiter.check(key, 1, 60))
        self.assertGreaterEqual(limiter.check(key, 1, 60), 1)

    def test_redis_limiter_uses_atomic_shared_counter_and_ttl(self) -> None:
        class FakeRedis:
            def __init__(self):
                self.calls = []

            def eval(self, script, key_count, key, window_seconds):
                self.calls.append((script, key_count, key, window_seconds))
                return [2, 17]

        limiter = rate_limit.RateLimiter("redis://localhost")
        fake = FakeRedis()
        limiter._redis = fake

        self.assertEqual(limiter.check("central:v1:api:192.0.2.1", 1, 60), 17)
        self.assertEqual(fake.calls[0][1:], (1, "central:v1:api:192.0.2.1", 60))
        self.assertIn("redis.call(\"INCR\"", fake.calls[0][0])

    def test_redis_failure_is_not_silently_treated_as_allowed(self) -> None:
        class UnavailableRedis:
            def eval(self, *_args, **_kwargs):
                raise redis.RedisError("offline")

        limiter = rate_limit.RateLimiter("redis://localhost")
        limiter._redis = UnavailableRedis()

        with self.assertRaises(rate_limit.RateLimiterUnavailable):
            limiter.check("central:v1:api:192.0.2.1", 10, 60)

    def test_rate_limit_error_includes_retry_after_seconds(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.client_address = ("192.0.2.1", 12345)
        handler.headers = {}

        with patch.object(rate_limit.RATE_LIMITER, "check", return_value=9):
            with self.assertRaises(APIError) as context:
                handler.enforce_rate_limit("/api/auth/login")

        self.assertEqual(context.exception.status, 429)
        self.assertEqual(context.exception.retry_after, 9)

    def test_rate_limited_response_sets_retry_after_header(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.path = "/api/auth/login"
        handler.client_address = ("192.0.2.1", 12345)
        handler.headers = {}

        with patch.object(rate_limit.RATE_LIMITER, "check", return_value=9), patch.object(
            CentralHandler, "respond",
        ) as respond:
            handler.handle_api("POST")

        respond.assert_called_once_with(
            429,
            {"error": "Too many requests. Please try again later."},
            {"Retry-After": "9"},
        )

    def test_support_reports_have_a_tighter_rate_limit(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.client_address = ("192.0.2.1", 12345)
        handler.headers = {}
        with patch.object(rate_limit.RATE_LIMITER, "check", side_effect=[None, 9]) as check:
            with self.assertRaises(APIError) as context:
                handler.enforce_rate_limit("/api/support/reports")

        self.assertEqual(context.exception.status, 429)
        self.assertEqual(check.call_args_list[1].args, (
            "central:v1:support:192.0.2.1",
            config.SUPPORT_REPORT_RATE_LIMIT_REQUESTS,
            config.SUPPORT_REPORT_RATE_LIMIT_WINDOW_SECONDS,
        ))

    def test_email_verification_uses_signup_rate_limit(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.client_address = ("192.0.2.1", 12345)
        handler.headers = {}
        with patch.object(rate_limit.RATE_LIMITER, "check", side_effect=[None, 9]) as check:
            with self.assertRaises(APIError) as context:
                handler.enforce_rate_limit("/api/auth/verify-email")

        self.assertEqual(context.exception.status, 429)
        self.assertEqual(check.call_args_list[1].args, (
            "central:v1:register:192.0.2.1",
            config.REGISTER_RATE_LIMIT_REQUESTS,
            config.REGISTER_RATE_LIMIT_WINDOW_SECONDS,
        ))

    def test_resend_confirmation_uses_its_separate_rate_limit(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.client_address = ("192.0.2.1", 12345)
        handler.headers = {}
        with patch.object(rate_limit.RATE_LIMITER, "check", side_effect=[None, 9]) as check:
            with self.assertRaises(APIError) as context:
                handler.enforce_rate_limit("/api/auth/resend-confirmation")

        self.assertEqual(context.exception.status, 429)
        self.assertEqual(check.call_args_list[1].args, (
            "central:v1:resend-confirmation:192.0.2.1",
            10,
            3600,
        ))

    def test_live_health_check_skips_database_and_rate_limiter(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.path = "/api/health/live"

        with patch.object(CentralHandler, "respond") as respond, patch.object(
            database, "connect", side_effect=AssertionError("Liveness must not require PostgreSQL."),
        ), patch.object(
            rate_limit.RATE_LIMITER, "check", side_effect=AssertionError("Liveness must not be throttled."),
        ):
            handler.handle_api("GET")

        respond.assert_called_once_with(200, {"status": "ok"})


class EmailVerificationTests(unittest.TestCase):
    def test_signup_creates_pending_user_without_a_session(self) -> None:
        user = {
            "id": "pending-id",
            "username": "guest",
            "email": "guest@example.test",
            "display_name": "Guest",
            "role": "User",
        }

        class Cursor:
            def __init__(self, row=None):
                self.row = row

            def fetchone(self):
                return self.row

        class Connection:
            def execute(self, query, params=()):
                del params
                if query.startswith("SELECT 1 FROM Users"):
                    return Cursor()
                if query.startswith("SELECT COUNT(*)"):
                    return Cursor({"count": 0})
                if query.startswith("SELECT id,username"):
                    return Cursor(user)
                return Cursor()

        handler = object.__new__(CentralHandler)
        handler.path = "/api/auth/register"
        body = {
            "username": "guest",
            "email": "guest@example.test",
            "password": "a-long-enough-password",
        }
        with patch.object(CentralHandler, "read_body", return_value=body), patch(
            "backend.server.security.register",
            return_value={"user": {"id": "pending-id"}},
        ) as register, patch.object(config, "FIRST_SIGNUP_ADMIN", True):
            result, status = handler.dispatch(Connection(), "POST")

        self.assertEqual(status, 201)
        self.assertEqual(result, {"user": user, "requiresEmailConfirmation": True})
        self.assertNotIn("token", result)
        register.assert_called_once_with(
            "guest@example.test",
            "a-long-enough-password",
            "guest",
            "guest",
        )

    def test_signup_returns_session_when_supabase_confirmation_is_disabled(self) -> None:
        user = {
            "id": "created-id",
            "username": "guest",
            "email": "guest@example.test",
            "display_name": "guest",
            "role": "Admin",
        }

        class Cursor:
            def __init__(self, row=None):
                self.row = row

            def fetchone(self):
                return self.row

        class Connection:
            def execute(self, query, params=()):
                if query.startswith("SELECT 1 FROM Users WHERE role"):
                    return Cursor()
                if query.startswith("SELECT id,username"):
                    return Cursor(user)
                if query.startswith("UPDATE Users SET role"):
                    self.updated_role = params
                return Cursor()

        handler = object.__new__(CentralHandler)
        handler.path = "/api/auth/register"
        body = {
            "username": "guest",
            "email": "guest@example.test",
            "password": "a-long-enough-password",
        }
        with patch.object(CentralHandler, "read_body", return_value=body), patch(
            "backend.server.security.register",
            return_value={
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "user": {"id": "created-id"},
            },
        ), patch.object(config, "FIRST_SIGNUP_ADMIN", True):
            result, status = handler.dispatch(Connection(), "POST")

        self.assertEqual(status, 201)
        self.assertEqual(result, {
            "user": user,
            "requiresEmailConfirmation": False,
            "token": "access-token",
            "refreshToken": "refresh-token",
        })

    def test_signup_rejects_supabase_duplicate_email_response(self) -> None:
        class Cursor:
            def fetchone(self):
                return None

        class Connection:
            def execute(self, *_args, **_kwargs):
                return Cursor()

        handler = object.__new__(CentralHandler)
        handler.path = "/api/auth/register"
        body = {
            "username": "another_guest",
            "email": "guest@example.test",
            "password": "a-long-enough-password",
        }
        with patch.object(CentralHandler, "read_body", return_value=body), patch(
            "backend.server.security.register",
            return_value={"user": {"id": "created-id", "identities": []}},
        ):
            with self.assertRaisesRegex(APIError, "email address is already registered"):
                handler.dispatch(Connection(), "POST")

    def test_supabase_signup_code_verification_uses_signup_otp(self) -> None:
        with patch.object(security, "_auth_request", return_value={}) as auth_request:
            security.verify_signup_email("guest@example.test", "123456")

        auth_request.assert_called_once_with(
            "verify",
            method="POST",
            body={"email": "guest@example.test", "token": "123456", "type": "signup"},
        )

    def test_supabase_resend_uses_signup_otp(self) -> None:
        with patch.object(security, "_auth_request", return_value={}) as auth_request:
            security.resend_signup_email("guest@example.test")

        auth_request.assert_called_once_with(
            "resend",
            method="POST",
            body={"email": "guest@example.test", "type": "signup"},
        )

    def test_verification_returns_a_session_only_for_matching_registered_user(self) -> None:
        user = {
            "id": "verified-id",
            "username": "guest",
            "email": "guest@example.test",
            "display_name": "Guest",
            "role": "User",
        }

        class Cursor:
            def fetchone(self):
                return user

        class Connection:
            def execute(self, query, params):
                self.query = query
                self.params = params
                return Cursor()

        handler = object.__new__(CentralHandler)
        handler.path = "/api/auth/verify-email"
        body = {"email": " GUEST@example.test ", "token": "123456"}
        auth_result = {
            "access_token": "access",
            "refresh_token": "refresh",
            "user": {"id": "verified-id"},
        }
        with patch.object(CentralHandler, "read_body", return_value=body), patch(
            "backend.server.security.verify_signup_email", return_value=auth_result,
        ) as verify, patch.object(config, "FIRST_SIGNUP_ADMIN", False):
            result, status = handler.dispatch(Connection(), "POST")

        self.assertEqual(status, 200)
        self.assertEqual(result, {
            "token": "access",
            "refreshToken": "refresh",
            "user": user,
        })
        verify.assert_called_once_with("guest@example.test", "123456")

    def test_first_confirmed_signup_becomes_admin(self) -> None:
        user = {
            "id": "verified-id",
            "username": "guest",
            "email": "guest@example.test",
            "display_name": "Guest",
            "role": "User",
        }

        class Cursor:
            def __init__(self, row=None):
                self.row = row

            def fetchone(self):
                return self.row

        class Connection:
            def __init__(self):
                self.updated = False

            def execute(self, query, params=()):
                if query.startswith("SELECT id,username"):
                    return Cursor(user)
                if query.startswith("SELECT 1 FROM Users WHERE role"):
                    return Cursor()
                if query.startswith("UPDATE Users SET role"):
                    self.updated = params == ("verified-id",)
                    return Cursor()
                return Cursor()

        connection = Connection()
        handler = object.__new__(CentralHandler)
        handler.path = "/api/auth/verify-email"
        body = {"email": "guest@example.test", "token": "123456"}
        auth_result = {
            "access_token": "access",
            "user": {"id": "verified-id"},
        }
        with patch.object(CentralHandler, "read_body", return_value=body), patch(
            "backend.server.security.verify_signup_email", return_value=auth_result,
        ), patch.object(config, "FIRST_SIGNUP_ADMIN", True):
            result, status = handler.dispatch(connection, "POST")

        self.assertEqual(status, 200)
        self.assertEqual(result["user"]["role"], "Admin")
        self.assertTrue(connection.updated)

    def test_resend_confirmation_response_does_not_disclose_account_status(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.path = "/api/auth/resend-confirmation"
        with patch.object(
            CentralHandler, "read_body", return_value={"email": "guest@example.test"},
        ), patch("backend.server.security.resend_signup_email") as resend:
            result, status = handler.dispatch(None, "POST")

        self.assertEqual(status, 200)
        self.assertEqual(result, {
            "message": "If the account is awaiting confirmation, a new code has been sent.",
        })
        resend.assert_called_once_with("guest@example.test")


class SupportReportTests(unittest.TestCase):
    def test_support_report_is_saved_with_authenticated_owner_and_optional_request_id(self) -> None:
        class Connection:
            def __init__(self):
                self.statement = None

            def execute(self, query, params=()):
                self.statement = (query, tuple(params))

        connection = Connection()
        result = server.create_support_report(
            connection,
            {"id": "guest-id"},
            {"category": "Booking", "message": "  Booking page did not load.  ", "requestId": "a" * 32},
        )

        self.assertEqual(len(result["id"]), 32)
        self.assertEqual(connection.statement[1][:5], (
            result["id"], "guest-id", "Booking", "Booking page did not load.", "a" * 32,
        ))

    def test_support_report_rejects_invalid_category_empty_or_oversized_message(self) -> None:
        class Connection:
            def execute(self, *_args, **_kwargs):
                raise AssertionError("Invalid reports must not be stored.")

        for payload, message in (
            ({"category": "Internal logs", "message": "test"}, "valid report category"),
            ({"category": "Other", "message": "  "}, "Describe the issue"),
            ({"category": "Other", "message": "x" * 2001}, "2,000 characters"),
            ({"category": "Other", "message": "test", "requestId": "not-a-request-id"}, "request reference"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(APIError, message):
                    server.create_support_report(Connection(), {"id": "guest-id"}, payload)

    def test_customer_can_submit_a_support_report(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.path = "/api/support/reports"
        report = {"id": "report-id", "createdAt": now()}
        actor = {
            "id": "guest-id", "role": "User", "email": "guest@example.test",
            "display_name": "Guest",
        }
        with patch("backend.server.actor_for", return_value=actor), patch.object(
            CentralHandler, "read_body", return_value={"category": "Service issue", "message": "Service unavailable."},
        ), patch("backend.server.create_support_report", return_value=report) as create_report, patch(
            "backend.server.mailer.send_hotel_email",
        ) as send_email:
            result, status = handler.dispatch(None, "POST")

        self.assertEqual((result, status), ({**report, "emailSent": True}, 201))
        create_report.assert_called_once_with(
            None, actor,
            {"category": "Service issue", "message": "Service unavailable."},
        )
        send_email.assert_called_once()
        self.assertEqual(send_email.call_args.args[0], config.HOTEL_EMAIL)
        self.assertEqual(send_email.call_args.kwargs["reply_to"], "guest@example.test")

    def test_support_report_is_saved_when_email_delivery_is_not_configured(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.path = "/api/support/reports"
        actor = {
            "id": "guest-id", "role": "User", "email": "guest@example.test",
            "display_name": "Guest",
        }
        report = {"id": "report-id", "createdAt": now()}
        with patch("backend.server.actor_for", return_value=actor), patch.object(
            CentralHandler, "read_body", return_value={"category": "Other", "message": "Help"},
        ), patch("backend.server.create_support_report", return_value=report), patch(
            "backend.server.mailer.send_hotel_email",
            side_effect=mailer.MailDeliveryError("SMTP is not configured."),
        ):
            result, status = handler.dispatch(None, "POST")

        self.assertEqual(status, 201)
        self.assertEqual(result["emailSent"], False)
        self.assertEqual(result["emailError"], "SMTP is not configured.")

    def test_customer_cannot_read_admin_support_reports(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.path = "/api/admin/support/reports"
        with patch("backend.server.actor_for", return_value={"id": "guest-id", "role": "User"}):
            with self.assertRaisesRegex(APIError, "Administrator access"):
                handler.dispatch(None, "GET")

    def test_admin_support_report_endpoint_returns_latest_report_rows(self) -> None:
        rows = [{"id": "report-id", "message": "Booking issue"}]

        class Cursor:
            def __init__(self, data):
                self.data = data

            def fetchall(self):
                return self.data

        class Connection:
            def __init__(self):
                self.queries = []
                self.calls = 0

            def execute(self, query, _params=()):
                self.queries.append(query)
                self.calls += 1
                return Cursor(rows if self.calls == 1 else [])

        handler = object.__new__(CentralHandler)
        handler.path = "/api/admin/support/reports"
        connection = Connection()
        with patch("backend.server.actor_for", return_value={"id": "admin-id", "role": "Admin"}):
            result, status = handler.dispatch(connection, "GET")

        self.assertEqual(status, 200)
        self.assertEqual(result, [{"id": "report-id", "message": "Booking issue", "replies": []}])
        self.assertIn("LIMIT 100", connection.queries[0])
        self.assertIn("SupportReportReplies", connection.queries[1])

    def test_admin_can_reply_to_guest_and_reply_is_saved(self) -> None:
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
                if query.startswith("SELECT SupportReports.id"):
                    return Cursor({
                        "id": "report-id",
                        "category": "Booking",
                        "message": "Booking problem",
                        "email": "guest@example.test",
                        "display_name": "Guest",
                    })
                return Cursor()

        handler = object.__new__(CentralHandler)
        handler.path = "/api/admin/support/reports/report-id/replies"
        with patch("backend.server.actor_for", return_value={
            "id": "admin-id", "role": "Admin", "display_name": "Admin",
        }), patch.object(
            CentralHandler, "read_body", return_value={"message": "We are looking into it."},
        ), patch("backend.server.mailer.send_hotel_email") as send_email:
            connection = Connection()
            result, status = handler.dispatch(connection, "POST")

        self.assertEqual(status, 201)
        self.assertEqual(result["reportId"], "report-id")
        self.assertTrue(result["emailSent"])
        self.assertEqual(send_email.call_args.args[0], "guest@example.test")
        self.assertEqual(send_email.call_args.kwargs["reply_to"], config.HOTEL_EMAIL)
        insert = next(item for item in connection.statements if item[0].startswith("INSERT INTO SupportReportReplies"))
        self.assertEqual(insert[1][1:4], ("report-id", "admin-id", "We are looking into it."))

    def test_non_admin_cannot_send_report_replies(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.path = "/api/admin/support/reports/report-id/replies"
        with patch("backend.server.actor_for", return_value={"id": "guest-id", "role": "User"}), patch.object(
            CentralHandler, "read_body", return_value={"message": "Not allowed"},
        ):
            with self.assertRaisesRegex(APIError, "Administrator access"):
                handler.dispatch(None, "POST")

    def test_failed_admin_reply_email_is_not_saved(self) -> None:
        class Cursor:
            def fetchone(self):
                return {
                    "id": "report-id",
                    "category": "Booking",
                    "message": "Booking problem",
                    "email": "guest@example.test",
                    "display_name": "Guest",
                }

        class Connection:
            def __init__(self):
                self.inserts = 0

            def execute(self, query, _params=()):
                if query.startswith("INSERT INTO SupportReportReplies"):
                    self.inserts += 1
                return Cursor()

        handler = object.__new__(CentralHandler)
        handler.path = "/api/admin/support/reports/report-id/replies"
        connection = Connection()
        with patch("backend.server.actor_for", return_value={"id": "admin-id", "role": "Admin"}), patch.object(
            CentralHandler, "read_body", return_value={"message": "Reply"},
        ), patch(
            "backend.server.mailer.send_hotel_email",
            side_effect=mailer.MailDeliveryError("SMTP is not configured."),
        ):
            with self.assertRaisesRegex(APIError, "SMTP is not configured"):
                handler.dispatch(connection, "POST")

        self.assertEqual(connection.inserts, 0)

    def test_gmail_smtp_delivery_uses_tls_and_report_reply_address(self) -> None:
        with patch.object(config, "SMTP_USERNAME", "nexorahotel@gmail.com"), patch.object(
            config, "SMTP_PASSWORD", "abcd efgh ijkl mnop",
        ), patch.object(config, "SMTP_SENDER", "nexorahotel@gmail.com"), patch.object(
            config, "SMTP_HOST", "smtp.gmail.com",
        ), patch.object(config, "SMTP_PORT", 587), patch(
            "backend.mailer.smtplib.SMTP",
        ) as smtp_constructor:
            mailer.send_hotel_email(
                "guest@example.test",
                "Re: Report",
                "We received your report.",
                reply_to="nexorahotel@gmail.com",
            )

        smtp_constructor.assert_called_once_with("smtp.gmail.com", 587, timeout=15)
        smtp = smtp_constructor.return_value.__enter__.return_value
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("nexorahotel@gmail.com", "abcdefghijklmnop")
        sent = smtp.send_message.call_args.args[0]
        self.assertEqual(sent["To"], "guest@example.test")
        self.assertEqual(sent["Reply-To"], "nexorahotel@gmail.com")
        self.assertEqual(sent.get_content().strip(), "We received your report.")

    def test_gmail_delivery_requires_server_side_credentials(self) -> None:
        with patch.object(config, "SMTP_USERNAME", ""), patch.object(config, "SMTP_PASSWORD", ""):
            with self.assertRaisesRegex(mailer.MailDeliveryError, "CENTRAL_SMTP_USERNAME"):
                mailer.send_hotel_email("guest@example.test", "Subject", "Body")


class ErrorLogCorrelationTests(unittest.TestCase):
    def test_error_logs_include_safe_request_context(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.request_id = "request-id"
        handler.command = "GET"
        handler.path = "/api/qr/verify/private-receipt"
        handler.response_status = 503
        with patch.object(server.LOGGER, "error") as log_error:
            handler.log_error("Request failed (%s).", "OperationalError")

        extra = log_error.call_args.kwargs["extra"]
        self.assertEqual(extra["request_id"], "request-id")
        self.assertEqual(extra["method"], "GET")
        self.assertEqual(extra["path"], "/api/qr/verify/[redacted]")
        self.assertEqual(extra["status"], 503)
        self.assertEqual(extra["error_type"], "OperationalError")


class CombinedBookingTests(unittest.TestCase):
    def setUp(self):
        self.body = {
            "name": "Guest",
            "email": "guest@example.test",
            "paymentMethod": "cash",
            "hotel": {
                "property": "Hotel",
                "roomType": "Standard",
                "checkIn": "2030-01-01",
                "checkOut": "2030-01-03",
                "guests": 1,
            },
            "parking": {
                "property": "Parking",
                "vehicle": "Car",
                "plate": "TEST-42",
                "parkingDate": "2030-01-01",
                "parkingTime": "14:00",
                "parkingEndTime": "11:00",
                "durationHours": 45,
            },
        }
        self.actor = {"id": "guest-id", "role": "User"}

    def test_success_creates_and_links_both_approved_bookings(self) -> None:
        class Connection:
            def __init__(self):
                self.statements = []

            def execute(self, query, params=()):
                self.statements.append((query, tuple(params)))

        connection = Connection()
        created = [
            {"id": "HTL-ONE", "status": "Approved"},
            {"id": "PKG-TWO", "status": "Approved"},
        ]
        with patch("backend.server.make_booking", side_effect=created) as make_booking, patch(
            "backend.server.issue_qr_ticket",
        ) as issue_qr_ticket:
            result = server.make_combined_booking(connection, self.actor, self.body)

        self.assertEqual(result["hotel"]["id"], "HTL-ONE")
        self.assertEqual(result["parking"]["id"], "PKG-TWO")
        self.assertEqual(result["hotel"]["bookingGroupId"], result["id"])
        self.assertEqual(result["parking"]["bookingGroupId"], result["id"])
        self.assertEqual(result["paymentStatus"], "Pending")
        self.assertEqual(make_booking.call_args_list[0].args[2:], (
            "Hotel", {**self.body["hotel"], "name": "Guest", "email": "guest@example.test",
                      "phone": "", "paymentMethod": "cash"},
        ))
        self.assertEqual(make_booking.call_args_list[1].args[2], "Parking")
        self.assertEqual(
            [statement for statement, _ in connection.statements if statement.startswith("UPDATE ")],
            [
                "UPDATE HotelBookings SET booking_group_id=? WHERE id=?",
                "UPDATE ParkingBookings SET booking_group_id=? WHERE id=?",
            ],
        )
        issue_qr_ticket.assert_called_once_with(connection, "Hotel", "HTL-ONE")

    def test_rejects_staff_accounts_before_writing_group(self) -> None:
        class Connection:
            def execute(self, *_args, **_kwargs):
                raise AssertionError("Unauthorized combined requests must not write data.")

        with self.assertRaisesRegex(APIError, "Only customer or administrator"):
            server.make_combined_booking(
                Connection(), {"id": "staff-id", "role": "Hotel Personnel"}, self.body,
            )

    def test_rejects_invalid_or_out_of_stay_parking_dates(self) -> None:
        class Connection:
            def execute(self, *_args, **_kwargs):
                raise AssertionError("Invalid combined requests must not write data.")

        invalid_body = {**self.body, "parking": {**self.body["parking"], "parkingDate": "2030-01-03"}}
        with self.assertRaisesRegex(APIError, "within the hotel stay"):
            server.make_combined_booking(Connection(), self.actor, invalid_body)

    def test_rejects_a_parking_duration_that_does_not_end_at_checkout(self) -> None:
        class Connection:
            def execute(self, *_args, **_kwargs):
                raise AssertionError("Invalid combined requests must not write data.")

        invalid_body = {
            **self.body,
            "parking": {**self.body["parking"], "durationHours": 48},
        }
        with self.assertRaisesRegex(APIError, "must match the selected hotel check-out"):
            server.make_combined_booking(Connection(), self.actor, invalid_body)

    def test_unavailable_child_rolls_back_the_combined_request(self) -> None:
        class Connection:
            def __init__(self):
                self.committed = False
                self.rolled_back = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, _exc_value, _traceback):
                self.committed = exc_type is None
                self.rolled_back = exc_type is not None

            def execute(self, *_args, **_kwargs):
                return None

        connection = Connection()
        handler = object.__new__(CentralHandler)
        handler.path = "/api/combined/bookings"
        handler.client_address = ("192.0.2.1", 12345)
        handler.headers = {}
        with patch.object(CentralHandler, "enforce_rate_limit"), patch(
            "backend.server.database.connect", return_value=connection,
        ), patch("backend.server.actor_for", return_value=self.actor), patch(
            "backend.server.reservations_enabled", return_value=True,
        ), patch.object(CentralHandler, "read_body", return_value=self.body), patch.object(
            CentralHandler, "respond",
        ) as respond, patch(
            "backend.server.make_booking",
            side_effect=[
                {"id": "HTL-ONE", "status": "Approved"},
                {"id": "PKG-TWO", "status": "Pending"},
            ],
        ):
            handler.handle_api("POST")

        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)
        respond.assert_called_once_with(409, {
            "error": "A hotel room and parking space must both be available for a combined reservation. No bookings were saved.",
        })

    def test_qr_pairing_uses_booking_group_instead_of_overlapping_bookings(self) -> None:
        hotel = {
            "id": "HTL-ONE", "status": "Approved", "guest_name": "Guest",
            "room_number": "101", "floor_number": 1,
            "check_in": "2030-01-01", "check_out": "2030-01-03",
        }
        parking = {
            "id": "PKG-TWO", "status": "Approved", "slot_code": "P-01",
            "plate_number": "TEST-42", "start_at": "2030-01-01T14:00:00+00:00",
            "end_at": "2030-01-03T11:00:00+00:00",
        }

        class Cursor:
            def __init__(self, row=None, rows=None):
                self.row = row
                self.rows = rows or []

            def fetchone(self):
                return self.row

            def fetchall(self):
                return self.rows

        class Connection:
            def __init__(self):
                self.statements = []

            def execute(self, query, params=()):
                self.statements.append((query, tuple(params)))
                if "FROM HotelBookings LEFT JOIN Rooms" in query:
                    return Cursor(row=hotel)
                if "FROM ParkingBookings" in query and "JOIN Vehicles" in query:
                    return Cursor(row=parking)
                if query.startswith("SELECT * FROM QRTickets"):
                    return Cursor(rows=[])
                if query.startswith("SELECT username,email,display_name FROM Users"):
                    return Cursor(row={
                        "username": "guest", "email": "guest@example.test", "display_name": "Guest",
                    })
                return Cursor()

        connection = Connection()
        booking = {
            "id": "HTL-ONE", "user_id": "guest-id", "status": "Approved",
            "booking_group_id": "group-123",
        }
        with patch("backend.server.booking_row", return_value=booking), patch(
            "backend.server.history",
        ):
            server.issue_qr_ticket(connection, "Hotel", "HTL-ONE")

        group_queries = [
            (query, params) for query, params in connection.statements
            if "booking_group_id=?" in query
        ]
        self.assertEqual(len(group_queries), 2)
        self.assertTrue(all(params == ("group-123",) for _, params in group_queries))
        insert = next(
            params for query, params in connection.statements
            if query.startswith("INSERT INTO QRTickets")
        )
        self.assertEqual(insert[2:4], ("HTL-ONE", "PKG-TWO"))


class AutomaticApprovalTests(unittest.TestCase):
    def create_booking(self, booking_type, available_resource, requested_slot_id=None):
        class Result:
            def fetchone(self):
                return None

        class Connection:
            def __init__(self):
                self.statements = []

            def execute(self, query, params=()):
                self.statements.append((query, tuple(params)))
                return Result() if query.startswith("SELECT * FROM Vehicles") else None

        connection = Connection()
        booking = {
            "id": f"{'HTL' if booking_type == 'Hotel' else 'PKG'}-TEST01",
            "user_id": "guest-id", "check_in": "2030-01-01", "check_out": "2030-01-02",
            "room_id": None, "parking_slot_id": None, "start_at": "2030-01-01T10:00:00+00:00",
            "end_at": "2030-01-01T11:00:00+00:00", "status": "Pending",
        }
        body = {
            "name": "Guest", "email": "guest@example.test", "property": "Test Property",
        }
        if booking_type == "Hotel":
            body.update({
                "roomType": "Standard", "checkIn": "2030-01-01",
                "checkOut": "2030-01-02", "guests": 1,
            })
        else:
            body.update({
                "vehicle": "Car", "plate": "TEST-42", "parkingDate": "2030-01-01",
                "parkingTime": "10:00", "durationHours": 1,
            })
            if requested_slot_id:
                body["slotId"] = requested_slot_id

        def resolve_resource(connection, kind, request, requested_id=None):
            if requested_slot_id is not None:
                self.assertEqual(requested_id, requested_slot_id)
            return available_resource(connection, kind, request, requested_id)

        with patch("backend.server.booking_row", return_value=booking), patch(
            "backend.server.available_resource", side_effect=resolve_resource,
        ), patch("backend.server.history") as history, patch(
            "backend.server.notification",
        ) as notification, patch("backend.server.issue_qr_ticket"), patch(
            "backend.server.serialize", side_effect=lambda conn, _kind, row: {
                "id": row["id"],
                "status": "Approved" if any(
                    "SET status='Approved'" in query for query, _ in conn.statements
                ) else "Pending",
            },
        ):
            result = server.make_booking(connection, {"id": "guest-id", "role": "User"}, booking_type, body)
        return connection, result, history, notification

    def assert_resource_is_automatically_reserved(self, booking_type, resource, requested_slot_id=None):
        resource_table = "Rooms" if booking_type == "Hotel" else "ParkingSlots"
        resource_column = "room_id" if booking_type == "Hotel" else "parking_slot_id"
        connection, result, history, notification = self.create_booking(
            booking_type, lambda *_args: resource, requested_slot_id,
        )

        self.assertEqual(result["status"], "Approved")
        self.assertTrue(any(
            query == f"UPDATE {resource_table} SET status='Reserved' WHERE id=?"
            and params == (resource["id"],)
            for query, params in connection.statements
        ))
        self.assertTrue(any(
            f"SET status='Approved',{resource_column}=?" in query and params[0] == resource["id"]
            for query, params in connection.statements
        ))
        self.assertEqual(history.call_args.args[5:7], (None, "Approved"))
        self.assertEqual(notification.call_args.args[3:5], ("booking_approved", "Booking approved"))

    def test_available_room_is_reserved_and_booking_is_approved(self) -> None:
        self.assert_resource_is_automatically_reserved(
            "Hotel", {"id": "room-id", "room_number": "101"},
        )

    def test_available_parking_slot_is_reserved_and_booking_is_approved(self) -> None:
        self.assert_resource_is_automatically_reserved(
            "Parking", {"id": "slot-id", "slot_code": "P-01"}, "slot-id",
        )

    def test_unavailable_selected_parking_slot_rejects_the_booking(self) -> None:
        def no_resource(*_args):
            raise APIError(409, "No parking resource is available for that time.")

        with self.assertRaisesRegex(APIError, "No parking resource is available"):
            self.create_booking("Parking", no_resource, "slot-id")

    def assert_pending_when_inventory_is_unavailable(self, booking_type):
        def no_resource(*_args):
            raise APIError(409, f"No {booking_type.lower()} resource is available for that time.")

        connection, result, history, notification = self.create_booking(booking_type, no_resource)

        self.assertEqual(result["status"], "Pending")
        self.assertFalse(any("SET status='Approved'" in query for query, _ in connection.statements))
        self.assertEqual(history.call_args.args[5:7], (None, "Pending"))
        self.assertEqual(notification.call_args.args[3:5], ("new_request", "New booking request"))

    def test_booking_stays_pending_when_no_room_is_available(self) -> None:
        self.assert_pending_when_inventory_is_unavailable("Hotel")

    def test_booking_stays_pending_when_no_parking_slot_is_available(self) -> None:
        self.assert_pending_when_inventory_is_unavailable("Parking")


class BookingUpdateTests(unittest.TestCase):
    def test_parking_booking_patch_uses_datetime_fields(self) -> None:
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
                if query.startswith("SELECT * FROM Vehicles"):
                    return Cursor({"id": "vehicle-1", "vehicle_type": "Car", "plate_number": "ABC-123"})
                return Cursor()

        booking = {
            "id": "PKG-1",
            "user_id": "user-1",
            "status": "Pending",
            "assigned_personnel_id": None,
            "vehicle_id": "vehicle-1",
            "parking_slot_id": None,
            "property_name": "Main Garage",
            "start_at": "2030-01-01T09:00:00+00:00",
            "end_at": "2030-01-01T10:00:00+00:00",
            "guest_name": "Guest",
            "guest_email": "guest@example.test",
            "guest_phone": "",
            "notes": "",
            "internal_notes": "",
            "created_at": "2030-01-01T00:00:00+00:00",
            "updated_at": "2030-01-01T00:00:00+00:00",
        }
        connection = Connection()
        actor = {"id": "staff-1", "role": "Parking Personnel", "display_name": "Staff"}
        with patch("backend.server.booking_row", return_value=booking), patch(
            "backend.server.serialize", return_value={"id": "PKG-1", "parkingDate": "2030-01-01"}
        ), patch.object(server, "history"), patch.object(server, "notification"):
            result = server.update_booking(connection, actor, "Parking", "PKG-1", {
                "parkingDate": "2030-01-01",
                "parkingTime": "12:00",
                "durationHours": 3,
            })

        self.assertEqual(result["parkingDate"], "2030-01-01")
        self.assertTrue(any(
            query.startswith("UPDATE ParkingBookings SET start_at=?,end_at=?,updated_at=? WHERE id=?")
            for query, _ in connection.statements
        ))

    def test_invalid_hotel_dates_are_rejected_before_update(self) -> None:
        booking = {
            "id": "HTL-1", "user_id": "user-1", "status": "Pending",
            "check_in": "2030-01-01", "check_out": "2030-01-03", "guest_count": 1,
        }

        class Connection:
            def __init__(self):
                self.statements = []

            def execute(self, query, params=()):
                self.statements.append((query, tuple(params)))

        connection = Connection()
        with patch("backend.server.booking_row", return_value=booking):
            with self.assertRaisesRegex(APIError, "valid hotel dates"):
                server.update_booking(
                    connection,
                    {"id": "staff-1", "role": "Hotel Personnel"},
                    "Hotel",
                    "HTL-1",
                    {"checkIn": "not-a-date"},
                )

        self.assertEqual(connection.statements, [
            ("LOCK TABLE HotelBookings, ParkingBookings, Rooms, ParkingSlots IN SHARE ROW EXCLUSIVE MODE", ()),
        ])

    def test_hotel_update_without_editable_fields_is_rejected(self) -> None:
        booking = {
            "id": "HTL-1", "user_id": "user-1", "status": "Pending", "room_id": None,
            "check_in": "2030-01-01", "check_out": "2030-01-03", "guest_count": 1,
        }

        class Connection:
            def execute(self, *_args, **_kwargs):
                return None

        with patch("backend.server.booking_row", return_value=booking):
            with self.assertRaisesRegex(APIError, "No editable fields"):
                server.update_booking(
                    Connection(),
                    {"id": "staff-1", "role": "Hotel Personnel"},
                    "Hotel",
                    "HTL-1",
                    {"unknownField": "ignored"},
                )

    def test_parking_duration_rejects_non_finite_and_out_of_range_values(self) -> None:
        booking = {
            "id": "PKG-1", "user_id": "user-1", "status": "Pending",
            "start_at": "2030-01-01T09:00:00+00:00", "end_at": "2030-01-01T10:00:00+00:00",
        }

        class Connection:
            def execute(self, *_args, **_kwargs):
                return None

        for duration in (0, float("nan"), float("inf"), 169):
            with self.subTest(duration=duration), patch("backend.server.booking_row", return_value=booking):
                with self.assertRaisesRegex(APIError, "between 1 hour and 7 days"):
                    server.update_booking(
                        Connection(),
                        {"id": "staff-1", "role": "Parking Personnel"},
                        "Parking",
                        "PKG-1",
                        {"durationHours": duration},
                    )


class ResourceStatusTests(unittest.TestCase):
    def test_status_reflects_remaining_approved_bookings_and_preserves_maintenance(self) -> None:
        class Cursor:
            def __init__(self, row):
                self.row = row

            def fetchone(self):
                return self.row

        class Connection:
            def __init__(self, resource_status, occupied, approved):
                self.resource_status = resource_status
                self.occupied = occupied
                self.approved = approved
                self.updated_status = None

            def execute(self, query, params=()):
                if query.startswith("SELECT status FROM Rooms"):
                    return Cursor({"status": self.resource_status})
                if "status='Checked In'" in query:
                    return Cursor({"exists": 1} if self.occupied else None)
                if "status='Approved'" in query:
                    return Cursor({"exists": 1} if self.approved else None)
                if query.startswith("UPDATE Rooms"):
                    self.updated_status = params[0]
                    return Cursor(None)
                raise AssertionError(f"Unexpected SQL: {query}")

        cases = (
            ("Available", False, True, "Reserved"),
            ("Available", True, True, "Occupied"),
            ("Available", False, False, "Available"),
            ("Maintenance", False, False, None),
        )
        for resource_status, occupied, approved, expected in cases:
            with self.subTest(resource_status=resource_status, occupied=occupied, approved=approved):
                connection = Connection(resource_status, occupied, approved)
                server.refresh_resource_status(connection, "Hotel", "room-1")
                self.assertEqual(connection.updated_status, expected)


class ReservationAvailabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        class Cursor:
            def __init__(self, rowcount=0, row=None):
                self.rowcount = rowcount
                self.row = row

            def fetchone(self):
                return self.row

        class Connection:
            def __init__(self):
                self.enabled = True

            def execute(self, query, params=()):
                if query.startswith("SELECT value FROM AppSettings"):
                    return Cursor(row={"value": "true" if self.enabled else "false"})
                if query.startswith("UPDATE AppSettings"):
                    self.enabled = params[0] == "true"
                    return Cursor(rowcount=1)
                if query.startswith("INSERT INTO AuditLog"):
                    return Cursor(rowcount=1)
                raise AssertionError(f"Unexpected SQL: {query}")

        self.connection = Connection()

    def dispatch(self, role: str, method: str, path: str, body: dict | None = None):
        handler = object.__new__(CentralHandler)
        handler.path = path
        with patch("backend.server.actor_for", return_value={"id": "actor-id", "role": role}), patch.object(
            CentralHandler, "read_body", return_value=body or {},
        ):
            return handler.dispatch(self.connection, method)

    def test_admin_can_read_and_change_reservation_availability(self) -> None:
        self.assertEqual(self.dispatch("Admin", "GET", "/api/admin/reservations/status"), ({"enabled": True}, 200))
        self.assertEqual(
            self.dispatch("Admin", "PUT", "/api/admin/reservations/status", {"enabled": False}),
            ({"enabled": False}, 200),
        )
        self.assertFalse(self.connection.enabled)

    def test_non_admin_cannot_change_reservation_availability(self) -> None:
        with self.assertRaisesRegex(APIError, "Administrator access"):
            self.dispatch("User", "PUT", "/api/admin/reservations/status", {"enabled": False})
        self.assertTrue(self.connection.enabled)

    def test_authenticated_users_can_read_availability_but_not_change_it(self) -> None:
        self.connection.enabled = False
        self.assertEqual(
            self.dispatch("User", "GET", "/api/admin/reservations/status"),
            ({"enabled": False}, 200),
        )
        with self.assertRaisesRegex(APIError, "Administrator access"):
            self.dispatch("User", "PUT", "/api/admin/reservations/status", {"enabled": True})
        self.assertFalse(self.connection.enabled)

    def test_rejects_non_boolean_availability_value(self) -> None:
        with self.assertRaisesRegex(APIError, "must be a boolean"):
            self.dispatch("Admin", "PUT", "/api/admin/reservations/status", {"enabled": "false"})
        self.assertTrue(self.connection.enabled)

    def test_paused_reservations_reject_non_admin_api_requests(self) -> None:
        self.connection.enabled = False
        with self.assertRaisesRegex(APIError, "temporarily unavailable"):
            self.dispatch("User", "GET", "/api/bookings")
        self.assertEqual(self.dispatch("Admin", "GET", "/api/admin/reservations/status"), ({"enabled": False}, 200))
        with patch("backend.server.list_bookings", return_value=[]):
            self.assertEqual(self.dispatch("Admin", "GET", "/api/bookings"), ([], 200))


class ApiDatabaseConnectionTests(unittest.TestCase):
    def test_database_connection_failures_return_json_service_unavailable(self) -> None:
        failures = (
            OSError("database host unavailable"),
            server.pg8000.dbapi.InterfaceError("database connection refused"),
            server.pg8000.dbapi.OperationalError("database connection lost"),
            RuntimeError("database configuration is invalid"),
        )
        for failure in failures:
            with self.subTest(error=type(failure).__name__):
                handler = object.__new__(CentralHandler)
                handler.path = "/api/bookings"
                handler.client_address = ("192.0.2.1", 12345)
                handler.headers = {}
                with patch.object(rate_limit.RATE_LIMITER, "check", return_value=None), patch(
                    "backend.server.database.connect", side_effect=failure,
                ), patch.object(
                    CentralHandler, "log_error",
                ) as log_error, patch.object(CentralHandler, "respond") as respond:
                    handler.handle_api("GET")

                log_error.assert_called_once()
                respond.assert_called_once_with(503, {
                    "error": "The reservation database is temporarily unavailable. Please try again.",
                })
                self.assertEqual(handler.response_status, 503)


class ExpiredSessionTests(unittest.TestCase):
    def test_expired_jwt_reported_as_forbidden_is_treated_as_unauthenticated(self) -> None:
        error = security.SupabaseAuthError(
            403,
            "invalid JWT: unable to parse or verify signature, token has invalid claims: token is expired",
        )
        with patch("backend.security._auth_request", side_effect=error):
            self.assertIsNone(security.find_session_user(object(), "expired-token"))

    def test_other_auth_forbidden_errors_are_not_treated_as_expired_sessions(self) -> None:
        error = security.SupabaseAuthError(403, "User account is disabled.")
        with patch("backend.security._auth_request", side_effect=error):
            with self.assertRaisesRegex(security.SupabaseAuthError, "disabled"):
                security.find_session_user(object(), "token")


class AdminAccountCreationTests(unittest.TestCase):
    def test_admin_creation_endpoint_rejects_non_admin(self) -> None:
        handler = object.__new__(CentralHandler)
        handler.path = "/api/admin/users"
        with patch("backend.server.actor_for", return_value={"role": "User"}), patch.object(
            CentralHandler, "read_body", return_value={},
        ), patch("backend.server.reservations_enabled", return_value=True), patch(
            "backend.server.security.register",
        ) as register:
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


class PrivateStaticFileTests(unittest.TestCase):
    def test_sensitive_files_and_source_directories_are_not_public(self) -> None:
        private_paths = (
            "/CENTRAL%20CHANNEL/.env",
            "/CENTRAL%20CHANNEL/data/central-channel.sqlite3",
            "/CENTRAL%20CHANNEL/backend/server.py",
            "/.git/config",
        )
        for path in private_paths:
            with self.subTest(path=path):
                self.assertTrue(server.is_private_static_path(path))

    def test_public_site_assets_remain_available(self) -> None:
        self.assertFalse(server.is_private_static_path("/LOGIN%20PANEL/index.html"))


@unittest.skipUnless(
    config.SUPABASE_DATABASE_URL and config.SUPABASE_URL and config.SUPABASE_PUBLISHABLE_KEY and config.SUPABASE_SECRET_KEY,
    "Set Supabase database, URL, publishable, and secret keys to run API integration tests.",
)
class CentralApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rate_limit_patch = patch.object(rate_limit.RATE_LIMITER, "check", return_value=None)
        cls.rate_limit_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.rate_limit_patch.stop()

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
        self.assertEqual(booking["paymentStatus"], "Pending")
        self.assertEqual(booking["status"], "Approved")
        room_id = booking["roomId"]
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
        self.assertEqual([item["action"] for item in history], ["check-out", "check-in", "created"])
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
        self.assertEqual(visible[hotel_booking["id"]]["status"], "Approved")
        self.assertEqual(visible[hotel_booking["id"]]["type"], "Hotel")
        self.assertEqual(visible[parking_booking["id"]]["status"], "Approved")
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
        self.assertEqual(len(passes), 1)
        hotel_pass = next(
            qr_pass for qr_pass in passes if qr_pass["hotelBookingId"] == hotel_booking["id"]
        )
        self.assertEqual(hotel_pass["status"], "Active")
        self.assertTrue(hotel_pass["hotel"]["room"])
        self.assertEqual(hotel_pass["parkingBookingId"], parking_booking["id"])
        self.assertTrue(hotel_pass["parking"]["slot"])
        self.assertTrue(hotel_pass["qrImage"].startswith("data:image/svg+xml;base64,"))
        verified, status = self.request(
            "GET", f"/api/qr/verify/{hotel_pass['receiptCode']}", token=admin_token,
        )
        self.assertEqual(status, 200)
        self.assertTrue(verified["valid"])

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

    def test_fresh_database_bootstraps_first_confirmed_signup_as_admin(self) -> None:
        with database.connect() as connection:
            connection.execute("DELETE FROM Sessions")
            connection.execute("DELETE FROM Personnel")
            connection.execute("DELETE FROM Users")
        first, status = self.request("POST", "/api/auth/register", {
            "username": "owner", "email": "owner@example.test", "password": "a-long-enough-password",
        })
        self.assertEqual(status, 201)
        self.assertEqual(first["user"]["role"], "User")
        self.auth_user_ids.append(first["user"]["id"])
        with patch(
            "backend.server.security.verify_signup_email",
            return_value={"access_token": "verified-owner-token", "user": {"id": first["user"]["id"]}},
        ):
            first, status = self.request("POST", "/api/auth/verify-email", {
                "email": "owner@example.test", "token": "123456",
            })
        self.assertEqual(status, 200)
        self.assertEqual(first["user"]["role"], "Admin")

        second, status = self.request("POST", "/api/auth/register", {
            "username": "member", "email": "member@example.test", "password": "another-long-password",
        })
        self.assertEqual(status, 201)
        self.assertEqual(second["user"]["role"], "User")
        self.auth_user_ids.append(second["user"]["id"])
        with patch(
            "backend.server.security.verify_signup_email",
            return_value={"access_token": "verified-member-token", "user": {"id": second["user"]["id"]}},
        ):
            second, status = self.request("POST", "/api/auth/verify-email", {
                "email": "member@example.test", "token": "123456",
            })
        self.assertEqual(status, 200)
        self.assertEqual(second["user"]["role"], "User")

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

    def test_admin_audit_log_is_private_and_records_reservation_controls(self) -> None:
        _, status = self.request(
            "GET", "/api/admin/audit-log", token=self.accounts["guest"]["token"],
        )
        self.assertEqual(status, 403)

        result, status = self.request(
            "PUT",
            "/api/admin/reservations/status",
            {"enabled": False},
            self.accounts["admin"]["token"],
        )
        self.assertEqual(status, 200)
        self.assertFalse(result["enabled"])

        entries, status = self.request(
            "GET", "/api/admin/audit-log", token=self.accounts["admin"]["token"],
        )
        self.assertEqual(status, 200)
        self.assertTrue(any(
            entry["action"] == "reservations.availability_changed"
            and json.loads(entry["details_json"]) == {"enabled": False}
            for entry in entries
        ))


if __name__ == "__main__":
    unittest.main()