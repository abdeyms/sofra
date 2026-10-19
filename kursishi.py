from base64 import b64decode
from contextlib import asynccontextmanager, closing
from datetime import date, datetime, time, timedelta
import os
from pathlib import Path
import re
from secrets import compare_digest
import sqlite3
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


DATABASE_PATH = Path(os.getenv("BOOKING_DB_PATH", Path(__file__).with_name("bookings.db")))


def get_connection():
	connection = sqlite3.connect(DATABASE_PATH, timeout=10, check_same_thread=False)
	connection.row_factory = sqlite3.Row
	connection.execute("PRAGMA foreign_keys = ON")
	return connection


def initialize_database():
	DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
	with closing(get_connection()) as connection:
		connection.executescript(
			"""
			CREATE TABLE IF NOT EXISTS dining_tables (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL UNIQUE,
				seats INTEGER NOT NULL CHECK (seats > 0)
			);
			CREATE TABLE IF NOT EXISTS bookings (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				table_id INTEGER NOT NULL REFERENCES dining_tables(id),
				customer_name TEXT NOT NULL,
				phone TEXT NOT NULL,
				party_size INTEGER NOT NULL CHECK (party_size > 0),
				booking_date TEXT NOT NULL,
				start_time TEXT NOT NULL,
				end_time TEXT NOT NULL,
				status TEXT NOT NULL DEFAULT 'confirmed'
					CHECK (status IN ('confirmed', 'cancelled')),
				created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
			);
			"""
		)
		table_count = connection.execute(
			"SELECT COUNT(*) FROM dining_tables"
		).fetchone()[0]
		if table_count == 0:
			connection.executemany(
				"INSERT INTO dining_tables (name, seats) VALUES (?, ?)",
				[("T1", 2), ("T2", 2), ("T3", 4), ("T4", 4), ("T5", 6), ("T6", 8)],
			)
		connection.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
	if os.getenv("APP_ENV") == "production" and not (
		os.getenv("APP_USERNAME") and os.getenv("APP_PASSWORD")
	):
		raise RuntimeError("APP_USERNAME and APP_PASSWORD are required in production")
	initialize_database()
	yield


app = FastAPI(
	title="Restoran stol band qilish API",
	description="Stollar mavjudligini tekshirish va bronlarni boshqarish API si.",
	version="1.0.0",
	lifespan=lifespan,
)
app.add_middleware(
	CORSMiddleware,
	allow_origins=[],
	allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
	allow_methods=["*"],
	allow_headers=["*"],
)


@app.middleware("http")
async def require_admin(request: Request, call_next):
	username = os.getenv("APP_USERNAME")
	password = os.getenv("APP_PASSWORD")
	if username is None and password is None:
		return await call_next(request)
	if not username or not password:
		return PlainTextResponse("Application credentials are not configured", status_code=503)

	try:
		scheme, encoded_credentials = request.headers.get("authorization", "").split(" ", 1)
		if scheme.lower() != "basic":
			raise ValueError
		provided_username, provided_password = b64decode(encoded_credentials, validate=True).decode("utf-8").split(":", 1)
	except (ValueError, UnicodeDecodeError):
		provided_username = provided_password = ""

	if not (compare_digest(provided_username, username) and compare_digest(provided_password, password)):
		return PlainTextResponse(
			"Authentication required",
			status_code=401,
			headers={"WWW-Authenticate": 'Basic realm="Sofra", charset="UTF-8"'},
		)
	return await call_next(request)


def database():
	connection = get_connection()
	try:
		yield connection
	finally:
		connection.close()


Database = Annotated[sqlite3.Connection, Depends(database)]


class TableCreate(BaseModel):
	name: str = Field(min_length=1, max_length=30)
	seats: int = Field(gt=0, le=30)

	@field_validator("name")
	@classmethod
	def clean_name(cls, value: str) -> str:
		value = value.strip()
		if not value:
			raise ValueError("Stol nomi bo‘sh bo‘lmasligi kerak")
		return value


class TableUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	name: str | None = Field(default=None, min_length=1, max_length=30)
	seats: int | None = Field(default=None, gt=0, le=30)

	@field_validator("name")
	@classmethod
	def clean_name(cls, value: str | None) -> str | None:
		if value is None:
			return value
		value = value.strip()
		if not value:
			raise ValueError("Stol nomi bo‘sh bo‘lmasligi kerak")
		return value


class BookingCreate(BaseModel):
	table_id: int = Field(gt=0)
	customer_name: str = Field(min_length=2, max_length=100)
	phone: str = Field(min_length=7, max_length=25)
	party_size: int = Field(gt=0, le=30)
	booking_date: date
	start_time: time
	duration_minutes: int = Field(default=90, ge=30, le=360)

	@field_validator("customer_name")
	@classmethod
	def clean_customer_name(cls, value: str) -> str:
		value = value.strip()
		if not value:
			raise ValueError("Mehmon ismi bo‘sh bo‘lmasligi kerak")
		return value

	@field_validator("phone")
	@classmethod
	def validate_phone(cls, value: str) -> str:
		value = value.strip()
		if not re.fullmatch(r"[0-9+()\-\s]+", value) or len(re.sub(r"\D", "", value)) < 7:
			raise ValueError("Telefon raqami kamida 7 ta raqamdan iborat bo‘lishi kerak")
		return value

	@field_validator("start_time")
	@classmethod
	def require_local_time(cls, value: time) -> time:
		if value.tzinfo is not None and value.utcoffset() is not None:
			raise ValueError("Vaqt mahalliy formatda bo‘lishi kerak")
		return value


class BookingUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	table_id: int | None = Field(default=None, gt=0)
	customer_name: str | None = Field(default=None, min_length=2, max_length=100)
	phone: str | None = Field(default=None, min_length=7, max_length=25)
	party_size: int | None = Field(default=None, gt=0, le=30)
	booking_date: date | None = None
	start_time: time | None = None
	duration_minutes: int | None = Field(default=None, ge=30, le=360)

	@field_validator("customer_name")
	@classmethod
	def clean_customer_name(cls, value: str | None) -> str | None:
		if value is None:
			return value
		value = value.strip()
		if not value:
			raise ValueError("Mehmon ismi bo‘sh bo‘lmasligi kerak")
		return value

	@field_validator("phone")
	@classmethod
	def validate_phone(cls, value: str | None) -> str | None:
		if value is None:
			return value
		value = value.strip()
		if not re.fullmatch(r"[0-9+()\-\s]+", value) or len(re.sub(r"\D", "", value)) < 7:
			raise ValueError("Telefon raqami kamida 7 ta raqamdan iborat bo‘lishi kerak")
		return value

	@field_validator("start_time")
	@classmethod
	def require_local_time(cls, value: time | None) -> time | None:
		if value is not None and value.tzinfo is not None and value.utcoffset() is not None:
			raise ValueError("Vaqt mahalliy formatda bo‘lishi kerak")
		return value


def as_dict(row: sqlite3.Row) -> dict:
	return dict(row)


def booking_interval(booking_date: date, start_time: time, duration_minutes: int) -> tuple[datetime, datetime]:
	if start_time.tzinfo is not None and start_time.utcoffset() is not None:
		raise HTTPException(status_code=422, detail="Vaqt mahalliy formatda bo‘lishi kerak")
	start = datetime.combine(booking_date, start_time)
	end = start + timedelta(minutes=duration_minutes)
	if start <= datetime.now():
		raise HTTPException(status_code=422, detail="Bron vaqti kelajakda bo‘lishi kerak")
	if end.date() != booking_date:
		raise HTTPException(status_code=422, detail="Bron vaqti keyingi kunga o‘tmasligi kerak")
	return start, end


