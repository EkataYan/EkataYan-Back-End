from datetime import datetime, timezone
from flask import Blueprint, g
from app.middleware.auth_middleware import authenticated
from app.repositories import NotificationRepository
from app.utils.responses import success
from app.utils.validators import identifier, pagination

bp = Blueprint("notifications", __name__)


@bp.get("/notifications")
@authenticated
def list_notifications():
    page = pagination()
    return success(NotificationRepository(g.db).list(g.user_id, page), pagination=page)


@bp.put("/notifications/<notification_id>/read")
@authenticated
def mark_read(notification_id):
    notification_id = identifier(notification_id)
    repository = NotificationRepository(g.db)
    item = repository.get(notification_id, g.user_id)
    if not item["read_at"]:
        item = repository.mark_read(notification_id, g.user_id, datetime.now(timezone.utc).isoformat())
    return success(item)
