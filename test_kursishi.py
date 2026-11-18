from contextlib import closing
from datetime import date, time, timedelta, timezone
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest

from fastapi import HTTPException, Response
from pydantic import ValidationError

import kursishi


class BookingBackendTests(unittest.TestCase):
	def setUp(self):
		self.original_database_path = kursishi.DATABASE_PATH
		self.original_admin_sessions = kursishi.ADMIN_SESSIONS.copy()
		self.temp_directory = TemporaryDirectory()
		kursishi.DATABASE_PATH = Path(self.temp_directory.name) / "test.db"
		kursishi.initialize_database()
		self.connection = kursishi.get_connection()
		self.booking_date = date.today() + timedelta(days=1)

	def tearDown(self):
		self.connection.close()
		kursishi.DATABASE_PATH = self.original_database_path
		kursishi.ADMIN_SESSIONS.clear()
		kursishi.ADMIN_SESSIONS.update(self.original_admin_sessions)
		self.temp_directory.cleanup()

	def create_booking(self, table_id=1, start_time=time(10), duration=90, party_size=2):
		return kursishi.create_booking(
			kursishi.BookingCreate(
				table_id=table_id,
				customer_name="Ali Valiyev",
				phone="+998 90 123 45 67",
				party_size=party_size,
				booking_date=self.booking_date,
				start_time=start_time,
				duration_minutes=duration,
			),
			self.connection,
		)

	def assert_http_error(self, expected_status, action):
		with self.assertRaises(HTTPException) as raised:
			action()
		self.assertEqual(raised.exception.status_code, expected_status)

	def test_protected_routes_require_valid_basic_auth(self):
		with patch.dict(os.environ, {"APP_USERNAME": "admin", "APP_PASSWORD": "secret"}, clear=True):
			call_next = AsyncMock(return_value=Response(status_code=204))
			unauthorized = asyncio.run(
				kursishi.require_admin(
					SimpleNamespace(headers={}, url=SimpleNamespace(path="/")), call_next
				)
			)
			self.assertEqual(unauthorized.status_code, 401)
			call_next.assert_not_awaited()

			credentials = "YWRtaW46c2VjcmV0"
			authorized = asyncio.run(
				kursishi.require_admin(
					SimpleNamespace(
						headers={"authorization": f"Basic {credentials}"},
						url=SimpleNamespace(path="/"),
					),
					call_next,
				)
			)

		self.assertIn("Basic", unauthorized.headers["www-authenticate"])
		self.assertEqual(authorized.status_code, 204)
		call_next.assert_awaited_once()

	def test_admin_api_requires_an_active_session(self):
		call_next = AsyncMock(return_value=Response(status_code=204))
		request = SimpleNamespace(
			url=SimpleNamespace(path="/admin/api/tables"),
			cookies={},
			headers={},
			method="GET",
		)
		unauthorized = asyncio.run(kursishi.require_admin(request, call_next))
		self.assertEqual(unauthorized.status_code, 401)
		call_next.assert_not_awaited()

		token = "valid-test-session"
		kursishi.ADMIN_SESSIONS[token] = kursishi.datetime.now() + timedelta(hours=1)
		request.cookies[kursishi.ADMIN_SESSION_COOKIE] = token
		authorized = asyncio.run(kursishi.require_admin(request, call_next))
		self.assertEqual(authorized.status_code, 204)
		self.assertEqual(authorized.headers["cache-control"], "no-store")
		call_next.assert_awaited_once()

	def test_public_booking_stays_open_but_booking_records_are_protected(self):
		with patch.dict(os.environ, {}, clear=True):
			for path, method in (("/bookings", "GET"), ("/bookings/7", "GET"), ("/bookings/7", "DELETE")):
				with self.subTest(path=path, method=method):
					call_next = AsyncMock(return_value=Response(status_code=204))
					request = SimpleNamespace(
						url=SimpleNamespace(path=path),
						cookies={},
						headers={},
						method=method,
					)
					response = asyncio.run(kursishi.require_admin(request, call_next))
					self.assertEqual(response.status_code, 401)
					call_next.assert_not_awaited()

			for path, method in (("/tables", "GET"), ("/availability", "GET"), ("/bookings", "POST")):
				with self.subTest(path=path, method=method):
					call_next = AsyncMock(return_value=Response(status_code=204))
					request = SimpleNamespace(
						url=SimpleNamespace(path=path),
						cookies={},
						headers={},
						method=method,
					)
					response = asyncio.run(kursishi.require_admin(request, call_next))
					self.assertEqual(response.status_code, 204)
					call_next.assert_awaited_once()

	def test_admin_login_requires_configured_correct_code_and_sets_secure_cookie(self):
		request = SimpleNamespace(
			url=SimpleNamespace(scheme="https"),
			cookies={},
		)
		response = Response()
		with patch.dict(os.environ, {"ADMIN_ACCESS_CODE": "private-code"}, clear=True):
			self.assertEqual(
				kursishi.admin_login(
					kursishi.AdminLogin(access_code="private-code"), request, response
				),
				{"authenticated": True},
			)
			with self.assertRaises(HTTPException) as raised:
				kursishi.admin_login(
					kursishi.AdminLogin(access_code="wrong-code"), request, Response()
				)
		self.assertEqual(raised.exception.status_code, 401)
		self.assertIn("httponly", response.headers["set-cookie"].lower())
		self.assertIn("secure", response.headers["set-cookie"].lower())
		self.assertIn("samesite=strict", response.headers["set-cookie"].lower())

	def test_admin_login_fails_closed_when_access_code_is_missing(self):
		with patch.dict(os.environ, {}, clear=True), patch("kursishi.load_local_admin_code"):
			with self.assertRaises(HTTPException) as raised:
				kursishi.admin_login(
					kursishi.AdminLogin(access_code="anything"),
					SimpleNamespace(url=SimpleNamespace(scheme="http"), cookies={}),
					Response(),
				)
		self.assertEqual(raised.exception.status_code, 503)

	def test_production_requires_credentials(self):
		with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True):
			with self.assertRaisesRegex(
				RuntimeError, "APP_USERNAME, APP_PASSWORD, and ADMIN_ACCESS_CODE"
			):
				asyncio.run(kursishi.lifespan(kursishi.app).__aenter__())

	def test_overlapping_bookings_are_rejected_and_adjacent_ones_are_allowed(self):
		first = self.create_booking(duration=90)
		self.assert_http_error(409, lambda: self.create_booking(start_time=time(10, 30)))
		adjacent = self.create_booking(start_time=time(11, 30))
		self.assertNotEqual(first["id"], adjacent["id"])

	def test_booking_is_persisted_for_a_new_connection(self):
		booking = self.create_booking()
		with closing(kursishi.get_connection()) as connection:
			stored = kursishi.get_booking(booking["id"], connection)
		self.assertEqual(stored["customer_name"], "Ali Valiyev")

	def test_stylesheet_route_points_to_the_external_css_file(self):
		route = next(route for route in kursishi.app.routes if getattr(route, "path", None) == "/styles.css")
		response = route.endpoint()
		self.assertEqual(response.path, Path(kursishi.__file__).with_name("styles.css"))
		self.assertEqual(response.media_type, "text/css")

	def test_admin_page_and_assets_have_routes(self):
		expected = {
			"/admin": ("admin.html", "text/html"),
			"/admin.css": ("admin.css", "text/css"),
			"/admin.js": ("admin.js", "text/javascript"),
		}
		for route_path, (filename, media_type) in expected.items():
			with self.subTest(route=route_path):
				route = next(
					route for route in kursishi.app.routes
					if getattr(route, "path", None) == route_path
				)
				response = route.endpoint()
				self.assertEqual(response.path, Path(kursishi.__file__).with_name(filename))
				self.assertEqual(response.media_type, media_type)

	def test_room_script_route_points_to_the_external_javascript_file(self):
		route = next(route for route in kursishi.app.routes if getattr(route, "path", None) == "/room.js")
		response = route.endpoint()
		self.assertEqual(response.path, Path(kursishi.__file__).with_name("room.js"))
		self.assertEqual(response.media_type, "text/javascript")

	def test_availability_rejects_past_and_overnight_intervals(self):
		self.assert_http_error(
			422,
			lambda: kursishi.booking_interval(date.today() - timedelta(days=1), time(10), 90),
		)
		self.assert_http_error(
			422,
			lambda: kursishi.booking_interval(self.booking_date, time(23, 30), 90),
		)
		self.assert_http_error(
			422,
			lambda: kursishi.find_available_tables(
				self.connection, self.booking_date, time(10, tzinfo=timezone.utc), 90, 2
			),
		)

	def test_partial_update_preserves_duration_and_rolls_back_invalid_edits(self):
		first = self.create_booking(duration=120)
		self.create_booking(start_time=time(12), duration=60)
		updated = kursishi.update_booking(
			first["id"], kursishi.BookingUpdate(customer_name="Ali Karimov"), self.connection
		)
		self.assertEqual(updated["customer_name"], "Ali Karimov")
		self.assertEqual(updated["end_time"], "12:00:00")
		self.assert_http_error(
			409,
			lambda: kursishi.update_booking(
				first["id"], kursishi.BookingUpdate(start_time=time(11, 30)), self.connection
			),
		)
		updated = kursishi.update_booking(
			first["id"], kursishi.BookingUpdate(customer_name="Ali Updated"), self.connection
		)
		self.assertEqual(updated["customer_name"], "Ali Updated")
		self.assert_http_error(
			422,
			lambda: kursishi.update_booking(
				first["id"], kursishi.BookingUpdate(party_size=3), self.connection
			),
		)

	def test_cancellation_releases_table_and_cannot_be_repeated(self):
		booking = self.create_booking()
		kursishi.cancel_booking(booking["id"], self.connection)
		availability = kursishi.find_available_tables(
			self.connection, self.booking_date, time(10), 90, 2
		)
		self.assertIn(1, [table["id"] for table in availability])
		self.assert_http_error(
			409, lambda: kursishi.cancel_booking(booking["id"], self.connection)
		)

	def test_table_can_be_updated_or_deleted_only_when_safe(self):
		table = kursishi.create_table(kursishi.TableCreate(name="T7", seats=4), self.connection)
		updated = kursishi.update_table(
			table["id"], kursishi.TableUpdate(name="VIP", seats=6), self.connection
		)
		self.assertEqual((updated["name"], updated["seats"]), ("VIP", 6))
		response = kursishi.delete_table(table["id"], self.connection)
		self.assertIsInstance(response, Response)
		self.assertEqual(response.status_code, 204)
		self.create_booking()
		self.assert_http_error(409, lambda: kursishi.delete_table(1, self.connection))
		self.assert_http_error(
			409,
			lambda: kursishi.update_table(1, kursishi.TableUpdate(seats=1), self.connection),
		)

	def test_invalid_names_and_phone_numbers_are_rejected(self):
		with self.assertRaises(ValidationError):
			kursishi.TableCreate(name="   ", seats=2)
		with self.assertRaises(ValidationError):
			kursishi.BookingCreate(
				table_id=1,
				customer_name="   ",
				phone="1234567",
				party_size=2,
				booking_date=self.booking_date,
				start_time=time(10),
			)
		with self.assertRaises(ValidationError):
			kursishi.BookingCreate(
				table_id=1,
				customer_name="Ali",
				phone="abcdefg",
				party_size=2,
				booking_date=self.booking_date,
				start_time=time(10),
			)


if __name__ == "__main__":
	unittest.main()