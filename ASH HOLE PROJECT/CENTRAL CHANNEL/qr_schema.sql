CREATE TABLE IF NOT EXISTS QRTickets (
    receipt_code TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES Users(id) ON DELETE CASCADE,
    hotel_booking_id TEXT UNIQUE REFERENCES HotelBookings(id) ON DELETE CASCADE,
    parking_booking_id TEXT UNIQUE REFERENCES ParkingBookings(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    user_email TEXT NOT NULL,
    guest_name TEXT NOT NULL,
    hotel_room TEXT,
    hotel_floor INTEGER,
    parking_slot TEXT,
    vehicle_plate TEXT,
    check_in TEXT,
    check_out TEXT,
    parking_start_at TEXT,
    parking_end_at TEXT,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending'
        CONSTRAINT qrtickets_status_check
        CHECK (status IN ('Pending', 'Active', 'Cancelled', 'Completed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS IX_QRTickets_User
    ON QRTickets(user_id, created_at DESC);

ALTER TABLE QRTickets
    DROP CONSTRAINT IF EXISTS qrtickets_status_check;

ALTER TABLE QRTickets
    ADD CONSTRAINT qrtickets_status_check
    CHECK (status IN ('Pending', 'Active', 'Cancelled', 'Completed'));
