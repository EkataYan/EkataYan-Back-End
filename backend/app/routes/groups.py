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
    return success(MembershipRepository(g.db).public_list(trip_id))


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
    require_trip(trip_id)
    MembershipRepository(g.db).remove_authorized(trip_id, user_id)
    return success({"deleted": True})


@bp.post("/trips/<trip_id>/leave")
@authenticated
def leave(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id)
    MembershipRepository(g.db).leave(trip_id)
    return success({"left": True})
