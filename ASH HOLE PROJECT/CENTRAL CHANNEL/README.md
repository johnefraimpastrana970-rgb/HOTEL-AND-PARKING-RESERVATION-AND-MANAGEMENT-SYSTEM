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

Admins can pause or resume reservation API access from the switch in the upper-right corner of the dashboard. While paused, non-admin reservation API requests are rejected; login and the Admin dashboard remain available so an Admin can resume service. The setting is stored in PostgreSQL, so it remains consistent across app replicas and backend restarts.

An existing administrator can create additional Admin accounts from **Personnel management → Create administrator account**. Enter a unique username and email and a password of at least 10 characters. Supabase email confirmation settings apply to newly created accounts; if confirmation is enabled, the new administrator must confirm their email before signing in. The form is available only to Admin users, and account creation uses the server's Supabase publishable key, not a service-role key.

On Windows, you can instead double-click `RUN_RESERVATION_SITE.bat` in the workspace root. It starts the backend, waits for it to respond, and opens the sign-in page. After you sign in or register, the reservation page opens. Keep the backend console window open while using the site.

`SUPABASE_DATABASE_SCHEMA` selects the PostgreSQL schema (default `public`). The other `.env` settings configure the host, port, session lifetime, first-admin bootstrap, allowed origins, or an external API base URL.

## Production traffic and operations

The API keeps Supabase bearer-token authentication and server-side role/ownership checks for every protected endpoint. It applies a general API limit (default 120 requests per minute per client IP), with tighter limits for login (10/minute), registration (5/hour), and token refresh (30/minute). A 429 response includes `Retry-After`. Configure the limits with the `CENTRAL_*_RATE_LIMIT_*` settings in `.env.example`.

Set `CENTRAL_REDIS_URL` to a private Redis/Valkey service in production. This makes rate limits atomic and shared across replicas; if Redis is configured but unavailable, requests fail with 503 rather than bypassing the protection. Without it, the development fallback is process-local, is reported as `rateLimitMode: "local"` by the readiness endpoint, and is not suitable for a load-balanced deployment. When behind a reverse proxy or load balancer, set `CENTRAL_TRUSTED_PROXY_CIDRS` to only the proxy CIDRs so client IPs can be read safely from forwarded headers. Do not trust arbitrary forwarded headers.

`GET /api/health/live` is a liveness check independent of database connectivity. `GET /api/health/ready` (also available at the existing `/api/health`) checks PostgreSQL and a configured Redis service. API responses carry an `X-Request-ID`; JSON access/error logs include the request ID, status, path, and duration without logging request bodies or bearer tokens. Database initialization retries transient startup connection failures, and the threaded server waits for active requests during shutdown. For production, run behind HTTPS and a production-grade reverse proxy/load balancer, use multiple app replicas only with shared Redis, and enable managed database backups/point-in-time recovery and centralized log retention/alerting.

The development static-file host does not serve dotfiles, backend source, dependency manifests, or local database files. Keep production secrets in the hosting platform's secret manager rather than in deployed static assets.

## REST API

The service exposes bearer-token authentication at `/api/auth/register`, `/api/auth/login`, `/api/auth/me`, and `/api/auth/logout`. Booking endpoints include:

- `GET /api/admin/reservations/status`, `PUT /api/admin/reservations/status` (Admin-only reservation availability control)

- `GET /api/bookings`, `GET /api/hotel/bookings`, `GET /api/parking/bookings`
- `POST /api/hotel/bookings`, `POST /api/parking/bookings`
- `PUT /api/bookings/{id}/accept|approve|reject|cancel|check-in|check-out|assign`
- `PATCH /api/bookings/{id}`
- `GET /api/rooms`, `GET /api/parking/slots`
- `GET /api/personnel`, `GET /api/notifications`, `GET /api/history`

`CENTRAL_API_BASE` may be set on `window` before `api-client.js` loads to target a compatible external REST service. The default uses the current web origin, or `http://127.0.0.1:8000` when opened as a local file.

The NEXORA hotel walkthrough in the main website reads the authenticated room and parking inventories from the API when the walkthrough starts and refreshes them every 20 seconds. Database room numbers and parking slot codes are shown in the 3D scene; reserved or occupied resources appear unavailable. The walkthrough is a visualization only—make reservations through the booking pages.

## Roles and data

Roles are `Admin`, `Hotel Personnel`, `Parking Personnel`, and `User`. API authorization limits personnel to their department and users to their own reservations. Supabase Auth verifies passwords and bearer tokens; the app stores profile and role data in PostgreSQL and refreshes expiring access tokens. Approval and check-in/check-out state changes reserve, occupy, or release the matching room or parking slot in the same transaction and write notifications plus booking-history entries.

Reservation checkout supports manual Cash or Bank transfer selection. Parking guests can select a specific available space from the live slot map before proceeding to checkout; the API rechecks and reserves that selected space during booking creation, rejecting the request if another booking claimed it meanwhile. Submitting a reservation does not charge the guest; the API automatically approves it and assigns an available room or parking slot from the shared inventory when one is free for the requested dates and times. If no resource is available, an unassigned request remains Pending for Admin or matching personnel to review. The PostgreSQL schema includes Users, Personnel, HotelBookings, Rooms, ParkingBookings, ParkingSlots, Vehicles, Notifications, BookingHistory, and Sessions. Existing records in the old SQLite file are not copied automatically; export/import them before switching if they need to be retained. Back up the Supabase database regularly. The included HTTP server is intended for local development; production deployments should use HTTPS, a production WSGI/ASGI server, and a restricted `CENTRAL_ALLOWED_ORIGINS` value.

The customer page can display sample prices in USD, EUR, GBP, or PHP. EUR, GBP, and PHP display values use Frankfurter's latest published USD exchange rates, refreshed when the page opens and periodically while it remains open. If the rate service is unavailable, the page uses the last saved rates and shows their publication date. These are indicative display conversions only: the reservation API does not charge a payment or store a converted transaction amount.

## Tests

```powershell
Push-Location "CENTRAL CHANNEL"
python -m pip install -r requirements.txt
python -m unittest backend.test_api -v
Pop-Location
```

API integration tests create and remove a uniquely named schema and temporary Supabase Auth users, so run them only against a development project. They are skipped unless the database URL, Supabase URL, publishable key, and server-only secret key are configured.