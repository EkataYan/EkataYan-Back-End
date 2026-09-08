from flask import Blueprint, g
from app.middleware.auth_middleware import authenticated
from app.utils.responses import success
from app.utils.validators import ProfileInput, parse

bp = Blueprint("users", __name__)


@bp.get("/users/me")
@authenticated
def get_me():
    return success(g.db.one("profiles", {"id": g.user_id}))


@bp.put("/users/me")
@authenticated
def update_me():
    data = parse(ProfileInput).model_dump(mode="json")
    return success(g.db.update("profiles", {"id": g.user_id}, data))
