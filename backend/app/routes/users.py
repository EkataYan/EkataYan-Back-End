import re

from flask import Blueprint, current_app, g, request
from app.middleware.auth_middleware import authenticated
from app.repositories import ProfileRepository
from app.utils.responses import APIError, success
from app.utils.validators import ProfileInput, ProfilePatchInput, parse

bp = Blueprint("users", __name__)


@bp.get("/users/me")
@authenticated
def get_me():
    try:
        profile = ProfileRepository(g.db).get(g.user_id)
    except Exception:
        current_app.logger.exception("Profile fetch failed for user uuid=%s", g.user_id)
        raise
    current_app.logger.info("Profile fetch succeeded for user uuid=%s", g.user_id)
    return success(profile)


@bp.put("/users/me")
@authenticated
def update_me():
    data = parse(ProfileInput).model_dump(mode="json")
    return success(ProfileRepository(g.db).update(g.user_id, data))


@bp.patch("/users/me")
@authenticated
def patch_me():
    profile = parse(ProfilePatchInput, error_status=400)
    data = profile.model_dump(mode="json", exclude_unset=True)
    try:
        return success(ProfileRepository(g.db).update(g.user_id, data))
    except APIError as error:
        if "username" in data and error.code == "CONFLICT":
            raise APIError("USERNAME_TAKEN", "That username is already taken.", 409) from None
        raise


@bp.get("/users/search")
@authenticated
def search_users():
    query = request.args.get("q", "").strip().removeprefix("@").lower()
    if not 1 <= len(query) <= 20 or not all(character.isalnum() or character == "_" or character.isspace() for character in query):
        raise APIError("INVALID_REQUEST", "Search must be between 1 and 20 characters.", 400)
    trip_id = request.args.get("trip_id")
    if trip_id:
        from app.repositories import InvitationRepository
        from app.utils.validators import identifier
        trip_id = identifier(trip_id)
        rows = InvitationRepository(g.db).search_candidates(trip_id, query)
    else:
        rows = ProfileRepository(g.db).search(query)
    return success([{
        "id": row["id"], "username": row["username"],
        "display_name": row.get("display_name", ""), "avatar_url": row.get("avatar_url"),
        **({"relationship": row["relationship"]} if "relationship" in row else {}),
    } for row in rows])


@bp.get("/users/username-availability")
@authenticated
def username_availability():
    raw = request.args.get("username", "").strip().removeprefix("@").lower()
    if not re.fullmatch(r"[a-z0-9_]{3,20}", raw):
        return success({"username": raw, "available": False, "valid": False})
    available = bool(ProfileRepository(g.db).username_available(raw))
    return success({"username": raw, "available": available, "valid": True})