def find_available_tables(
	connection: sqlite3.Connection,
	booking_date: date,
	start_time: time,
	duration_minutes: int,
	party_size: int,
) -> list[dict]:
	_, end = booking_interval(booking_date, start_time, duration_minutes)

	rows = connection.execute(
		"""
		SELECT dining_tables.id, dining_tables.name, dining_tables.seats
		FROM dining_tables
		WHERE dining_tables.seats >= ?
		  AND NOT EXISTS (
			  SELECT 1 FROM bookings
			  WHERE bookings.table_id = dining_tables.id
				AND bookings.status = 'confirmed'
				AND bookings.booking_date = ?
				AND bookings.start_time < ?
				AND bookings.end_time > ?
		  )
		ORDER BY dining_tables.seats, dining_tables.id
		""",
		(party_size, booking_date.isoformat(), end.time().isoformat(), start_time.isoformat()),
	).fetchall()
	return [as_dict(row) for row in rows]


@app.get("/")
def home():
	return FileResponse(Path(__file__).with_name("index.html"))


@app.get("/styles.css", include_in_schema=False)
def stylesheet():
	return FileResponse(Path(__file__).with_name("styles.css"), media_type="text/css")


@app.get("/room.js", include_in_schema=False)
def room_script():
	return FileResponse(Path(__file__).with_name("room.js"), media_type="text/javascript")


@app.get("/tables")
def list_tables(connection: Database):
	rows = connection.execute(
		"SELECT id, name, seats FROM dining_tables ORDER BY id"
	).fetchall()
	return [as_dict(row) for row in rows]


@app.post("/tables", status_code=status.HTTP_201_CREATED)
def create_table(table: TableCreate, connection: Database):
	try:
		cursor = connection.execute(
			"INSERT INTO dining_tables (name, seats) VALUES (?, ?)",
			(table.name.strip(), table.seats),
		)
		connection.commit()
	except sqlite3.IntegrityError as error:
		raise HTTPException(status_code=409, detail="Bu nomdagi stol mavjud") from error
	return {"id": cursor.lastrowid, "name": table.name.strip(), "seats": table.seats}


@app.patch("/tables/{table_id}")
def update_table(table_id: int, table: TableUpdate, connection: Database):
	changes = table.model_dump(exclude_unset=True)
	if not changes or any(value is None for value in changes.values()):
		raise HTTPException(status_code=422, detail="Kamida bitta qiymat yuboring; null qiymat mumkin emas")
	connection.execute("BEGIN IMMEDIATE")
	existing = connection.execute(
		"SELECT id, seats FROM dining_tables WHERE id = ?", (table_id,)
	).fetchone()
	if existing is None:
		connection.rollback()
		raise HTTPException(status_code=404, detail="Stol topilmadi")
	new_seats = changes.get("seats", existing["seats"])
	incompatible_booking = connection.execute(
		"""
		SELECT 1 FROM bookings
		WHERE table_id = ? AND status = 'confirmed'
		  AND booking_date >= date('now', 'localtime') AND party_size > ?
		LIMIT 1
		""",
		(table_id, new_seats),
	).fetchone()
	if incompatible_booking:
		connection.rollback()
		raise HTTPException(status_code=409, detail="Kelajakdagi bronlar sig‘imidan kichik stolga o‘zgartirib bo‘lmaydi")
	assignments = ", ".join(f"{column} = ?" for column in changes)
	try:
		connection.execute(
			f"UPDATE dining_tables SET {assignments} WHERE id = ?",
			[*changes.values(), table_id],
		)
		connection.commit()
	except sqlite3.IntegrityError as error:
		connection.rollback()
		raise HTTPException(status_code=409, detail="Bu nomdagi stol mavjud") from error
	row = connection.execute(
		"SELECT id, name, seats FROM dining_tables WHERE id = ?", (table_id,)
	).fetchone()
	return as_dict(row)


