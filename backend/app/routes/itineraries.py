from flask import Blueprint, current_app, g

from app.middleware.auth_middleware import authenticated, require_trip
from app.services.ai_service import AIService
from app.utils.responses import success
from app.utils.validators import GenerateInput, identifier, parse

bp = Blueprint("itineraries", __name__)


@bp.post("/itineraries/generate")
@authenticated
def generate():
    payload = parse(GenerateInput)
    trip_id = str(payload.trip_id)
    require_trip(trip_id, admin=True)
    itinerary = AIService(current_app.config).generate_itinerary(payload.model_dump())
    saved = g.db.rpc("save_itinerary", {"p_trip_id": trip_id, "p_data": itinerary})
    return success(saved, 201)


@bp.get("/trips/<trip_id>/itineraries")
@authenticated
def list_itineraries(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id)
    return success(g.db.select("itineraries", {"trip_id": trip_id}, select="*,itinerary_days(*,itinerary_activities(*))"))
