from flask import Blueprint, g
from app.middleware.auth_middleware import authenticated, require_trip
from app.services.chat_service import ChatService
from app.utils.responses import success
from app.utils.validators import MessageInput, identifier, pagination, parse

bp = Blueprint("chat", __name__)


@bp.get("/trips/<trip_id>/messages")
@authenticated
def messages(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id)
    page = pagination()
    return success(ChatService(g.db).list(trip_id, page), pagination=page)


@bp.post("/trips/<trip_id>/messages")
@authenticated
def send(trip_id):
    trip_id = identifier(trip_id)
    data = parse(MessageInput)
    require_trip(trip_id)
    return success(ChatService(g.db).send(trip_id, g.user_id, data.content), 201)
