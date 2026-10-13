"""SQLite schema and reusable connection helpers."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from . import config


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS Users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('Admin', 'Hotel Personnel', 'Parking Personnel', 'User')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS Personnel (
    user_id TEXT PRIMARY KEY REFERENCES Users(id) ON DELETE CASCADE,
    department TEXT NOT NULL CHECK (department IN ('Hotel', 'Parking')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS Rooms (
    id TEXT PRIMARY KEY,
    room_number TEXT NOT NULL UNIQUE,
    room_type TEXT NOT NULL DEFAULT 'Standard',
    status TEXT NOT NULL DEFAULT 'Available' CHECK (status IN ('Available', 'Reserved', 'Occupied', 'Maintenance')),
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ParkingSlots (
    id TEXT PRIMARY KEY,
    slot_code TEXT NOT NULL UNIQUE,
    accessible INTEGER NOT NULL DEFAULT 0,
    ev_charging INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Available' CHECK (status IN ('Available', 'Reserved', 'Occupied', 'Maintenance'))
);
CREATE TABLE IF NOT EXISTS Vehicles (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES Users(id),
    vehicle_type TEXT NOT NULL,
    plate_number TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS HotelBookings (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES Users(id),
    assigned_personnel_id TEXT REFERENCES Users(id),
    room_id TEXT REFERENCES Rooms(id),
    property_name TEXT NOT NULL DEFAULT '',
    guest_name TEXT NOT NULL,
    guest_email TEXT NOT NULL,
    guest_phone TEXT NOT NULL DEFAULT '',
    room_type TEXT NOT NULL,
    check_in TEXT NOT NULL,
    check_out TEXT NOT NULL,
    guest_count INTEGER NOT NULL CHECK (guest_count > 0),
    status TEXT NOT NULL DEFAULT 'Pending',
    notes TEXT NOT NULL DEFAULT '',
    internal_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS IX_HotelBookings_Dates ON HotelBookings(check_in, check_out, status);
CREATE TABLE IF NOT EXISTS ParkingBookings (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES Users(id),
    assigned_personnel_id TEXT REFERENCES Users(id),
    parking_slot_id TEXT REFERENCES ParkingSlots(id),
    vehicle_id TEXT NOT NULL REFERENCES Vehicles(id),
    property_name TEXT NOT NULL DEFAULT '',
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending',
    notes TEXT NOT NULL DEFAULT '',
    internal_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS IX_ParkingBookings_Times ON ParkingBookings(start_at, end_at, status);
CREATE TABLE IF NOT EXISTS Notifications (
    id TEXT PRIMARY KEY,
    recipient_user_id TEXT REFERENCES Users(id) ON DELETE CASCADE,
    audience_role TEXT,
    category TEXT NOT NULL,
    booking_type TEXT,
    booking_id TEXT,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT
);
CREATE INDEX IF NOT EXISTS IX_Notifications_Recipient ON Notifications(recipient_user_id, created_at);
CREATE TABLE IF NOT EXISTS BookingHistory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_type TEXT NOT NULL,
    booking_id TEXT NOT NULL,
    actor_user_id TEXT REFERENCES Users(id),
    action TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT,
    details TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS IX_BookingHistory_Booking ON BookingHistory(booking_type, booking_id, created_at);
CREATE TABLE IF NOT EXISTS Sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES Users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool | None:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(database_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(database_path or config.DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10, isolation_level="DEFERRED", factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def initialize(database_path: str | Path | None = None) -> None:
    with connect(database_path) as connection:
        connection.executescript(SCHEMA)
        if connection.execute("SELECT COUNT(*) FROM Rooms").fetchone()[0] == 0:
            connection.executemany(
                "INSERT INTO Rooms (id, room_number, room_type) VALUES (?, ?, ?)",
                [
                    (str(uuid.uuid4()), f"{100 + number}", "Deluxe" if number % 6 == 0 else "Standard")
                    for number in range(1, 37)
                ],
            )
        if connection.execute("SELECT COUNT(*) FROM ParkingSlots").fetchone()[0] == 0:
            connection.executemany(
                "INSERT INTO ParkingSlots (id, slot_code, accessible, ev_charging) VALUES (?, ?, ?, ?)",
                [
                    (str(uuid.uuid4()), f"P-{number:02}", int(number <= 4), int(number % 8 == 0))
                    for number in range(1, 49)
                ],
            )