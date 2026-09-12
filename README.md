# EkataYan backend

EkataYan is a Flask REST backend for the Android travel-planning application. It uses Supabase for authentication, PostgreSQL data and private image storage. It provides profiles, trips, group planning, shared expenses, group messages, notifications, AI itinerary generation and weather forecasts. Booking integrations are deliberately out of scope.

## Architecture

The application lives in `backend/` and uses an application factory plus feature Blueprints. Routes validate request data and call services; services isolate Supabase, AI, weather and storage providers. The Android app signs in with Supabase Auth and sends `Authorization: Bearer <access-token>` to protected endpoints. The backend verifies that token using Supabase Auth, then makes PostgREST and Storage calls using the same token. This means PostgreSQL Row Level Security (RLS) remains the final access-control boundary.

No service-role key is used. User-facing requests use the authenticated caller's JWT, so RLS
remains the database authorization boundary.

## Setup

Requirements: Python 3.11 or newer, a Supabase project, and optionally an AI provider and WeatherAPI account.

```powershell
cd backend
py -m venv ..\.venv
..\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Set `SUPABASE_URL` and `SUPABASE_KEY` in `backend/.env`. `SUPABASE_KEY` must be the project’s publishable key (or legacy anon key), never a service-role/secret key. Use explicit `CORS_ORIGINS`; the sample contains development origins. Set `AI_BASE_URL`, `AI_MODEL`, and `AI_API_KEY` only when enabling the OpenAI-compatible itinerary provider. Set `WEATHER_API_KEY` only when enabling WeatherAPI.

AI configuration is optional. Omit `AI_API_KEY`, `AI_BASE_URL`, and `AI_MODEL` to run the backend with itinerary generation disabled, or set all three to enable the OpenAI-compatible provider. Calls to the generation endpoint return HTTP 503 while AI is disabled; unrelated endpoints continue normally.

Start the development server from `backend/`:

```powershell
python run.py
```

It listens at `http://127.0.0.1:5000`; verify with `GET /health` (the existing
`GET /api/health` alias is also retained). For a production deployment, use a
process manager/WSGI server such as Waitress, set `FLASK_ENV=production`, keep
`FLASK_DEBUG=false`, terminate TLS at the deployment edge, and configure exact
Android/web origins.

The production server included in `requirements.txt` is Waitress. From `backend/`, use:

```powershell
waitress-serve --listen=0.0.0.0:$env:PORT run:app
```

On Linux, Gunicorn is installed by `requirements.txt`. The Flask package uses an
application factory; the actual WSGI object is `app` in `run.py`, so the target
is `run:app` (not `app:app`).

## Railway deployment

Deploy the `EkataYan-Back-End` repository with these Railway service settings:

- Root Directory: `/backend`
- Build Command: leave empty (Railpack installs `requirements.txt`)
- Start Command: `gunicorn run:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 90 --access-logfile - --error-logfile -`
- Healthcheck Path: `/health`

The committed `backend/Procfile` supplies the same start command when Railway
uses automatic Railpack detection. Railway supplies `PORT`; do not hardcode it.
The 90-second worker timeout is intentionally longer than the backend's
45-second AI provider timeout.

Required Railway variables are `SUPABASE_URL` and exactly one client-safe key:
prefer `SUPABASE_PUBLISHABLE_KEY`; `SUPABASE_ANON_KEY` and the legacy
`SUPABASE_KEY` name are accepted for compatibility. Never configure a Supabase
secret/service-role key as any of those values. `FLASK_ENV` should be
`production` and `FLASK_DEBUG` must be `false`.

Optional feature variables are `AI_PROVIDER`, `AI_API_KEY`, `AI_BASE_URL`,
`AI_MODEL`, `WEATHER_PROVIDER`, `WEATHER_API_KEY`, and `CORS_ORIGINS`. AI is
enabled only when all three `AI_API_KEY`, `AI_BASE_URL`, and `AI_MODEL` values
are present. Weather returns a controlled 503 when its key is absent. An absent
or invalid Supabase configuration also returns a controlled 503 from protected
routes instead of preventing Gunicorn from booting; `/health` remains
dependency-free.

## Supabase initialization

Apply the ordered SQL files in `backend/supabase/migrations/`. Existing projects must continue
from their last applied migration; never reset a populated database. The connected project has
`003`-`007` recorded in migration history. The migrations configure private `profile-images` and
`trip-images` buckets with a 5 MB limit and JPEG/PNG/WebP MIME types. The schema contains:

- `profiles` linked one-to-one with Supabase-managed `auth.users`, including email and phone contact fields
- `trips` and `trip_members`
- `itineraries`, `itinerary_days`, and `itinerary_activities`
- `expenses` and `expense_participants`
- `group_messages` and `notifications`
- `wishlists` and `saved_places`

It also defines indexes, profile and owner-membership triggers, RLS policies, and the atomic `save_expense` and `save_itinerary` functions. Apply it to an empty/new project first and review it with your database administrator before production. RLS integration tests require a real Supabase project and are not included in the local unit test suite.

## API

Responses use `{ "success": true, "data": ... }`; failures use `{ "success": false, "error": { "code", "message" } }`.

Public endpoints: `GET /health` and the compatibility alias `GET /api/health`.

Protected endpoints:

- `GET /api/auth/session`; `GET`/`PUT`/`PATCH /api/users/me`
- `POST`/`GET /api/trips`; `GET`/`PUT`/`DELETE /api/trips/<trip_id>`
- `POST`/`GET /api/trips/<trip_id>/members`; `DELETE /api/trips/<trip_id>/members/<user_id>`
- `POST /api/itineraries/generate`; `GET /api/trips/<trip_id>/itineraries`
- `GET /api/weather?location=&date=` (or authenticated latitude/longitude coordinates)
- `POST`/`GET /api/trips/<trip_id>/expenses`; `PUT`/`DELETE /api/expenses/<expense_id>`
- `POST`/`GET /api/trips/<trip_id>/messages`
- `GET /api/notifications`; `PUT /api/notifications/<notification_id>/read`
- `GET`/`POST /api/wishlists`; `GET`/`PATCH`/`DELETE /api/wishlists/<wishlist_id>`
- `POST /api/wishlists/<wishlist_id>/places`; `DELETE /api/wishlists/<wishlist_id>/places/<place_id>`
- `POST /api/storage/profile-picture`; `POST /api/trips/<trip_id>/images` (multipart field: `file`)

All UUIDs are server-validated. Clients never set a trip creator or message sender. Trip owners manage membership and deletion; trip admins edit trips and generate itineraries; members can access trip content, send messages and record expenses. Money is validated as decimal and stored as PostgreSQL `numeric(14,2)`.

## Tests

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest
```

The tests use a fake Supabase adapter, so they cover Flask response structure, validation, token-required routes, a basic trip write and CORS without calling Supabase, AI, or weather providers.

## Current limitations

Supabase email/invite delivery, push delivery (such as FCM), booking providers, realtime chat,
signed Storage download URLs, rate limiting, observability and CI are still future work. AI and
weather routes return a configuration error until their environment variables are supplied. Do
not put `.env` or any credentials in source control.
