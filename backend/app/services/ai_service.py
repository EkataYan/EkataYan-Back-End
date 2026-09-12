"""Gemini-backed, structured Sri Lanka itinerary generation."""
from datetime import timedelta
import json
import logging
import time

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.models.itinerary import AiItineraryResponse, PlannerRequest
from app.utils.responses import APIError

logger = logging.getLogger(__name__)

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
                    response_format={"type": "text", "mime_type": "application/json",
                                     "schema": AiItineraryResponse.model_json_schema()},
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
                logger.warning("Gemini itinerary schema validation failed attempt=%s", attempt + 1)
            except (TimeoutError, errors.ServerError) as error:
                logger.warning("Gemini request unavailable error_type=%s", type(error).__name__)
                if getattr(error, "code", None) in (408, 504) or isinstance(error, TimeoutError):
                    raise APIError("ai_timeout", "Itinerary generation took too long. Please try again.", 504) from None
                raise APIError("ai_unavailable", "AI itinerary generation is temporarily unavailable.", 503) from None
            except errors.APIError as error:
                logger.warning("Gemini request failed status=%s", getattr(error, "code", None))
                raise APIError("ai_generation_failed", "We couldn't generate your itinerary.", 502) from None
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                last_error = error
                logger.warning("Gemini response parsing failed attempt=%s error_type=%s", attempt + 1, type(error).__name__)
        logger.error("Gemini itinerary rejected after retry duration_ms=%s error_type=%s",
                     round((time.monotonic() - started) * 1000), type(last_error).__name__)
        raise APIError("ai_generation_failed", "We couldn't generate your itinerary.", 502)

    @staticmethod
    def _prompt(planner, modification):
        normalized = planner.model_dump(mode="json") | {"duration_days": planner.duration_days}
        prompt = (
            "Create one complete itinerary from this normalized planner request. The backend-calculated "
            "duration_days and supplied dates, traveller type, and traveller count are immutable. Activity IDs "
            "must be unique strings. Include inter-city transfers in transport_from_previous and "
            "travel_time_minutes.\nPlanner request:\n" + json.dumps(normalized, separators=(",", ":"))
        )
        if modification:
            prompt += "\nModify the supplied itinerary while preserving immutable facts:\n" + json.dumps(
                modification, separators=(",", ":"), default=str)
        return prompt

    @staticmethod
    def _enforce_deterministic_facts(result, planner):
        if len(result.days) != planner.duration_days:
            raise ValueError("incorrect day count")
        for index, day in enumerate(result.days, 1):
            if day.day_number != index or day.date != planner.start_date + timedelta(days=index - 1):
                raise ValueError("incorrect itinerary dates")
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
            if not all(name in result.trip.route for name in requested):
                raise ValueError("requested destination missing from route")
        return result
