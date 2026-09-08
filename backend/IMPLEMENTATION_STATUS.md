# Implementation notes

No commits or pushes were made. The original root README was replaced with complete setup documentation.

## Repository inspection

Initially only README.md was tracked (one-line project title), with untracked .idea settings.
Branch: develop/backend. No existing backend or local AGENTS.md was found.
IDE settings were preserved and are now ignored by the new root .gitignore.

## Created so far

- Modular Flask factory, environment configuration, error envelopes, CORS, health endpoint.
- Request-scoped httpx Supabase adapter: Auth user validation, PostgREST CRUD/RPC.
- Authentication decorator and trip permission helper.
- Pydantic request models, money/split/date validation and pagination.
- Blueprints for auth session, profiles, trips, members, expenses, chat, notifications.
- AI, weather and private image-storage provider boundaries; itinerary, weather and image routes.
- Supabase schema migration with tables, indexes, RLS, storage policies and transactional RPCs.
- Runtime/development dependency lists, environment example, pytest coverage and full setup README.
- Dependencies were installed in the ignored local `.venv`; pytest and startup/import checks passed.

## Follow-up work

The completed foundation still needs real-Supabase RLS integration tests, notification-generating
database triggers, signed Storage downloads, push delivery, rate limits, production monitoring,
CI and invitation flows. Apply the migration to a development project before using it; it has not
been executed here because no Supabase project credentials were provided.

## Design decisions to retain/review

Android handles Supabase sign-in/refresh. Backend verifies access tokens with /auth/v1/user.
All database/storage calls must carry that user's token so RLS applies; service-role config is
reserved and unused. No shared mutable auth client. Core Supabase URL/key required at startup;
AI/weather missing credentials should fail only on feature use. PUT models are full replacements.
Owner alone manages membership/deletes trips; admins edit trips; members read/chat/add expenses;
expense creator/admin can edit/delete. Money uses Decimal in validation and must use numeric SQL.
Lists are bounded offset pagination, newest first.

Review adapter JSON decimal parsing (currently default JSON floating point), error handling,
and SQL permission parity before considering any feature complete. No live Supabase/API calls
or database migrations have been performed. No credentials are available or invented.
