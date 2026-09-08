"""Provider-neutral itinerary generation service.

The first adapter speaks the OpenAI-compatible Chat Completions protocol. Replace this class or
select another provider via a factory later; route code only relies on generate_itinerary().
"""
import json

import httpx

from app.utils.responses import APIError
from app.utils.validators import ItineraryResult


class AIService:
    def __init__(self, config):
        self.config = config

    def generate_itinerary(self, request_data):
        if not self.config.get("AI_API_KEY") or not self.config.get("AI_BASE_URL") or not self.config.get("AI_MODEL"):
            raise APIError("AI_NOT_CONFIGURED", "AI itinerary generation is not configured yet.", 503)
        if self.config.get("AI_PROVIDER", "openai_compatible") not in ("", "openai_compatible"):
            raise APIError("AI_PROVIDER_UNSUPPORTED", "The configured AI provider is not supported.", 503)
        schema = ItineraryResult.model_json_schema()
        prompt = (
            "Create a practical Sri Lankan travel itinerary. Respect dates, budget, traveller count, "
            "preferences and travel times. Costs must be non-negative estimates in the requested currency. "
            "Return only JSON matching the supplied schema.\nInput:\n" + json.dumps(request_data, default=str)
        )
        body = {"model": self.config["AI_MODEL"], "temperature": 0.3,
                "response_format": {"type": "json_schema", "json_schema": {"name": "itinerary", "strict": True, "schema": schema}},
                "messages": [{"role": "system", "content": "You are a careful Sri Lanka trip planner."},
                             {"role": "user", "content": prompt}]}
        try:
            response = httpx.post(self.config["AI_BASE_URL"].rstrip("/") + "/chat/completions",
                                  headers={"Authorization": "Bearer " + self.config["AI_API_KEY"]}, json=body,
                                  timeout=httpx.Timeout(45, connect=8), follow_redirects=False)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            result = ItineraryResult.model_validate_json(content)
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise APIError("AI_UNAVAILABLE", "The AI provider did not return a valid itinerary.", 502) from None
        expected_days = (request_data["end_date"] - request_data["start_date"]).days + 1
        if len(result.days) != expected_days or [d.day_number for d in result.days] != list(range(1, expected_days + 1)):
            raise APIError("AI_INVALID_RESPONSE", "The AI provider returned an incomplete itinerary.", 502)
        if any(d.date != request_data["start_date"].fromordinal(request_data["start_date"].toordinal() + d.day_number - 1) for d in result.days):
            raise APIError("AI_INVALID_RESPONSE", "The AI provider returned itinerary dates that do not match the trip.", 502)
        return result.model_dump(mode="json")
