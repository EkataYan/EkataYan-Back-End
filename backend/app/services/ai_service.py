"""Gemini-backed, structured Sri Lanka itinerary generation."""
from datetime import datetime, timedelta
import json
import logging
import time

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.models.itinerary import (
    ActivityLocation, AiItineraryResponse, CostEstimate, CostRange, InitialItineraryResponse,
    ItineraryActivity, ItineraryDay, PlannerRequest, TripSummary,
)
from app.utils.responses import APIError

logger = logging.getLogger(__name__)


APPLICATION_ITINERARY_SCHEMA = AiItineraryResponse.model_json_schema()

INITIAL_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "trip": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "route": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "summary", "route"],
        },
        "days": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "day_number": {"type": "integer"},
                    "date": {"type": "string", "format": "date"},
                    "destination": {"type": "string"},
                    "title": {"type": "string"},
                    "activities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "location": {"type": "string"},
                                "start_time": {"type": "string", "format": "time"},
                                "duration_minutes": {"type": "integer", "minimum": 15, "maximum": 720},
                            },
                            "required": ["name", "location", "start_time", "duration_minutes"],
                        },
                    },
                },
                "required": ["day_number", "date", "destination", "title", "activities"],
            },
        },
        "cost_estimate": {
            "type": "object",
            "properties": {
                "total": {
                    "type": "object",
                    "properties": {
                        "min": {"type": "integer", "minimum": 0},
                        "max": {"type": "integer", "minimum": 0},
                    },
                    "required": ["min", "max"],
                },
            },
            "required": ["total"],
        },
    },
    "required": ["trip", "days", "cost_estimate"],
}

INITIAL_SYSTEM_INSTRUCTION = """You plan realistic Sri Lanka trips. Return only schema-valid JSON.
Respect the supplied dates and destination order. Account for real road/rail travel and meal breaks.
Keep the trip summary to one short sentence. Produce only the requested number of main activities:
Relaxed 2-3/day, Balanced 3-4/day, Packed 4-5/day. Do not output descriptions, coordinates,
transport metadata, recommendations, or detailed cost categories. Cost total is approximate group LKR."""

SYSTEM_INSTRUCTION = """You are the itinerary engine for EkataYan, a Sri Lankan travel planning application.
Generate realistic Sri Lankan travel itineraries using only the supplied trip preferences.
Return valid JSON matching the provided schema, with no markdown, code fences, or commentary.
Respect the exact trip dates and generate exactly one day object per inclusive trip day.
Account for realistic Sri Lankan road and rail travel, city-to-city transition time, generally known
opening hours, meal breaks, sensible activity durations, and the selected travel pace. Never create
geographically impossible schedules or overload a day. Preserve requested destination order when
reasonable; reorder only for a significant logistical improvement and explain that in recommendations.
Treat multiple destinations as one continuous route and allocate the overall dates intelligently.
Use selected transport preferences, accommodation preference, interests, and travel style. When an
optional preference is absent, make a sensible recommendation without claiming the user selected it.
Budget, Comfort, Premium, and Let AI decide influence accommodation, dining, transport convenience,
paid activities, and cost. There is no numeric user budget.
Coordinates must be null unless reliably known; do not fabricate precision. Prices are approximate,
not real-time. Every cost range and total is the TOTAL GROUP COST in LKR for all travellers. Include
the disclaimer that the estimate is AI-generated and actual prices may vary.
Use the requested destinations unless allow_ai_destination_suggestions is true. In suggestion mode,
choose a coherent Sri Lankan route based on duration, party, interests, style, transport, and pace.
"""


