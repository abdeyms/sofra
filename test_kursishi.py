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
		self.temp_directory = TemporaryDirectory()
		kursishi.DATABASE_PATH = Path(self.temp_directory.name) / "test.db"
		kursishi.initialize_database()
		self.connection = kursishi.get_connection()
		self.booking_date = date.today() + timedelta(days=1)

	def tearDown(self):
		self.connection.close()
		kursishi.DATABASE_PATH = self.original_database_path
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
				kursishi.require_admin(SimpleNamespace(headers={}), call_next)
			)
			self.assertEqual(unauthorized.status_code, 401)
			call_next.assert_not_awaited()

			credentials = "YWRtaW46c2VjcmV0"
			authorized = asyncio.run(
				kursishi.require_admin(
					SimpleNamespace(headers={"authorization": f"Basic {credentials}"}), call_next
				)
			)

		self.assertIn("Basic", unauthorized.headers["www-authenticate"])
		self.assertEqual(authorized.status_code, 204)
		call_next.assert_awaited_once()

	def test_production_requires_credentials(self):
		with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True):
			with self.assertRaisesRegex(RuntimeError, "APP_USERNAME and APP_PASSWORD"):
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