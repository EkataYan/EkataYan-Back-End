import json
import logging
import time

from flask import Blueprint, current_app, g, request
from pydantic import ValidationError

from app.middleware.auth_middleware import authenticated, require_trip
from app.models.itinerary import ModifyItineraryRequest, PlannedItinerarySave, PlannerRequest
from app.repositories import ItineraryRepository, TripRepository
from app.utils.responses import APIError, success
from app.utils.validators import GenerateInput, identifier, parse

bp = Blueprint("itineraries", __name__)
logger = logging.getLogger(__name__)


def _planner_payload(model=PlannerRequest):
    if not request.is_json:
        raise APIError("validation_error", "Content-Type must be application/json.", 415)
    try:
        payload = model.model_validate(request.get_json())
        if isinstance(payload, PlannerRequest):
            safe_payload = payload.model_dump(mode="json")
            special_requests = safe_payload.pop("special_requests", None)
            safe_payload["special_requests"] = {
                "present": bool(special_requests), "length": len(special_requests or "")
            }
            logger.info("Planner payload normalized source=flask_request_validation payload=%s",
                        json.dumps(safe_payload, separators=(",", ":")))
        return payload
    except ValidationError as error:
        locations = {str(item["loc"][0]) for item in error.errors() if item["loc"]}
        if "destinations" in locations or any("destination" in item["msg"].lower() for item in error.errors()):
            message = "Please select at least one destination."
        elif {"start_date", "end_date"} & locations or any("date" in item["msg"].lower() for item in error.errors()):
            message = "Trip dates are invalid."
        elif "traveller_count" in locations:
            message = "Traveller count must be greater than zero."
        elif "preferred_language" in locations:
            message = "Preferred language must be one of: en, si, ta."
        else:
            message = "Please check your trip information."
        logger.warning(
            "Planner validation failed source=flask_request_validation class=%s message=%s fields=%s",
            type(error).__name__, message, sorted(locations), exc_info=True,
        )
        raise APIError("validation_error", message, 400) from None


def _ai_service():
    service = current_app.extensions.get("ai_service")
    if service is None:
        raise APIError("ai_not_configured", "AI itinerary generation is currently unavailable.", 503)
    return service


def _persistence_payload(itinerary):
    structured = itinerary.model_dump(mode="json")
    return {
        "overview": itinerary.trip.summary, "currency": "LKR",
        "recommendations": itinerary.recommendations, "structured_data": structured,
        "days": [{"day_number": day.day_number, "date": str(day.date), "locations": [day.destination],
                  "notes": day.summary, "activities": [{
                      "title": activity.name, "location": activity.location.name,
                      "suggested_time": str(activity.start_time), "description": activity.description,
                      "estimated_cost": activity.estimated_cost_lkr,
                      "transport": activity.transport_from_previous,
                      "notes": f"Ends {activity.end_time}; {activity.duration_minutes} min; travel {activity.travel_time_minutes} min",
                      "latitude": activity.location.latitude, "longitude": activity.location.longitude,
                      "category": activity.category,
                  } for activity in day.activities]} for day in itinerary.days],
    }


@bp.post("/itineraries/preview")
@authenticated
def preview():
    request_started = time.monotonic()
    logger.info("Itinerary preview request received user_id=%s", g.user_id)
    service = _ai_service()
    parsing_started = time.monotonic()
    planner = _planner_payload()
    parsing_ms = round((time.monotonic() - parsing_started) * 1000)
    generation_started = time.monotonic()
    itinerary = service.generate_itinerary(planner)
    generation_ms = round((time.monotonic() - generation_started) * 1000)
    response_started = time.monotonic()
    response = success(itinerary.model_dump(mode="json"), 200)
    response_ms = round((time.monotonic() - response_started) * 1000)
    logger.info(
        "Itinerary preview timing request_parse_ms=%s generation_ms=%s backend_response_ms=%s total_ms=%s",
        parsing_ms, generation_ms, response_ms, round((time.monotonic() - request_started) * 1000),
    )
    return response


@bp.post("/itineraries/modify")
@authenticated
def modify():
    payload = _planner_payload(ModifyItineraryRequest)
    context = {
        "current_itinerary": payload.current_itinerary.model_dump(mode="json"),
        "instruction": payload.instruction,
        "target_day": payload.target_day,
    }
    itinerary = _ai_service().generate_itinerary(payload.trip_context, modification=context)
    return success(itinerary.model_dump(mode="json"), 200)


@bp.post("/itineraries/save")
@authenticated
def save_preview():
    payload = _planner_payload(PlannedItinerarySave)
    planner = payload.planner
    itinerary = payload.itinerary
    route = itinerary.trip.route
    trip_data = {
        "name": itinerary.trip.title,
        "destinations": route,
        "start_date": str(planner.start_date),
        "end_date": str(planner.end_date),
        "budget": itinerary.cost_estimate.total.max,
        "currency": "LKR",
        "travelers": planner.traveller_count,
        "interests": planner.interests,
        "preferred_activities": [],
        "travel_style": planner.travel_style or "Let AI decide",
        "accommodation_preference": planner.accommodation_preference or "Let AI decide",
        "transportation_preference": ", ".join(planner.transport_preferences) or "Let AI decide",
        "additional_requirements": planner.special_requests or "",
        "status": "planned",
        "planner_context": planner.model_dump(mode="json"),
        "created_by": g.user_id,
    }
    structured = itinerary.model_dump(mode="json")
    persistence = _persistence_payload(itinerary)
    repository = ItineraryRepository(g.db)
    saved = repository.save_ai_trip(trip_data, persistence)
    trip = saved["trip"]
    complete = repository.get(saved["itinerary_id"])
    return success({"trip": trip, "itinerary": complete, "structured_itinerary": structured}, 201)


@bp.post("/itineraries/generate")
@authenticated
def generate():
    """Retained for existing saved-trip clients; new Planner uses preview then save."""
    service = _ai_service()
    payload = parse(GenerateInput)
    trip_id = str(payload.trip_id)
    require_trip(trip_id, admin=True)
    traveller_type = "Solo" if payload.travelers == 1 else "Couple" if payload.travelers == 2 else "Group"
    planner = PlannerRequest(
        destinations=[{"name": name} for name in payload.destinations], traveller_type=traveller_type,
        traveller_count=payload.travelers, start_date=payload.start_date, end_date=payload.end_date,
        transport_preferences=[payload.transportation_preference] if payload.transportation_preference != "any" else [],
        accommodation_preference=payload.accommodation_preference,
        travel_style=payload.travel_style if payload.travel_style in {"Budget", "Comfort", "Premium", "Let AI decide"} else "Let AI decide",
        interests=payload.interests, special_requests=payload.additional_requirements,
    )
    itinerary = service.generate_itinerary(planner)
    repository = ItineraryRepository(g.db)
    saved = repository.save(trip_id, _persistence_payload(itinerary))
    return success(repository.get(saved["id"]), 201)


@bp.get("/trips/<trip_id>/itineraries")
@authenticated
def list_itineraries(trip_id):
    trip_id = identifier(trip_id)
    require_trip(trip_id)
    return success(ItineraryRepository(g.db).list(trip_id))
