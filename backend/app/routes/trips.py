from flask import Blueprint, g
from app.middleware.auth_middleware import authenticated, require_trip
from app.utils.responses import success
from app.utils.validators import TripInput, identifier, pagination, parse

bp = Blueprint("trips", __name__)


@bp.post("/trips")
@authenticated
def create():
    data = parse(TripInput).model_dump(mode="json")
    data["created_by"] = g.user_id
    return success(g.db.insert("trips", data), 201)


@bp.get("/trips")
@authenticated
def list_trips():
    page = pagination()
    return success(g.db.select("trips", **page), pagination=page)


@bp.get("/trips/<trip_id>")
@authenticated
def get_trip(trip_id):
    return success(require_trip(identifier(trip_id)))


@bp.put("/trips/<trip_id>")
@authenticated
def update_trip(trip_id):
    trip_id = identifier(trip_id)
    data = parse(TripInput).model_dump(mode="json")
    require_trip(trip_id, admin=True)
    return success(g.db.update("trips", {"id": trip_id}, data))


@bp.delete("/trips/<trip_id>")
@authenticated
def delete_trip(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id, owner=True)
    g.db.delete("trips", {"id": trip_id})
    return success({"deleted": True})