class AIService:
    def __init__(self, config, client_factory=None):
        self.model = config["GEMINI_MODEL"]
        timeout_ms = int(config.get("GEMINI_TIMEOUT_SECONDS", 60)) * 1000
        factory = client_factory or genai.Client
        self.client = factory(api_key=config["GEMINI_API_KEY"], http_options=types.HttpOptions(timeout=timeout_ms))

    def generate_itinerary(self, planner_data, modification=None):
        planner = planner_data if isinstance(planner_data, PlannerRequest) else PlannerRequest.model_validate(planner_data)
        if modification is None:
            return self._generate_initial_itinerary(planner)
        started = time.monotonic()
        logger.info("Gemini itinerary generation started destinations=%s duration_days=%s suggestion_mode=%s",
                    len(planner.destinations), planner.duration_days, planner.allow_ai_destination_suggestions)
        base_prompt = self._prompt(planner, modification)
        last_error = None
        for attempt in range(2):
            prompt = base_prompt if attempt == 0 else base_prompt + (
                "\nYour prior response failed application validation. Regenerate the complete itinerary as valid JSON "
                "matching the required schema exactly."
            )
            try:
                interaction = self.client.interactions.create(
                    model=self.model,
                    input=prompt,
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_format={"type": "text", "mime_type": "application/json"},
                    store=False,
                )
                logger.info("Gemini response received attempt=%s", attempt + 1)
                result = AiItineraryResponse.model_validate_json(interaction.output_text or "")
                result = self._enforce_deterministic_facts(result, planner)
                logger.info("Gemini itinerary parsed successfully attempt=%s duration_ms=%s", attempt + 1,
                            round((time.monotonic() - started) * 1000))
                return result
            except ValidationError as error:
                last_error = error
                issues = [
                    {"path": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
                    for item in error.errors(include_input=False, include_url=False)[:20]
                ]
                logger.warning("Gemini itinerary schema validation failed attempt=%s issues=%s",
                               attempt + 1, issues)
            except (TimeoutError, errors.ServerError) as error:
                logger.exception(
                    "Gemini SDK request unavailable source=gemini_sdk class=%s message=%s status=%s model=%s",
                    type(error).__name__, str(error),
                    getattr(error, "status_code", getattr(error, "code", None)), self.model,
                )
                if getattr(error, "code", None) in (408, 504) or isinstance(error, TimeoutError):
                    raise APIError("ai_timeout", "Itinerary generation took too long. Please try again.", 504) from None
                raise APIError("ai_unavailable", "AI itinerary generation is temporarily unavailable.", 503) from None
            except errors.APIError as error:
                logger.exception(
                    "Gemini SDK request failed source=gemini_sdk class=%s message=%s status=%s model=%s",
                    type(error).__name__, str(error),
                    getattr(error, "status_code", getattr(error, "code", None)), self.model,
                )
                raise APIError("ai_request_failed", "The AI itinerary request could not be processed.", 502) from None
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                last_error = error
                logger.warning("Gemini response parsing failed attempt=%s error_type=%s message=%s",
                               attempt + 1, type(error).__name__, str(error))
            except Exception as error:
                # Interactions/GAOS exceptions (including BadRequestError) are not
                # subclasses of google.genai.errors.APIError in google-genai 2.23.
                module = type(error).__module__
                if module.startswith("google.genai"):
                    status = getattr(error, "status_code", getattr(error, "code", None))
                    logger.exception(
                        "Gemini SDK request failed source=gemini_sdk class=%s message=%s status=%s model=%s",
                        type(error).__name__, str(error), status, self.model,
                    )
                    if status in (408, 504):
                        raise APIError("ai_timeout", "Itinerary generation took too long. Please try again.", 504) from None
                    if status == 400:
                        raise APIError("ai_request_failed", "The AI itinerary request could not be processed.", 502) from None
                    raise APIError("ai_unavailable", "AI itinerary generation is temporarily unavailable.", 503) from None
                raise
        logger.error("Gemini itinerary rejected after retry duration_ms=%s error_type=%s",
                     round((time.monotonic() - started) * 1000), type(last_error).__name__)
        raise APIError("ai_generation_failed", "We couldn't generate your itinerary.", 502)

    def _generate_initial_itinerary(self, planner):
        started = time.monotonic()
        prompt_started = time.monotonic()
        preferences = {
            "destinations": [item.name for item in planner.destinations],
            "allow_ai_destination_suggestions": planner.allow_ai_destination_suggestions,
            "traveller_type": planner.traveller_type,
            "traveller_count": planner.traveller_count,
            "start_date": str(planner.start_date),
            "end_date": str(planner.end_date),
            "duration_days": planner.duration_days,
            "transport": planner.transport_preferences,
            "accommodation": planner.accommodation_preference,
            "travel_style": planner.travel_style,
            "interests": planner.interests,
            "pace": planner.travel_pace or "Balanced",
            "special_requests": planner.special_requests,
        }
        preferences = {key: value for key, value in preferences.items() if value not in (None, "", [])}
        prompt = "Create the Stage 1 itinerary from these trip preferences:\n" + json.dumps(
            preferences, separators=(",", ":")
        )
        prompt_ms = round((time.monotonic() - prompt_started) * 1000)
        last_error = None
        for attempt in range(2):
            ai_started = time.monotonic()
            try:
                interaction = self.client.interactions.create(
                    model=self.model,
                    input=prompt if attempt == 0 else prompt + "\nRegenerate with exact dates, day count, and activity limits.",
                    system_instruction=INITIAL_SYSTEM_INSTRUCTION,
                    response_format={"type": "text", "mime_type": "application/json",
                                     "schema": INITIAL_RESPONSE_SCHEMA},
                    generation_config={"thinking_level": "low"},
                    store=False,
                )
                ai_ms = round((time.monotonic() - ai_started) * 1000)
                raw = interaction.output_text or ""
                json_started = time.monotonic()
                decoded = json.loads(raw)
                json_ms = round((time.monotonic() - json_started) * 1000)
                validation_started = time.monotonic()
                initial = InitialItineraryResponse.model_validate(decoded)
                validation_ms = round((time.monotonic() - validation_started) * 1000)
                normalize_started = time.monotonic()
                result = self._expand_initial_itinerary(initial, planner)
                normalize_ms = round((time.monotonic() - normalize_started) * 1000)
                usage = getattr(interaction, "usage", None)
                output_tokens = getattr(usage, "total_output_tokens", None)
                logger.info(
                    "AI stage1 timing model=%s attempt=%s prompt_ms=%s ai_request_ms=%s json_parse_ms=%s "
                    "schema_validation_ms=%s normalization_ms=%s total_ms=%s prompt_chars=%s response_bytes=%s output_tokens=%s",
                    self.model, attempt + 1, prompt_ms, ai_ms, json_ms, validation_ms, normalize_ms,
                    round((time.monotonic() - started) * 1000), len(prompt), len(raw.encode("utf-8")), output_tokens,
                )
                return result
            except (ValidationError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                last_error = error
                logger.warning("AI stage1 response rejected attempt=%s class=%s message=%s ai_request_ms=%s",
                               attempt + 1, type(error).__name__, str(error),
                               round((time.monotonic() - ai_started) * 1000))
            except Exception as error:
                self._raise_provider_error(error)
        logger.error("AI stage1 failed after retry class=%s total_ms=%s", type(last_error).__name__,
                     round((time.monotonic() - started) * 1000))
        raise APIError("ai_generation_failed", "We couldn't generate your itinerary.", 502)

    def _raise_provider_error(self, error):
        module = type(error).__module__
        if not module.startswith("google.genai") and not isinstance(error, TimeoutError):
            raise error
        status = getattr(error, "status_code", getattr(error, "code", None))
        logger.exception("Gemini SDK request failed source=gemini_sdk class=%s message=%s status=%s model=%s",
                         type(error).__name__, str(error), status, self.model)
        if status in (408, 504) or isinstance(error, TimeoutError):
            raise APIError("ai_timeout", "Itinerary generation took too long. Please try again.", 504) from None
        if status == 400:
            raise APIError("ai_request_failed", "The AI itinerary request could not be processed.", 502) from None
        raise APIError("ai_unavailable", "AI itinerary generation is temporarily unavailable.", 503) from None

    @staticmethod
    def _expand_initial_itinerary(initial, planner):
        if len(initial.days) != planner.duration_days:
            raise ValueError(f"incorrect day count: expected {planner.duration_days}, received {len(initial.days)}")
        limits = {"Relaxed": (2, 3), "Balanced": (3, 4), "Packed": (4, 5)}
        minimum, maximum = limits.get(planner.travel_pace or "Balanced", (3, 4))
        days = []
        per_day_min = initial.cost_estimate.total.min // planner.duration_days
        per_day_max = initial.cost_estimate.total.max // planner.duration_days
        for index, source_day in enumerate(initial.days, 1):
            if not minimum <= len(source_day.activities) <= maximum:
                raise ValueError(f"day {index} activity count must be {minimum}-{maximum}")
            activities = []
            for activity_index, source in enumerate(source_day.activities, 1):
                start = datetime.combine(planner.start_date, source.start_time)
                end = (start + timedelta(minutes=source.duration_minutes)).time()
                activities.append(ItineraryActivity(
                    id=f"day-{index}-activity-{activity_index}", name=source.name, category="Activity",
                    location=ActivityLocation(name=source.location), start_time=source.start_time, end_time=end,
                    duration_minutes=source.duration_minutes, description="", estimated_cost_lkr=0,
                    transport_from_previous="", travel_time_minutes=0,
                ))
            days.append(ItineraryDay(
                day_number=index, date=planner.start_date + timedelta(days=index - 1),
                destination=source_day.destination, title=source_day.title, summary=source_day.title,
                activities=activities, day_estimated_cost_lkr=CostRange(min=per_day_min, max=per_day_max),
            ))
        route = initial.trip.route
        if not planner.allow_ai_destination_suggestions:
            requested = [item.name for item in planner.destinations]
            requested_keys = {item.casefold() for item in requested}
            route = requested + [item for item in route if item.casefold() not in requested_keys]
        zero = CostRange(min=0, max=0)
        return AiItineraryResponse(
            trip=TripSummary(
                title=initial.trip.title, summary=initial.trip.summary, route=route,
                start_date=planner.start_date, end_date=planner.end_date, duration_days=planner.duration_days,
                traveller_type=planner.traveller_type, traveller_count=planner.traveller_count,
                travel_style=planner.travel_style or "Let AI decide", travel_pace=planner.travel_pace or "Balanced",
            ),
            days=days,
            cost_estimate=CostEstimate(
                accommodation=zero, transport=zero, food=zero, activities=zero,
                total=initial.cost_estimate.total,
                disclaimer="AI-generated total group estimate only. Actual prices may vary.",
            ),
            recommendations=[],
        )

    @staticmethod
    def _prompt(planner, modification):
        normalized = planner.model_dump(mode="json") | {"duration_days": planner.duration_days}
        prompt = (
            "Create one complete itinerary from this normalized planner request. The backend-calculated "
            "duration_days and supplied dates, traveller type, and traveller count are immutable. Activity IDs "
            "must be unique strings. Include inter-city transfers in transport_from_previous and "
            "travel_time_minutes. Every nested field in the response schema is required unless nullable.\n"
            "Required response JSON schema:\n"
            + json.dumps(APPLICATION_ITINERARY_SCHEMA, separators=(",", ":"))
            + "\nPlanner request:\n" + json.dumps(normalized, separators=(",", ":"))
        )
        if modification:
            prompt += "\nModify the supplied itinerary while preserving immutable facts:\n" + json.dumps(
                modification, separators=(",", ":"), default=str)
        return prompt

    @staticmethod
    def _enforce_deterministic_facts(result, planner):
        if len(result.days) != planner.duration_days:
            raise ValueError(
                f"incorrect day count: expected {planner.duration_days}, received {len(result.days)}"
            )
        for index, day in enumerate(result.days, 1):
            # These values are owned by the backend; normalize instead of
            # rejecting an otherwise useful itinerary when Gemini drifts.
            day.day_number = index
            day.date = planner.start_date + timedelta(days=index - 1)
        result.trip.start_date = planner.start_date
        result.trip.end_date = planner.end_date
        result.trip.duration_days = planner.duration_days
        result.trip.traveller_type = planner.traveller_type
        result.trip.traveller_count = planner.traveller_count
        if planner.travel_style and planner.travel_style != "Let AI decide":
            result.trip.travel_style = planner.travel_style
        if planner.travel_pace:
            result.trip.travel_pace = planner.travel_pace
        if not planner.allow_ai_destination_suggestions:
            requested = [destination.name for destination in planner.destinations]
            requested_keys = {item.casefold() for item in requested}
            extras = [name for name in result.trip.route if name.casefold() not in requested_keys]
            # Preserve the user's route and retain only additional AI stops.
            result.trip.route = requested + extras
        return result
