"""Gemini-backed, structured Sri Lanka itinerary generation."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
import logging
import re
import time

from google import genai
from google.genai import errors, types
import httpx
from pydantic import ValidationError

from app.models.itinerary import (
    ActivityLocation, AiItineraryResponse, CostEstimate, CostRange, InitialItineraryResponse,
    ItineraryActivity, ItineraryDay, PlannerRequest, TripSummary,
)
from app.utils.responses import APIError

logger = logging.getLogger(__name__)

LANGUAGE_NAMES = {"en": "English", "si": "Sinhala", "ta": "Tamil"}


class ItineraryContractError(ValueError):
    """A schema-valid provider response that violates planner-specific rules."""

    def __init__(self, field, reason, expected, received):
        super().__init__(reason)
        self.field = field
        self.reason = reason
        self.expected = expected
        self.received = received


APPLICATION_ITINERARY_SCHEMA = AiItineraryResponse.model_json_schema()

INITIAL_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "trip": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "route": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "summary", "route"],
        },
        "days": {
            "type": "array",
            "minItems": 1,
            "maxItems": 30,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "day_number": {"type": "integer"},
                    "date": {"type": "string", "format": "date"},
                    "destination": {"type": "string"},
                    "title": {"type": "string"},
                    "activities": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 5,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
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
            "additionalProperties": False,
            "properties": {
                "total": {
                    "type": "object",
                    "additionalProperties": False,
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
    "additionalProperties": False,
}

INITIAL_SYSTEM_INSTRUCTION = """You are the itinerary engine for EkataYan and an expert Sri Lanka travel planner.
Return only data matching the required JSON schema, with no markdown, code fences, or commentary.
Create practical, realistic Sri Lankan itineraries. Respect the exact dates, duration, traveller count and type,
budget tier, interests, transport preferences, accommodation preference, and optional user requests. Treat
multiple destinations as one coherent route, preserve their order when practical, group nearby attractions,
and allow realistic road or rail transfers, opening hours, meals, and rest. Avoid impossible schedules,
excessive activities, generic filler, and obviously nonexistent places. Keep the trip summary to one short
sentence. Produce only the requested number of main activities: Relaxed 2-3/day, Balanced 3-4/day, Packed
4-5/day. Do not output fields outside the schema. Cost total is an approximate total group cost in LKR."""

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
        self.provider = config.get("AI_PROVIDER", "gemini").strip().lower()
        if self.provider != "gemini":
            raise ValueError(f"Unsupported AI provider: {self.provider}")
        self.model = config.get("AI_MODEL", "gemini-3.5-flash-lite")
        self.api_key = config["GEMINI_API_KEY"]
        timeout_seconds = float(config.get("AI_TIMEOUT_SECONDS", 60))
        factory = client_factory or genai.Client
        self.client = factory(
            api_key=self.api_key,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    def generate_itinerary(self, planner_data, modification=None):
        planner = planner_data if isinstance(planner_data, PlannerRequest) else PlannerRequest.model_validate(planner_data)
        if modification is None:
            return self._generate_initial_itinerary(planner)
        started = time.monotonic()
        logger.info("AI itinerary request started provider=%s model=%s mode=modify duration_days=%s",
                    self.provider, self.model, planner.duration_days)
        raw, _usage = self._request_structured(
            self._prompt(planner, modification), SYSTEM_INSTRUCTION, APPLICATION_ITINERARY_SCHEMA
        )
        try:
            result = AiItineraryResponse.model_validate_json(raw)
            result = self._enforce_deterministic_facts(result, planner)
        except (ValidationError, ValueError, TypeError) as error:
            self._raise_validation_error(error, started, "modify")
        logger.info("AI itinerary succeeded provider=%s model=%s mode=modify duration_ms=%s",
                    self.provider, self.model, round((time.monotonic() - started) * 1000))
        return result

    def _generate_initial_itinerary(self, planner):
        started = time.monotonic()
        logger.info("AI itinerary request started provider=%s model=%s mode=preview duration_days=%s",
                    self.provider, self.model, planner.duration_days)
        prompt_started = time.monotonic()
        prompt = self._initial_prompt(planner)
        prompt_ms = round((time.monotonic() - prompt_started) * 1000)
        ai_started = time.monotonic()
        response_schema = self._preview_schema(planner)
        raw, usage = self._request_structured(prompt, INITIAL_SYSTEM_INSTRUCTION, response_schema)
        ai_ms = round((time.monotonic() - ai_started) * 1000)
        json_started = time.monotonic()
        decoded = None
        structure = None
        try:
            decoded = json.loads(raw)
            json_ms = round((time.monotonic() - json_started) * 1000)
            structure = self._response_structure(decoded, response_schema)
            logger.info(
                "AI structured response received provider=%s model=%s mode=preview structure=%s",
                self.provider, self.model, structure,
            )
            validation_started = time.monotonic()
            initial = InitialItineraryResponse.model_validate(decoded)
            validation_ms = round((time.monotonic() - validation_started) * 1000)
            normalize_started = time.monotonic()
            result = self._expand_initial_itinerary(initial, planner)
            normalize_ms = round((time.monotonic() - normalize_started) * 1000)
        except (ValidationError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            self._raise_validation_error(error, started, "preview", structure)
        output_tokens = getattr(usage, "candidates_token_count", None)
        logger.info(
            "AI itinerary succeeded provider=%s model=%s mode=preview prompt_ms=%s ai_request_ms=%s "
            "json_parse_ms=%s schema_validation_ms=%s normalization_ms=%s total_ms=%s "
            "prompt_chars=%s response_bytes=%s output_tokens=%s",
            self.provider, self.model, prompt_ms, ai_ms, json_ms, validation_ms, normalize_ms,
            round((time.monotonic() - started) * 1000), len(prompt), len(raw.encode("utf-8")), output_tokens,
        )
        return result

    def _request_structured(self, prompt, instruction, schema):
        request_started = time.monotonic()
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=instruction,
                    response_mime_type="application/json",
                    response_json_schema=schema,
                ),
            )
        except (errors.APIError, TimeoutError, httpx.RequestError) as error:
            self._raise_provider_error(error, request_started)
        raw = response.text or ""
        if not raw.strip():
            logger.warning("AI provider returned empty output provider=%s model=%s duration_ms=%s",
                           self.provider, self.model,
                           round((time.monotonic() - request_started) * 1000))
            raise APIError("ai_generation_failed", "We couldn't generate your itinerary.", 502)
        logger.info("AI provider response received provider=%s model=%s duration_ms=%s",
                    self.provider, self.model, round((time.monotonic() - request_started) * 1000))
        return raw, getattr(response, "usage_metadata", None)

    def _raise_provider_error(self, error, request_started):
        status = getattr(error, "status_code", getattr(error, "code", None))
        message = getattr(error, "message", None) or str(error)
        message = message.replace(self.api_key, "<redacted>") if self.api_key else message
        message = re.sub(r"(?i)bearer\s+\S+", "Bearer <redacted>", message)[:1000]
        logger.warning(
            "AI provider request failed provider=%s model=%s status=%s class=%s duration_ms=%s message=%s",
            self.provider, self.model, status, type(error).__name__,
            round((time.monotonic() - request_started) * 1000), message,
        )
        if isinstance(error, (TimeoutError, httpx.TimeoutException)) or status in (408, 504):
            raise APIError("ai_timeout", "Itinerary generation took too long. Please try again.", 504) from None
        if status == 400:
            raise APIError("ai_request_failed", "The AI itinerary request could not be processed.", 502) from None
        if status in (401, 403):
            raise APIError("ai_authentication_failed", "AI itinerary generation authentication failed.", 502) from None
        if status == 429:
            raise APIError("ai_rate_limited", "AI itinerary generation quota was exceeded. Please try again later.", 429) from None
        if isinstance(status, int) and status >= 500:
            raise APIError("ai_unavailable", "AI itinerary generation is temporarily unavailable.", 503) from None
        raise APIError("ai_unavailable", "AI itinerary generation is temporarily unavailable.", 503) from None

    def _raise_validation_error(self, error, started, mode, structure=None):
        issues = []
        if isinstance(error, ValidationError):
            issues = [
                {
                    "field": self._format_validation_path(item["loc"]),
                    "reason": item["msg"],
                    "type": item["type"],
                }
                for item in error.errors(include_input=False, include_url=False)[:20]
            ]
        elif isinstance(error, ItineraryContractError):
            issues = [{
                "field": error.field,
                "reason": error.reason,
                "expected": error.expected,
                "received": error.received,
            }]
        else:
            issues = [{
                "field": "$",
                "reason": str(error)[:500] or type(error).__name__,
                "type": type(error).__name__,
            }]
        primary = issues[0]
        logger.warning(
            "AI response validation failed provider=%s model=%s mode=%s class=%s duration_ms=%s "
            "field=%s reason=%s expected=%s received=%s issues=%s structure=%s",
            self.provider, self.model, mode, type(error).__name__,
            round((time.monotonic() - started) * 1000), primary.get("field"), primary.get("reason"),
            primary.get("expected"), primary.get("received"), issues, structure,
        )
        raise APIError("ai_generation_failed", "We couldn't generate your itinerary.", 502) from None

    @staticmethod
    def _format_validation_path(location):
        path = ""
        for part in location:
            if isinstance(part, int):
                path += f"[{part}]"
            else:
                path += ("." if path else "") + str(part)
        return path or "$"

    @staticmethod
    def _response_structure(decoded, schema):
        expected_keys = sorted(schema.get("required", []))
        if not isinstance(decoded, dict):
            return {"root_type": type(decoded).__name__, "expected_root_type": "object"}
        returned_keys = sorted(str(key) for key in decoded)
        days = decoded.get("days")
        activity_counts = []
        if isinstance(days, list):
            activity_counts = [
                len(day.get("activities", [])) if isinstance(day, dict) and isinstance(day.get("activities"), list)
                else None
                for day in days[:30]
            ]
        return {
            "root_type": "object",
            "top_level_keys": returned_keys,
            "expected_top_level_keys": expected_keys,
            "missing_top_level_keys": sorted(set(expected_keys) - set(returned_keys)),
            "unexpected_top_level_keys": sorted(set(returned_keys) - set(schema.get("properties", {}))),
            "field_types": {key: type(decoded[key]).__name__ for key in returned_keys},
            "day_count": len(days) if isinstance(days, list) else None,
            "activity_counts": activity_counts,
        }

    @staticmethod
    def _initial_prompt(planner):
        preferences = {
            "destinations": [item.model_dump(mode="json", exclude_none=True) for item in planner.destinations],
            "allow_ai_destination_suggestions": planner.allow_ai_destination_suggestions,
            "suggest_additional_places": planner.suggest_additional_places,
            "traveller_type": planner.traveller_type,
            "traveller_count": planner.traveller_count,
            "start_date": str(planner.start_date),
            "end_date": str(planner.end_date),
            "duration_days": planner.duration_days,
            "transport_preferences": planner.transport_preferences,
            "accommodation_preference": planner.accommodation_preference,
            "travel_style": planner.travel_style,
            "interests": planner.interests,
            "travel_pace": planner.travel_pace or "Balanced",
            "special_requests": planner.special_requests,
            "preferred_language": planner.preferred_language,
        }
        preferences = {key: value for key, value in preferences.items() if value not in (None, "", [])}
        language_name = LANGUAGE_NAMES[planner.preferred_language]
        prompt = (
            "Create the Stage 1 itinerary from these trip preferences. Write all human-readable itinerary "
            f"content in {language_name}. Keep JSON property names unchanged and preserve Sri Lankan place "
            "names unless a standard localized name is appropriate.\n"
            + json.dumps(preferences, separators=(",", ":"))
        )
        return prompt

    @staticmethod
    def _activity_limits(planner):
        return {"Relaxed": (2, 3), "Balanced": (3, 4), "Packed": (4, 5)}.get(
            planner.travel_pace or "Balanced", (3, 4)
        )

    @classmethod
    def _preview_schema(cls, planner):
        """Apply planner-specific invariants to Gemini's supported JSON Schema subset."""
        schema = deepcopy(INITIAL_RESPONSE_SCHEMA)
        days = schema["properties"]["days"]
        days["minItems"] = planner.duration_days
        days["maxItems"] = planner.duration_days
        minimum, maximum = cls._activity_limits(planner)
        activities = days["items"]["properties"]["activities"]
        activities["minItems"] = minimum
        activities["maxItems"] = maximum
        return schema

    @staticmethod
    def _expand_initial_itinerary(initial, planner):
        if len(initial.days) != planner.duration_days:
            raise ItineraryContractError(
                "days", "incorrect day count", planner.duration_days, len(initial.days)
            )
        minimum, maximum = AIService._activity_limits(planner)
        days = []
        per_day_min = initial.cost_estimate.total.min // planner.duration_days
        per_day_max = initial.cost_estimate.total.max // planner.duration_days
        for index, source_day in enumerate(initial.days, 1):
            if not minimum <= len(source_day.activities) <= maximum:
                raise ItineraryContractError(
                    f"days[{index - 1}].activities", "activity count outside travel-pace limits",
                    f"{minimum}-{maximum}", len(source_day.activities),
                )
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
        language_name = LANGUAGE_NAMES[planner.preferred_language]
        prompt = (
            "Create one complete itinerary from this normalized planner request. The backend-calculated "
            "duration_days and supplied dates, traveller type, and traveller count are immutable. Activity IDs "
            "must be unique strings. Include inter-city transfers in transport_from_previous and "
            "travel_time_minutes. Every nested field in the response schema is required unless nullable. "
            f"Write all human-readable itinerary content in {language_name}; keep JSON property names unchanged "
            "and preserve Sri Lankan place names unless a standard localized name is appropriate.\n"
            "Return only the structured response requested by the provider configuration.\n"
            "Planner request:\n" + json.dumps(normalized, separators=(",", ":"))
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
            # rejecting an otherwise useful itinerary when the model drifts.
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
