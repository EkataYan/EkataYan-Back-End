from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Annotated, Literal
import re
from uuid import UUID

from flask import request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator, model_validator

from app.utils.responses import APIError

Text = Annotated[str, Field(min_length=1, max_length=160)]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]
Tags = Annotated[list[Text], Field(max_length=30)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProfileInput(Input):
    display_name: Text
    bio: Annotated[str, Field(max_length=1000)] = ""
    home_city: Annotated[str, Field(max_length=160)] = ""
    language: Literal["en", "si", "ta"] = "en"
    interests: Tags = []


class ProfilePatchInput(Input):
    display_name: Text | None = None
    bio: Annotated[str, Field(max_length=1000)] | None = None
    home_city: Annotated[str, Field(max_length=160)] | None = None
    language: Literal["en", "si", "ta"] | None = None
    interests: Tags | None = None
    phone: Annotated[str, Field(max_length=32)] | None = None

    @field_validator("phone")
    @classmethod
    def valid_phone(cls, value):
        if value is not None and value and not re.fullmatch(r"\+?[0-9 ()-]{7,32}", value):
            raise ValueError("phone contains invalid characters or has an invalid length")
        return value

    @model_validator(mode="after")
    def supplied_fields(self):
        if not self.model_fields_set:
            raise ValueError("At least one profile field is required.")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Profile fields cannot be null.")
        return self


class TripInput(Input):
    name: Text
    destinations: Annotated[list[Text], Field(min_length=1, max_length=20)]
    start_date: date
    end_date: date
    budget: Money
    currency: Literal["LKR", "USD", "EUR", "GBP", "INR", "AUD"] = "LKR"
    travelers: Annotated[StrictInt, Field(ge=1, le=100)] = 1
    interests: Tags = []
    preferred_activities: Tags = []
    travel_style: Text = "balanced"
    accommodation_preference: Text = "any"
    transportation_preference: Text = "any"
    additional_requirements: Annotated[str, Field(max_length=2000)] = ""

    @model_validator(mode="after")
    def dates(self):
        if self.end_date < self.start_date or (self.end_date - self.start_date).days > 29:
            raise ValueError("Trips must last between 1 and 30 days.")
        return self


class GenerateInput(TripInput):
    trip_id: UUID


class MemberInput(Input):
    user_id: UUID
    role: Literal["member", "admin"] = "member"


class Participant(Input):
    user_id: UUID
    share: Money


class ExpenseInput(Input):
    title: Text
    amount: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]
    currency: Literal["LKR", "USD", "EUR", "GBP", "INR", "AUD"] = "LKR"
    category: Text = "other"
    paid_by: UUID
    split_type: Literal["equal", "exact"] = "equal"
    participants: Annotated[list[Participant], Field(min_length=1, max_length=100)]
    incurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("incurred_at")
    @classmethod
    def aware_timestamp(cls, value):
        if value.tzinfo is None:
            raise ValueError("incurred_at must include a timezone.")
        return value

    @model_validator(mode="after")
    def splits(self):
        if len({p.user_id for p in self.participants}) != len(self.participants):
            raise ValueError("Participants must be unique.")
        if sum((p.share for p in self.participants), Decimal(0)) != self.amount:
            raise ValueError("Participant shares must sum exactly to amount.")
        if self.split_type == "equal":
            base = (self.amount / len(self.participants)).quantize(Decimal("0.01"), rounding="ROUND_DOWN")
            if any(p.share not in (base, base + Decimal("0.01")) for p in self.participants):
                raise ValueError("Equal shares must differ by at most one cent.")
        return self


class MessageInput(Input):
    content: Annotated[str, Field(min_length=1, max_length=4000)]


class Activity(Input):
    title: Text
    location: Text
    suggested_time: time
    description: Annotated[str, Field(max_length=2000)]
    estimated_cost: Money
    transport: Annotated[str, Field(max_length=1000)]
    notes: Annotated[str, Field(max_length=2000)] = ""


class ItineraryDay(Input):
    day_number: Annotated[StrictInt, Field(ge=1, le=30)]
    date: date
    locations: Annotated[list[Text], Field(min_length=1, max_length=20)]
    activities: Annotated[list[Activity], Field(min_length=1, max_length=15)]
    notes: Annotated[str, Field(max_length=2000)] = ""


class ItineraryResult(Input):
    overview: Annotated[str, Field(min_length=1, max_length=4000)]
    currency: Literal["LKR", "USD", "EUR", "GBP", "INR", "AUD"]
    days: Annotated[list[ItineraryDay], Field(min_length=1, max_length=30)]
    recommendations: Tags = []


class WeatherQuery(Input):
    latitude: Annotated[Decimal, Field(ge=-90, le=90, allow_inf_nan=False)]
    longitude: Annotated[Decimal, Field(ge=-180, le=180, allow_inf_nan=False)]
    date: date


def parse(model, data=None, error_status=422):
    if data is None:
        if not request.is_json:
            raise APIError("INVALID_REQUEST", "Content-Type must be application/json.", 415)
        data = request.get_json()
    try:
        return model.model_validate(data)
    except ValidationError as error:
        # Field names/types only: never reflect arbitrary request values or exception contexts.
        fields = sorted({str(e["loc"][0]) if e["loc"] else "body" for e in error.errors()})
        raise APIError("INVALID_REQUEST", "Invalid fields or constraints: " + ", ".join(fields), error_status) from None


def identifier(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise APIError("INVALID_REQUEST", "A valid UUID is required.", 422) from None


def pagination():
    try:
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
        if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
            raise ValueError
        return {"limit": limit, "offset": offset}
    except ValueError:
        raise APIError("INVALID_REQUEST", "limit must be 1–100 and offset 0–10000.", 422) from None
