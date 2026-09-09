from functools import wraps
import logging
from uuid import UUID

from flask import current_app, g, request

from app.services.supabase_service import SupabaseService
from app.utils.responses import APIError

logger = logging.getLogger(__name__)


def authenticated(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        parts = request.headers.get("Authorization", "").split()
        if len(parts) != 2 or parts[0].lower() != "bearer" or len(parts[1]) > 8192:
            raise APIError("UNAUTHORIZED", "A Supabase Bearer access token is required.", 401)
        factory = current_app.config.get("SUPABASE_FACTORY", SupabaseService)
        g.db = factory(current_app.config, parts[1])
        g.user = g.db.get_user()
        try:
            g.user_id = str(UUID(g.user["id"]))
        except (ValueError, TypeError, KeyError):
            raise APIError("UNAUTHORIZED", "Invalid user identity.", 401) from None
        logger.info("Authenticated Supabase user uuid=%s", g.user_id)
        return fn(*args, **kwargs)
    return wrapped


def require_trip(trip_id, admin=False, owner=False):
    trip = g.db.one("trips", {"id": trip_id})
    if trip["created_by"] == g.user_id:
        return trip
    if owner:
        raise APIError("FORBIDDEN", "Only the trip owner may perform this action.", 403)
    member = g.db.one("trip_members", {"trip_id": trip_id, "user_id": g.user_id})
    if admin and member["role"] != "admin":
        raise APIError("FORBIDDEN", "Trip administrator permission is required.", 403)
    return trip
