"""Provider-neutral itinerary generation service."""
import json
import logging

import httpx

from app.utils.responses import APIError
from app.utils.validators import ItineraryResult

logger = logging.getLogger(__name__)


def _gemini_itinerary_schema():
    """Compact generation schema; ItineraryResult remains the authoritative validator."""
    activity = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "location": {"type": "string"},
            "suggested_time": {"type": "string", "format": "time"},
            "description": {"type": "string"},
            "estimated_cost": {"type": "number", "minimum": 0},
            "transport": {"type": "string"},
            "notes": {"type": "string"},
            "category": {"type": "string"},
        },
        "required": [
            "title", "location", "suggested_time", "description",
            "estimated_cost", "transport", "notes", "category",
        ],
        "additionalProperties": False,
    }
    day = {
        "type": "object",
        "properties": {
            "day_number": {"type": "integer", "minimum": 1, "maximum": 30},
            "date": {"type": "string", "format": "date"},
            "locations": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20},
            "activities": {"type": "array", "items": activity, "minItems": 1, "maxItems": 15},
            "notes": {"type": "string"},
        },
        "required": ["day_number", "date", "locations", "activities", "notes"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "overview": {"type": "string"},
            "currency": {"type": "string", "enum": ["LKR", "USD", "EUR", "GBP", "INR", "AUD"]},
            "days": {"type": "array", "items": day, "minItems": 1, "maxItems": 30},
            "recommendations": {"type": "array", "items": {"type": "string"}, "maxItems": 30},
        },
        "required": ["overview", "currency", "days", "recommendations"],
        "additionalProperties": False,
    }


def _gemini_endpoint(base_url):
    base = base_url.rstrip("/")
    if base.endswith("/openai"):
        base = base[:-len("/openai")]
    return base + "/interactions"


def _gemini_output_text(data):
    if data.get("status") != "completed":
        raise ValueError("Gemini interaction did not complete")
    for step in reversed(data.get("steps", [])):
        if step.get("type") == "model_output":
            parts = [part.get("text", "") for part in step.get("content", []) if part.get("type") == "text"]
            if parts:
                return "".join(parts)
    raise ValueError("Gemini interaction had no text output")


class AIService:
    def __init__(self, config):
        self.config = config

    def generate_itinerary(self, request_data):
        if not self.config.get("AI_API_KEY") or not self.config.get("AI_BASE_URL") or not self.config.get("AI_MODEL"):
            raise APIError("AI_NOT_CONFIGURED", "AI itinerary generation is not configured yet.", 503)
        if self.config.get("AI_PROVIDER", "openai_compatible") not in ("", "openai_compatible", "gemini"):
            raise APIError("AI_PROVIDER_UNSUPPORTED", "The configured AI provider is not supported.", 503)
        provider = self.config.get("AI_PROVIDER", "openai_compatible")
        schema = ItineraryResult.model_json_schema()
        prompt = (
            "Create a practical Sri Lankan travel itinerary. Respect dates, budget, traveller count, "
            "preferences and travel times. Costs must be non-negative estimates in the requested currency. "
            "Return only JSON matching the supplied schema.\nInput:\n" + json.dumps(request_data, default=str)
        )
        try:
            if provider == "gemini":
                gemini_prompt = prompt + "\nOutput JSON schema:\n" + json.dumps(_gemini_itinerary_schema())
                body = {
                    "model": self.config["AI_MODEL"],
                    "input": gemini_prompt,
                    "system_instruction": "You are a careful Sri Lanka trip planner.",
                    "response_format": {
                        "type": "text",
                        "mime_type": "application/json",
                    },
                    "store": False,
                }
                response = httpx.post(
                    _gemini_endpoint(self.config["AI_BASE_URL"]),
                    headers={"x-goog-api-key": self.config["AI_API_KEY"]},
                    json=body,
                    timeout=httpx.Timeout(75, connect=8),
                    follow_redirects=False,
                )
            else:
                body = {
                    "model": self.config["AI_MODEL"],
                    "temperature": 0.3,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "itinerary", "strict": True, "schema": schema},
                    },
                    "messages": [
                        {"role": "system", "content": "You are a careful Sri Lanka trip planner."},
                        {"role": "user", "content": prompt},
                    ],
                }
                response = httpx.post(
                    self.config["AI_BASE_URL"].rstrip("/") + "/chat/completions",
                    headers={"Authorization": "Bearer " + self.config["AI_API_KEY"]},
                    json=body,
                    timeout=httpx.Timeout(75, connect=8),
                    follow_redirects=False,
                )
            response.raise_for_status()
            data = response.json()
            content = (
                _gemini_output_text(data)
                if provider == "gemini"
                else data["choices"][0]["message"]["content"]
            )
            result = ItineraryResult.model_validate_json(content)
        except httpx.HTTPStatusError as error:
            logger.warning(
                "AI provider request failed provider=%s status=%s",
                provider,
                error.response.status_code,
            )
            raise APIError("AI_UNAVAILABLE", "The AI provider did not return a valid itinerary.", 502) from None
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            logger.warning(
                "AI provider response was invalid provider=%s error_type=%s",
                provider,
                type(error).__name__,
            )
            raise APIError("AI_UNAVAILABLE", "The AI provider did not return a valid itinerary.", 502) from None
        expected_days = (request_data["end_date"] - request_data["start_date"]).days + 1
        if len(result.days) != expected_days or [d.day_number for d in result.days] != list(range(1, expected_days + 1)):
            raise APIError("AI_INVALID_RESPONSE", "The AI provider returned an incomplete itinerary.", 502)
        if any(d.date != request_data["start_date"].fromordinal(request_data["start_date"].toordinal() + d.day_number - 1) for d in result.days):
            raise APIError("AI_INVALID_RESPONSE", "The AI provider returned itinerary dates that do not match the trip.", 502)
        return result.model_dump(mode="json")
