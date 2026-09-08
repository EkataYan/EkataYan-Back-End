from datetime import datetime, timezone
from flask import Blueprint, g
from app.middleware.auth_middleware import authenticated
from app.utils.responses import success
from app.utils.validators import identifier, pagination

bp = Blueprint("notifications", __name__)


@bp.get("/notifications")
@authenticated
def list_notifications():
    page = pagination()
    return success(g.db.select("notifications", {"user_id": g.user_id}, **page), pagination=page)


@bp.put("/notifications/<notification_id>/read")
@authenticated
def mark_read(notification_id):
    notification_id = identifier(notification_id)
    item = g.db.one("notifications", {"id": notification_id, "user_id": g.user_id})
    if not item["read_at"]:
        item = g.db.update("notifications", {"id": notification_id, "user_id": g.user_id},
                           {"read_at": datetime.now(timezone.utc).isoformat()})
    return success(item)
