# EkataYan backend

EkataYan is a Flask REST backend for the Android travel-planning application. It uses Supabase for authentication, PostgreSQL data and private image storage. It provides profiles, trips, group planning, shared expenses, group messages, notifications, AI itinerary generation and weather forecasts. Booking integrations are deliberately out of scope.

## Architecture

The application lives in `backend/` and uses an application factory plus feature Blueprints. Routes validate request data and call services; services isolate Supabase, AI, weather and storage providers. The Android app signs in with Supabase Auth and sends `Authorization: Bearer <access-token>` to protected endpoints. The backend verifies that token using Supabase Auth, then makes PostgREST and Storage calls using the same token. This means PostgreSQL Row Level Security (RLS) remains the final access-control boundary.

`SUPABASE_SERVICE_ROLE_KEY` is reserved for a future trusted background worker. It is never needed by Android and is not used by any user-facing endpoint.

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

It listens at `http://127.0.0.1:5000`; verify with `GET /api/health`. For a production deployment, use a process manager/WSGI server such as Waitress, set `FLASK_ENV=production`, keep `FLASK_DEBUG=false`, terminate TLS at the deployment edge, and configure exact Android/web origins.

The production server included in `requirements.txt` is Waitress. From `backend/`, use:

```powershell
waitress-serve --listen=0.0.0.0:$env:PORT run:app
```

On a Linux deployment platform, Gunicorn is installed by `requirements.txt`; use `gunicorn --bind 0.0.0.0:$PORT run:app` from `backend/`.

## Supabase initialization

For a new project, run [001_ekatayan_schema.sql](backend/supabase/migrations/001_ekatayan_schema.sql) in the Supabase SQL editor or apply it with the Supabase CLI. If `001` was already applied, run `002_profile_contact_fields.sql` instead to add/backfill profile contact fields and update the provisioning trigger. Create the two private buckets named `profile-images` and `trip-images`, with a 5 MB limit and JPEG/PNG/WebP MIME types; the migration includes the matching object policies. The migration creates:

- `profiles` linked one-to-one with Supabase-managed `auth.users`, including email and phone contact fields
- `trips` and `trip_members`
- `itineraries`, `itinerary_days`, and `itinerary_activities`
- `expenses` and `expense_participants`
- `group_messages` and `notifications`

It also defines indexes, profile and owner-membership triggers, RLS policies, and the atomic `save_expense` and `save_itinerary` functions. Apply it to an empty/new project first and review it with your database administrator before production. RLS integration tests require a real Supabase project and are not included in the local unit test suite.

## API

Responses use `{ "success": true, "data": ... }`; failures use `{ "success": false, "error": { "code", "message" } }`.

Public endpoints: `GET /api/health`, `GET /api/weather?latitude=&longitude=&date=`.

Protected endpoints:

- `GET /api/auth/session`; `GET`/`PUT /api/users/me`
- `POST`/`GET /api/trips`; `GET`/`PUT`/`DELETE /api/trips/<trip_id>`
- `POST`/`GET /api/trips/<trip_id>/members`; `DELETE /api/trips/<trip_id>/members/<user_id>`
- `POST /api/itineraries/generate`; `GET /api/trips/<trip_id>/itineraries`
- `POST`/`GET /api/trips/<trip_id>/expenses`; `PUT`/`DELETE /api/expenses/<expense_id>`
- `POST`/`GET /api/trips/<trip_id>/messages`
- `GET /api/notifications`; `PUT /api/notifications/<notification_id>/read`
- `POST /api/storage/profile-picture`; `POST /api/trips/<trip_id>/images` (multipart field: `file`)

All UUIDs are server-validated. Clients never set a trip creator or message sender. Trip owners manage membership and deletion; trip admins edit trips and generate itineraries; members can access trip content, send messages and record expenses. Money is validated as decimal and stored as PostgreSQL `numeric(14,2)`.

## Tests

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest
```

The tests use a fake Supabase adapter, so they cover Flask response structure, validation, token-required routes, a basic trip write and CORS without calling Supabase, AI, or weather providers.

## Current limitations

Supabase email/invite delivery, push delivery (such as FCM), booking providers, realtime chat, signed Storage download URLs, rate limiting, observability, CI and real-project RLS integration tests are still future work. AI and weather routes return a configuration error until their environment variables are supplied. Do not put `.env` or any credentials in source control.
