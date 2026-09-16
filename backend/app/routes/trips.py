import logging

from flask import Blueprint, g
from app.middleware.auth_middleware import authenticated, require_trip
from app.repositories import ItineraryRepository, TripRepository
from app.utils.responses import success
from app.utils.validators import BudgetInput, TripInput, identifier, pagination, parse

bp = Blueprint("trips", __name__)
logger = logging.getLogger(__name__)


@bp.post("/trips")
@authenticated
def create():
    data = parse(TripInput).model_dump(mode="json")
    data["created_by"] = g.user_id
    trip = TripRepository(g.db).create(data)
    return success(trip | {"can_delete": True}, 201)


@bp.get("/trips")
@authenticated
def list_trips():
    page = pagination()
    trips = TripRepository(g.db).list(page)
    # Deleting a shared trip is owner-only. Expose that server-derived capability
    # so the client can offer members the existing leave flow instead of sending
    # a guaranteed-forbidden DELETE request.
    visible_trips = [trip | {"can_delete": trip["created_by"] == g.user_id} for trip in trips]
    return success(visible_trips, pagination=page)


@bp.get("/trips/<trip_id>")
@authenticated
def get_trip(trip_id):
    return success(require_trip(identifier(trip_id)))


@bp.get("/trips/<trip_id>/details")
@authenticated
def get_trip_details(trip_id):
    trip_id = identifier(trip_id)
    logger.info("Trip details request trip_id=%s authenticated_user_id=%s", trip_id, g.user_id)
    trip = require_trip(trip_id)
    itineraries = ItineraryRepository(g.db).list(trip_id)
    itinerary = itineraries[0] if itineraries else None
    structured = itinerary.get("structured_data") if itinerary else None
    logger.info("Trip details response trip_id=%s authenticated_user_id=%s itinerary_found=%s",
                trip_id, g.user_id, itinerary is not None)
    return success({"trip": trip, "itinerary": itinerary, "structured_itinerary": structured})


@bp.put("/trips/<trip_id>")
@authenticated
def update_trip(trip_id):
    trip_id = identifier(trip_id)
    data = parse(TripInput).model_dump(mode="json")
    require_trip(trip_id, admin=True)
    return success(TripRepository(g.db).update(trip_id, data))


@bp.delete("/trips/<trip_id>")
@authenticated
def delete_trip(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id, owner=True)
    TripRepository(g.db).delete(trip_id)
    return success({"deleted": True})


@bp.patch("/trips/<trip_id>/budget")
@authenticated
def set_budget(trip_id):
    trip_id = identifier(trip_id)
    data = parse(BudgetInput, error_status=400)
    require_trip(trip_id, admin=True)
    return success(TripRepository(g.db).set_budget(trip_id, str(data.budget_amount)))
