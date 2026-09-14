from datetime import date, time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Name = Annotated[str, Field(min_length=1, max_length=200)]
Text = Annotated[str, Field(max_length=4000)]
Money = Annotated[int, Field(ge=0, le=2_000_000_000)]
PreferredLanguage = Literal["en", "si", "ta"]


class PlannerDestination(Schema):
    name: Name
    place_id: Annotated[str, Field(max_length=300)] | None = None
    latitude: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)] | None = None
    longitude: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be supplied together")
        return self


class PlannerRequest(Schema):
    destinations: Annotated[list[PlannerDestination], Field(max_length=20)] = Field(default_factory=list)
    traveller_type: Literal["Solo", "Couple", "Friends", "Family", "Group"]
    traveller_count: Annotated[StrictInt, Field(gt=0, le=100)]
    start_date: date
    end_date: date
    transport_preferences: Annotated[list[Name], Field(max_length=30)] = Field(default_factory=list)
    accommodation_preference: Name | None = None
    travel_style: Literal["Budget", "Comfort", "Premium", "Let AI decide"] | None = None
    interests: Annotated[list[Name], Field(max_length=30)] = Field(default_factory=list)
    travel_pace: Literal["Relaxed", "Balanced", "Packed"] | None = None
    special_requests: Annotated[str, Field(max_length=2000)] | None = None
    allow_ai_destination_suggestions: bool = False
    suggest_additional_places: bool = False
    preferred_language: PreferredLanguage = "en"

    @field_validator("destinations", mode="before")
    @classmethod
    def normalize_destinations(cls, value):
        if value is None:
            return []
        if isinstance(value, list):
            return [{"name": item} if isinstance(item, str) else item for item in value]
        return value

    @field_validator("transport_preferences", "interests", mode="before")
    @classmethod
    def normalize_optional_lists(cls, value):
        return [] if value is None else value

    @field_validator(
        "accommodation_preference", "travel_style", "travel_pace", "special_requests", mode="before"
    )
    @classmethod
    def normalize_optional_text(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def constraints(self):
        if not self.destinations and not self.allow_ai_destination_suggestions:
            raise ValueError("Please select at least one destination.")
        if self.end_date < self.start_date:
            raise ValueError("Trip dates are invalid.")
        if (self.end_date - self.start_date).days > 29:
            raise ValueError("Trips cannot exceed 30 days.")
        return self

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days + 1


class ActivityLocation(Schema):
    name: Name
    latitude: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)] | None = None
    longitude: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            self.latitude = None
            self.longitude = None
        return self


class ItineraryActivity(Schema):
    id: Name
    name: Name
    category: Name
    location: ActivityLocation
    start_time: time
    end_time: time
    duration_minutes: Annotated[StrictInt, Field(gt=0, le=1440)]
    description: Text
    estimated_cost_lkr: Money
    transport_from_previous: Annotated[str, Field(max_length=1000)] = ""
    travel_time_minutes: Annotated[StrictInt, Field(ge=0, le=1440)] = 0


class CostRange(Schema):
    min: Money
    max: Money

    @model_validator(mode="after")
    def ordered(self):
        if self.max < self.min:
            raise ValueError("cost range max must be greater than or equal to min")
        return self


class ItineraryDay(Schema):
    day_number: Annotated[StrictInt, Field(ge=1, le=30)]
    date: date
    destination: Name
    title: Name
    summary: Text
    activities: Annotated[list[ItineraryActivity], Field(min_length=1, max_length=15)]
    day_estimated_cost_lkr: CostRange


class TripSummary(Schema):
    title: Name
    summary: Text
    route: Annotated[list[Name], Field(min_length=1, max_length=20)]
    start_date: date
    end_date: date
    duration_days: Annotated[StrictInt, Field(ge=1, le=30)]
    traveller_type: Literal["Solo", "Couple", "Friends", "Family", "Group"]
    traveller_count: Annotated[StrictInt, Field(gt=0, le=100)]
    travel_style: Name
    travel_pace: Name


class CostEstimate(Schema):
    currency: Literal["LKR"] = "LKR"
    accommodation: CostRange
    transport: CostRange
    food: CostRange
    activities: CostRange
    total: CostRange
    disclaimer: Text


class AiItineraryResponse(Schema):
    trip: TripSummary
    days: Annotated[list[ItineraryDay], Field(min_length=1, max_length=30)]
    cost_estimate: CostEstimate
    recommendations: Annotated[list[Name], Field(max_length=30)] = Field(default_factory=list)


# Latency-optimized Stage 1 schema. The backend expands this into the stable
# AiItineraryResponse contract consumed by Android.
class InitialActivity(Schema):
    name: Name
    location: Name
    start_time: time
    duration_minutes: Annotated[StrictInt, Field(gt=0, le=720)]


class InitialDay(Schema):
    day_number: Annotated[StrictInt, Field(ge=1, le=30)]
    date: date
    destination: Name
    title: Name
    activities: Annotated[list[InitialActivity], Field(min_length=1, max_length=5)]


class InitialTrip(Schema):
    title: Name
    summary: Annotated[str, Field(max_length=300)]
    route: Annotated[list[Name], Field(min_length=1, max_length=20)]


class InitialCostEstimate(Schema):
    total: CostRange


class InitialItineraryResponse(Schema):
    trip: InitialTrip
    days: Annotated[list[InitialDay], Field(min_length=1, max_length=30)]
    cost_estimate: InitialCostEstimate


class PlannedItinerarySave(Schema):
    planner: PlannerRequest
    itinerary: AiItineraryResponse


class ModifyItineraryRequest(Schema):
    trip_context: PlannerRequest
    current_itinerary: AiItineraryResponse
    instruction: Annotated[str, Field(min_length=1, max_length=1000)]
    target_day: Annotated[StrictInt, Field(ge=1, le=30)] | None = None
