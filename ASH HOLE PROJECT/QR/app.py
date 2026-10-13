"""NEXORA - Hotel & Parking Management
Reservation -> automatic QR ticket -> QR verification at the gate/front desk.

Run:  pip install -r requirements.txt
      python app.py
Open: http://localhost:5000
"""
import base64
import io
import secrets
import sqlite3
from datetime import date

import qrcode
from flask import Flask, g, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)
DB_PATH = "nexora.db"


# ---------- database ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                guest_name TEXT NOT NULL,
                email TEXT NOT NULL,
                room_type TEXT NOT NULL,
                check_in TEXT NOT NULL,
                check_out TEXT NOT NULL,
                parking INTEGER NOT NULL DEFAULT 0,
                plate TEXT,
                status TEXT NOT NULL DEFAULT 'reserved',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )


# ---------- helpers ----------
ROOMS = ["Standard", "Deluxe", "Suite"]


def make_qr_data_uri(text: str) -> str:
    """Generate a QR code and return it as a base64 PNG data URI."""
    qr = qrcode.QRCode(box_size=10, border=2,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#14202B", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def new_code() -> str:
    return "NXR-" + secrets.token_hex(3).upper()


# ---------- routes ----------
@app.route("/")
def index():
    return render_template("index.html", rooms=ROOMS, today=date.today().isoformat(),
                           reservation=None, error=None)


@app.route("/reserve", methods=["POST"])
def reserve():
    f = request.form
    name, email = f.get("guest_name", "").strip(), f.get("email", "").strip()
    room = f.get("room_type", "")
    check_in, check_out = f.get("check_in", ""), f.get("check_out", "")
    parking = 1 if f.get("parking") else 0
    plate = f.get("plate", "").strip().upper() if parking else None

    error = None
    if not name or not email:
        error = "Enter your name and email."
    elif room not in ROOMS:
        error = "Choose a room type."
    elif not check_in or not check_out or check_out <= check_in:
        error = "Check-out must be after check-in."
    elif check_in < date.today().isoformat():
        error = "Check-in can't be in the past."
    elif parking and not plate:
        error = "Enter your plate number to reserve parking."

    if error:
        return render_template("index.html", rooms=ROOMS, today=date.today().isoformat(),
                               reservation=None, error=error), 400

    code = new_code()
    db().execute(
        "INSERT INTO reservations (code, guest_name, email, room_type, check_in, check_out, parking, plate)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (code, name, email, room, check_in, check_out, parking, plate),
    )
    db().commit()
    return redirect(url_for("ticket", code=code))


@app.route("/ticket/<code>")
def ticket(code):
    row = db().execute("SELECT * FROM reservations WHERE code=?", (code,)).fetchone()
    if not row:
        return "Reservation not found", 404
    # The QR points to the verify endpoint, so any phone camera opens it
    verify_url = url_for("verify", code=code, _external=True)
    return render_template("index.html", rooms=ROOMS, today=date.today().isoformat(),
                           reservation=row, qr=make_qr_data_uri(verify_url),
                           verify_url=verify_url, error=None)


@app.route("/verify/<code>")
def verify(code):
    """Scanned by staff at reception or the parking gate."""
    row = db().execute("SELECT * FROM reservations WHERE code=?", (code,)).fetchone()
    if not row:
        return jsonify(valid=False, message="Reservation not found"), 404
    return jsonify(valid=True, code=row["code"], guest=row["guest_name"],
                   room=row["room_type"], check_in=row["check_in"],
                   check_out=row["check_out"], parking=bool(row["parking"]),
                   plate=row["plate"], status=row["status"])


@app.route("/verify/<code>/checkin", methods=["POST"])
def checkin(code):
    """Call from your staff app/gate controller to mark the guest as arrived."""
    cur = db().execute("UPDATE reservations SET status='checked_in' WHERE code=?", (code,))
    db().commit()
    if cur.rowcount == 0:
        return jsonify(ok=False), 404
    return jsonify(ok=True, status="checked_in")


if __name__ == "__main__":
    init_db()
    # host 0.0.0.0 lets phones on the same Wi-Fi open the QR link
    app.run(host="0.0.0.0", port=5000, debug=True)
