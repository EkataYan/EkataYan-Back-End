from flask import Blueprint, g
from app.middleware.auth_middleware import authenticated, require_trip
from app.repositories import MembershipRepository
from app.utils.responses import APIError, success
from app.utils.validators import MemberInput, identifier, pagination, parse

bp = Blueprint("groups", __name__)


@bp.get("/trips/<trip_id>/members")
@authenticated
def members(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id)
    page = pagination()
    return success(MembershipRepository(g.db).list(trip_id, page), pagination=page)


@bp.post("/trips/<trip_id>/members")
@authenticated
def add(trip_id):
    trip_id = identifier(trip_id)
    member = parse(MemberInput)
    require_trip(trip_id, owner=True)
    data = member.model_dump(mode="json") | {"trip_id": trip_id}
    return success(MembershipRepository(g.db).add(data), 201)


@bp.delete("/trips/<trip_id>/members/<user_id>")
@authenticated
def remove(trip_id, user_id):
    trip_id, user_id = identifier(trip_id), identifier(user_id)
    trip = require_trip(trip_id, owner=True)
    if user_id == trip["created_by"]:
        raise APIError("CONFLICT", "The trip owner cannot be removed.", 409)
    MembershipRepository(g.db).remove(trip_id, user_id)
    return success({"deleted": True})