@app.delete("/tables/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_table(table_id: int, connection: Database):
	connection.execute("BEGIN IMMEDIATE")
	exists = connection.execute(
		"SELECT 1 FROM dining_tables WHERE id = ?", (table_id,)
	).fetchone()
	if exists is None:
		connection.rollback()
		raise HTTPException(status_code=404, detail="Stol topilmadi")
	has_bookings = connection.execute(
		"SELECT 1 FROM bookings WHERE table_id = ? LIMIT 1", (table_id,)
	).fetchone()
	if has_bookings:
		connection.rollback()
		raise HTTPException(status_code=409, detail="Bronlar tarixiga ega stolni o‘chirib bo‘lmaydi")
	connection.execute("DELETE FROM dining_tables WHERE id = ?", (table_id,))
	connection.commit()
	return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/availability")
def check_availability(
	booking_date: date,
	start_time: time,
	party_size: Annotated[int, Query(gt=0, le=30)],
	duration_minutes: Annotated[int, Query(ge=30, le=360)] = 90,
	connection: Database = None,
):
	tables = find_available_tables(
		connection, booking_date, start_time, duration_minutes, party_size
	)
	return {"available": bool(tables), "tables": tables}


@app.post("/bookings", status_code=status.HTTP_201_CREATED)
def create_booking(booking: BookingCreate, connection: Database):
	_, end = booking_interval(booking.booking_date, booking.start_time, booking.duration_minutes)
	connection.execute("BEGIN IMMEDIATE")
	table = connection.execute(
		"SELECT id, seats FROM dining_tables WHERE id = ?", (booking.table_id,)
	).fetchone()
	if table is None:
		connection.rollback()
		raise HTTPException(status_code=404, detail="Stol topilmadi")
	if booking.party_size > table["seats"]:
		connection.rollback()
		raise HTTPException(status_code=422, detail="Mehmonlar soni stol sig‘imidan katta")

	conflict = connection.execute(
		"""
		SELECT 1 FROM bookings
		WHERE table_id = ? AND booking_date = ? AND status = 'confirmed'
		  AND start_time < ? AND end_time > ?
		LIMIT 1
		""",
		(
			booking.table_id,
			booking.booking_date.isoformat(),
			end.time().isoformat(),
			booking.start_time.isoformat(),
		),
	).fetchone()
	if conflict:
		connection.rollback()
		raise HTTPException(status_code=409, detail="Bu vaqtda stol band qilingan")

	cursor = connection.execute(
		"""
		INSERT INTO bookings
			(table_id, customer_name, phone, party_size, booking_date, start_time, end_time)
		VALUES (?, ?, ?, ?, ?, ?, ?)
		""",
		(
			booking.table_id,
			booking.customer_name.strip(),
			booking.phone.strip(),
			booking.party_size,
			booking.booking_date.isoformat(),
			booking.start_time.isoformat(),
			end.time().isoformat(),
		),
	)
	connection.commit()
	return get_booking(cursor.lastrowid, connection)


@app.get("/bookings")
def list_bookings(
	connection: Database,
	booking_date: date | None = None,
	booking_status: Annotated[str | None, Query(alias="status", pattern="^(confirmed|cancelled)$")] = None,
):
	query = """
		SELECT bookings.*, dining_tables.name AS table_name
		FROM bookings JOIN dining_tables ON dining_tables.id = bookings.table_id
		WHERE 1 = 1
	"""
	parameters: list[str] = []
	if booking_date:
		query += " AND booking_date = ?"
		parameters.append(booking_date.isoformat())
	if booking_status:
		query += " AND bookings.status = ?"
		parameters.append(booking_status)
	query += " ORDER BY booking_date, start_time"
	rows = connection.execute(query, parameters).fetchall()
	return [as_dict(row) for row in rows]


def get_booking(booking_id: int, connection: sqlite3.Connection):
	row = connection.execute(
		"""
		SELECT bookings.*, dining_tables.name AS table_name
		FROM bookings JOIN dining_tables ON dining_tables.id = bookings.table_id
		WHERE bookings.id = ?
		""",
		(booking_id,),
	).fetchone()
	if row is None:
		raise HTTPException(status_code=404, detail="Bron topilmadi")
	return as_dict(row)


@app.get("/bookings/{booking_id}")
def read_booking(booking_id: int, connection: Database):
	return get_booking(booking_id, connection)


@app.patch("/bookings/{booking_id}")
def update_booking(booking_id: int, changes: BookingUpdate, connection: Database):
	update_values = changes.model_dump(exclude_unset=True)
	if not update_values or any(value is None for value in update_values.values()):
		raise HTTPException(status_code=422, detail="Kamida bitta qiymat yuboring; null qiymat mumkin emas")
	connection.execute("BEGIN IMMEDIATE")
	current = connection.execute(
		"SELECT * FROM bookings WHERE id = ?", (booking_id,)
	).fetchone()
	if current is None:
		connection.rollback()
		raise HTTPException(status_code=404, detail="Bron topilmadi")
	if current["status"] != "confirmed":
		connection.rollback()
		raise HTTPException(status_code=409, detail="Bekor qilingan bronni o‘zgartirib bo‘lmaydi")
	booking_data = {
		"table_id": current["table_id"],
		"customer_name": current["customer_name"],
		"phone": current["phone"],
		"party_size": current["party_size"],
		"booking_date": current["booking_date"],
		"start_time": current["start_time"],
		"duration_minutes": int(
			(
				datetime.fromisoformat(f"{current['booking_date']}T{current['end_time']}")
				- datetime.fromisoformat(f"{current['booking_date']}T{current['start_time']}")
			).total_seconds()
			// 60
		),
	}
	booking_data.update(update_values)
	try:
		booking = BookingCreate.model_validate(booking_data)
	except ValidationError as error:
		connection.rollback()
		raise HTTPException(status_code=422, detail=error.errors()) from error
	try:
		_, end = booking_interval(booking.booking_date, booking.start_time, booking.duration_minutes)
	except HTTPException:
		connection.rollback()
		raise
	table = connection.execute(
		"SELECT seats FROM dining_tables WHERE id = ?", (booking.table_id,)
	).fetchone()
	if table is None:
		connection.rollback()
		raise HTTPException(status_code=404, detail="Stol topilmadi")
	if booking.party_size > table["seats"]:
		connection.rollback()
		raise HTTPException(status_code=422, detail="Mehmonlar soni stol sig‘imidan katta")
	conflict = connection.execute(
		"""
		SELECT 1 FROM bookings
		WHERE table_id = ? AND booking_date = ? AND status = 'confirmed'
		  AND id != ? AND start_time < ? AND end_time > ?
		LIMIT 1
		""",
		(
			booking.table_id,
			booking.booking_date.isoformat(),
			booking_id,
			end.time().isoformat(),
			booking.start_time.isoformat(),
		),
	).fetchone()
	if conflict:
		connection.rollback()
		raise HTTPException(status_code=409, detail="Bu vaqtda stol band qilingan")
	connection.execute(
		"""
		UPDATE bookings
		SET table_id = ?, customer_name = ?, phone = ?, party_size = ?,
		    booking_date = ?, start_time = ?, end_time = ?
		WHERE id = ?
		""",
		(
			booking.table_id,
			booking.customer_name,
			booking.phone,
			booking.party_size,
			booking.booking_date.isoformat(),
			booking.start_time.isoformat(),
			end.time().isoformat(),
			booking_id,
		),
	)
	connection.commit()
	return get_booking(booking_id, connection)


@app.delete("/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_booking(booking_id: int, connection: Database):
	cursor = connection.execute(
		"UPDATE bookings SET status = 'cancelled' WHERE id = ? AND status = 'confirmed'",
		(booking_id,),
	)
	connection.commit()
	if cursor.rowcount == 0:
		exists = connection.execute(
			"SELECT 1 FROM bookings WHERE id = ?", (booking_id,)
		).fetchone()
		if exists:
			raise HTTPException(status_code=409, detail="Bron avval bekor qilingan")
		raise HTTPException(status_code=404, detail="Bron topilmadi")
	return Response(status_code=status.HTTP_204_NO_CONTENT)


if __name__ == "__main__":
	import uvicorn

	uvicorn.run("kursishi:app", host="127.0.0.1", port=8000, reload=False)
