"""xAI Grok-backed, structured Sri Lanka itinerary generation."""
from datetime import datetime, timedelta
import json
import logging
import time

import httpx
from pydantic import ValidationError

from app.models.itinerary import (
    ActivityLocation, AiItineraryResponse, CostEstimate, CostRange, InitialItineraryResponse,
    ItineraryActivity, ItineraryDay, PlannerRequest, TripSummary,
)
from app.utils.responses import APIError

logger = logging.getLogger(__name__)

LANGUAGE_NAMES = {"en": "English", "si": "Sinhala", "ta": "Tamil"}
XAI_RESPONSES_URL = "https://api.x.ai/v1/responses"


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
        self.provider = config.get("AI_PROVIDER", "grok").strip().lower()
        if self.provider != "grok":
            raise ValueError(f"Unsupported AI provider: {self.provider}")
        self.model = config.get("AI_MODEL", "grok-4.6")
        self.api_key = config["XAI_API_KEY"]
        timeout_seconds = float(config.get("AI_TIMEOUT_SECONDS", 60))
        factory = client_factory or httpx.Client
        self.client = factory(timeout=httpx.Timeout(timeout_seconds))

    def generate_itinerary(self, planner_data, modification=None):
        planner = planner_data if isinstance(planner_data, PlannerRequest) else PlannerRequest.model_validate(planner_data)
        if modification is None:
            return self._generate_initial_itinerary(planner)
        started = time.monotonic()
        logger.info("AI itinerary request started provider=%s model=%s mode=modify duration_days=%s",
                    self.provider, self.model, planner.duration_days)
        base_prompt = self._prompt(planner, modification)
        last_error = None
        for attempt in range(2):
            prompt = base_prompt if attempt == 0 else base_prompt + (
                "\nYour prior response failed application validation. Regenerate the complete itinerary as valid JSON "
                "matching the required schema exactly."
            )
            try:
                raw, _usage = self._request_structured(
                    prompt, SYSTEM_INSTRUCTION, APPLICATION_ITINERARY_SCHEMA, "ekatayan_itinerary"
                )
                result = AiItineraryResponse.model_validate_json(raw)
                result = self._enforce_deterministic_facts(result, planner)
                logger.info("AI itinerary succeeded provider=%s model=%s attempt=%s duration_ms=%s",
                            self.provider, self.model, attempt + 1,
                            round((time.monotonic() - started) * 1000))
                return result
            except ValidationError as error:
                last_error = error
                issues = [
                    {"path": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
                    for item in error.errors(include_input=False, include_url=False)[:20]
                ]
                logger.warning("AI itinerary validation failed provider=%s model=%s attempt=%s issues=%s",
                               self.provider, self.model, attempt + 1, issues)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                last_error = error
                logger.warning("AI response parsing failed provider=%s model=%s attempt=%s error_type=%s",
                               self.provider, self.model, attempt + 1, type(error).__name__)
        logger.error("AI itinerary rejected after retry provider=%s model=%s duration_ms=%s error_type=%s",
                     self.provider, self.model, round((time.monotonic() - started) * 1000),
                     type(last_error).__name__)
        raise APIError("ai_generation_failed", "We couldn't generate your itinerary.", 502)

    def _generate_initial_itinerary(self, planner):
        started = time.monotonic()
        logger.info("AI itinerary request started provider=%s model=%s mode=preview duration_days=%s",
                    self.provider, self.model, planner.duration_days)
        prompt_started = time.monotonic()
        prompt = self._initial_prompt(planner)
        prompt_ms = round((time.monotonic() - prompt_started) * 1000)
        last_error = None
        for attempt in range(2):
            ai_started = time.monotonic()
            try:
                raw, usage = self._request_structured(
                    prompt if attempt == 0 else prompt + (
                        "\nYour prior response was invalid. Regenerate the complete JSON with exact dates, "
                        "day count, and activity limits."
                    ),
                    INITIAL_SYSTEM_INSTRUCTION,
                    INITIAL_RESPONSE_SCHEMA,
                    "ekatayan_itinerary_preview",
                )
                ai_ms = round((time.monotonic() - ai_started) * 1000)
                json_started = time.monotonic()
                decoded = json.loads(raw)
                json_ms = round((time.monotonic() - json_started) * 1000)
                validation_started = time.monotonic()
                initial = InitialItineraryResponse.model_validate(decoded)
                validation_ms = round((time.monotonic() - validation_started) * 1000)
                normalize_started = time.monotonic()
                result = self._expand_initial_itinerary(initial, planner)
                normalize_ms = round((time.monotonic() - normalize_started) * 1000)
                output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
                logger.info(
                    "AI itinerary succeeded provider=%s model=%s mode=preview attempt=%s prompt_ms=%s ai_request_ms=%s json_parse_ms=%s "
                    "schema_validation_ms=%s normalization_ms=%s total_ms=%s prompt_chars=%s response_bytes=%s output_tokens=%s",
                    self.provider, self.model, attempt + 1, prompt_ms, ai_ms, json_ms, validation_ms, normalize_ms,
                    round((time.monotonic() - started) * 1000), len(prompt), len(raw.encode("utf-8")), output_tokens,
                )
                return result
            except (ValidationError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                last_error = error
                logger.warning("AI response validation failed provider=%s model=%s mode=preview attempt=%s class=%s ai_request_ms=%s",
                               self.provider, self.model, attempt + 1, type(error).__name__,
                               round((time.monotonic() - ai_started) * 1000))
        logger.error("AI preview failed after retry provider=%s model=%s class=%s total_ms=%s",
                     self.provider, self.model, type(last_error).__name__,
                     round((time.monotonic() - started) * 1000))
        raise APIError("ai_generation_failed", "We couldn't generate your itinerary.", 502)

    def _request_structured(self, prompt, instruction, schema, schema_name):
        payload = {
            "model": self.model,
            "instructions": instruction,
            "input": prompt,
            "text": {"format": {
                "type": "json_schema", "name": schema_name, "schema": schema, "strict": True,
            }},
        }
        request_started = time.monotonic()
        try:
            response = self.client.post(
                XAI_RESPONSES_URL,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        except httpx.TimeoutException:
            logger.warning("AI request timed out provider=%s model=%s duration_ms=%s", self.provider,
                           self.model, round((time.monotonic() - request_started) * 1000))
            raise APIError("ai_timeout", "Itinerary generation took too long. Please try again.", 504) from None
        except httpx.RequestError as error:
            logger.warning("AI network request failed provider=%s model=%s class=%s duration_ms=%s",
                           self.provider, self.model, type(error).__name__,
                           round((time.monotonic() - request_started) * 1000))
            raise APIError("ai_unavailable", "AI itinerary generation is temporarily unavailable.", 503) from None

        duration_ms = round((time.monotonic() - request_started) * 1000)
        logger.info("AI response received provider=%s model=%s status=%s duration_ms=%s",
                    self.provider, self.model, response.status_code, duration_ms)
        self._raise_http_error(response.status_code, duration_ms)
        try:
            data = response.json()
        except ValueError as error:
            raise ValueError("xAI returned an invalid response envelope") from error
        raw = self._extract_output_text(data)
        if not raw.strip():
            raise ValueError("xAI returned an empty response")
        return raw, data.get("usage", {})

    def _raise_http_error(self, status, duration_ms):
        if status < 400:
            return
        logger.warning("AI provider request failed provider=%s model=%s status=%s duration_ms=%s",
                       self.provider, self.model, status, duration_ms)
        if status in (401, 403):
            raise APIError("ai_authentication_failed", "AI itinerary generation authentication failed.", 502)
        if status == 429:
            raise APIError("ai_rate_limited", "AI itinerary generation is busy. Please try again shortly.", 429)
        if status in (408, 504):
            raise APIError("ai_timeout", "Itinerary generation took too long. Please try again.", 504)
        if status in (404, 422):
            raise APIError("ai_model_unavailable", "The configured AI model is unavailable.", 503)
        if status >= 500:
            raise APIError("ai_unavailable", "AI itinerary generation is temporarily unavailable.", 503)
        raise APIError("ai_request_failed", "The AI itinerary request could not be processed.", 502)

    @staticmethod
    def _extract_output_text(data):
        if isinstance(data.get("output_text"), str):
            return data["output_text"]
        parts = []
        for output in data.get("output", []):
            if not isinstance(output, dict) or output.get("type") != "message":
                continue
            for content in output.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    parts.append(content["text"])
        return "".join(parts)

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
        language_name = LANGUAGE_NAMES[planner.preferred_language]
        prompt = (
            "Create one complete itinerary from this normalized planner request. The backend-calculated "
            "duration_days and supplied dates, traveller type, and traveller count are immutable. Activity IDs "
            "must be unique strings. Include inter-city transfers in transport_from_previous and "
            "travel_time_minutes. Every nested field in the response schema is required unless nullable. "
            f"Write all human-readable itinerary content in {language_name}; keep JSON property names unchanged "
            "and preserve Sri Lankan place names unless a standard localized name is appropriate.\n"
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
