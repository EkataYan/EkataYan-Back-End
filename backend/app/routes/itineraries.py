from flask import Blueprint, current_app, g

from app.middleware.auth_middleware import authenticated, require_trip
from app.utils.responses import APIError, success
from app.utils.validators import GenerateInput, identifier, parse

bp = Blueprint("itineraries", __name__)


@bp.post("/itineraries/generate")
@authenticated
def generate():
    ai_service = current_app.extensions.get("ai_service")
    if ai_service is None:
        raise APIError("AI_NOT_CONFIGURED", "AI service is not configured", 503)
    payload = parse(GenerateInput)
    trip_id = str(payload.trip_id)
    require_trip(trip_id, admin=True)
    itinerary = ai_service.generate_itinerary(payload.model_dump())
    saved = g.db.rpc("save_itinerary", {"p_trip_id": trip_id, "p_data": itinerary})
    # The RPC is transactional but returns only the parent row. Return the complete persisted
    # graph so clients render database-authoritative data rather than the provider response.
    complete = g.db.one("itineraries", {"id": saved["id"]},
                        select="*,itinerary_days(*,itinerary_activities(*))")
    return success(complete, 201)


@bp.get("/trips/<trip_id>/itineraries")
@authenticated
def list_itineraries(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id)
    return success(g.db.select("itineraries", {"trip_id": trip_id}, select="*,itinerary_days(*,itinerary_activities(*))"))
