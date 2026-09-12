from flask import Blueprint, current_app, g
from app.middleware.auth_middleware import authenticated
from app.repositories import ProfileRepository
from app.utils.responses import success
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
    return success(ProfileRepository(g.db).update(g.user_id, data))
