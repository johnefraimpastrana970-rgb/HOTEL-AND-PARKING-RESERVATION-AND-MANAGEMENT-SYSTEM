# Central Channel

Hotel and parking reservation management UI, customer booking handoff, and a Python REST service backed by Supabase PostgreSQL.

## Run locally

Install the PostgreSQL driver and configure your Supabase project first:

```powershell
python -m pip install -r "CENTRAL CHANNEL/requirements.txt"
```

Copy `CENTRAL CHANNEL/.env.example` to `CENTRAL CHANNEL/.env` and set `SUPABASE_DATABASE_URL` to the database connection string from your Supabase project's **Connect** dialog. Set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` from the project's API settings. Keep all keys in the local `.env`; `SUPABASE_SECRET_KEY` is server-only and is only required to run integration tests that create and remove test Auth users. The service creates its tables and seeds the initial room and parking inventory when it starts.

From the workspace root, start the service:

```powershell
python "CENTRAL CHANNEL/run.py"
```

Open `http://127.0.0.1:8000/LOGIN%20PANEL/index.html`. Supabase Auth manages passwords, confirmation emails, and bearer tokens. On a fresh database, the first signup becomes the administrator; later signups receive the `User` role. The administrator can promote registered users to Hotel Personnel or Parking Personnel from the dashboard. To disable first-signup bootstrap, set `CENTRAL_FIRST_SIGNUP_ADMIN=0` and create the administrator interactively with:

```powershell
python "CENTRAL CHANNEL/run.py" --create-admin
```

Administrators can open the dedicated portal at `http://127.0.0.1:8000/admin`. Sign in with an account whose role is `Admin`; regular customer accounts are not granted admin access.

An existing administrator can create additional Admin accounts from **Personnel management → Create administrator account**. Enter a unique username and email and a password of at least 10 characters. Supabase email confirmation settings apply to newly created accounts; if confirmation is enabled, the new administrator must confirm their email before signing in. The form is available only to Admin users, and account creation uses the server's Supabase publishable key, not a service-role key.

On Windows, you can instead double-click `RUN_RESERVATION_SITE.bat` in the workspace root. It starts the backend, waits for it to respond, and opens the sign-in page. After you sign in or register, the reservation page opens. Keep the backend console window open while using the site.

`SUPABASE_DATABASE_SCHEMA` selects the PostgreSQL schema (default `public`). The other `.env` settings configure the host, port, session lifetime, first-admin bootstrap, allowed origins, or an external API base URL.

## REST API

The service exposes bearer-token authentication at `/api/auth/register`, `/api/auth/login`, `/api/auth/me`, and `/api/auth/logout`. Booking endpoints include:

- `GET /api/bookings`, `GET /api/hotel/bookings`, `GET /api/parking/bookings`
- `POST /api/hotel/bookings`, `POST /api/parking/bookings`
- `PUT /api/bookings/{id}/accept|approve|reject|cancel|check-in|check-out|assign`
- `PATCH /api/bookings/{id}`
- `GET /api/rooms`, `GET /api/parking/slots`
- `GET /api/personnel`, `GET /api/notifications`, `GET /api/history`

`CENTRAL_API_BASE` may be set on `window` before `api-client.js` loads to target a compatible external REST service. The default uses the current web origin, or `http://127.0.0.1:8000` when opened as a local file.

## Roles and data

Roles are `Admin`, `Hotel Personnel`, `Parking Personnel`, and `User`. API authorization limits personnel to their department and users to their own reservations. Supabase Auth verifies passwords and bearer tokens; the app stores profile and role data in PostgreSQL and refreshes expiring access tokens. Approval and check-in/check-out state changes reserve, occupy, or release the matching room or parking slot in the same transaction and write notifications plus booking-history entries.

Reservation checkout supports manual Cash or Bank transfer selection. Submitting a reservation does not charge the guest; it saves the selected method and creates a Pending request for Admin or matching personnel to review and approve. The PostgreSQL schema includes Users, Personnel, HotelBookings, Rooms, ParkingBookings, ParkingSlots, Vehicles, Notifications, BookingHistory, and Sessions. Existing records in the old SQLite file are not copied automatically; export/import them before switching if they need to be retained. Back up the Supabase database regularly. The included HTTP server is intended for local development; production deployments should use HTTPS, a production WSGI/ASGI server, and a restricted `CENTRAL_ALLOWED_ORIGINS` value.

## Tests

```powershell
Push-Location "CENTRAL CHANNEL"
python -m pip install -r requirements.txt
python -m unittest backend.test_api -v
Pop-Location
```

API integration tests create and remove a uniquely named schema and temporary Supabase Auth users, so run them only against a development project. They are skipped unless the database URL, Supabase URL, publishable key, and server-only secret key are configured.