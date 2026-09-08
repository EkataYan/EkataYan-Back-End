from flask import Blueprint, g
from app.middleware.auth_middleware import authenticated
from app.utils.responses import success

bp = Blueprint("auth", __name__)


@bp.get("/auth/session")
@authenticated
def session():
    return success({"user_id": g.user_id, "email": g.user.get("email")})
