from io import BytesIO

import json

import pytest
from PIL import Image


def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json == {"success": True, "status": "healthy"}


def test_railway_health_is_public_and_dependency_free():
    from app import create_app

    app = create_app({
        "TESTING": True,
        "SUPABASE_URL": "",
        "SUPABASE_KEY": "",
        "GEMINI_API_KEY": "",
        "WEATHER_API_KEY": "",
        "CORS_ORIGINS": [],
    })

    response = app.test_client().get("/health")
    assert response.status_code == 200
    assert response.json == {"success": True, "status": "healthy"}


def test_missing_supabase_configuration_does_not_crash_worker_import():
    from app import create_app

    app = create_app({
        "TESTING": True,
        "SUPABASE_URL": "",
        "SUPABASE_KEY": "",
        "GEMINI_API_KEY": "",
        "WEATHER_API_KEY": "",
        "CORS_ORIGINS": [],
    })

    response = app.test_client().get(
        "/api/users/me",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code == 503
    assert response.json["error"]["code"] == "SUPABASE_NOT_CONFIGURED"


def test_protected_endpoint_requires_bearer_token(client):
    response = client.get("/api/users/me")
    assert response.status_code == 401
    assert response.json["success"] is False
    assert response.json["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_supabase_auth_forbidden_is_mapped_to_unauthorized():
    from app.services.supabase_service import SupabaseService
    from app.utils.responses import APIError

    service = object.__new__(SupabaseService)
    def rejected(*_args, **_kwargs):
        raise APIError("FORBIDDEN", "You do not have permission for this action.", 403)
    service.request = rejected
    with pytest.raises(APIError) as captured:
        service.get_user()
    assert captured.value.status == 401
    assert captured.value.code == "UNAUTHORIZED"


def test_profile_fetch_uses_authenticated_user_id(client, auth_headers):
    response = client.get("/api/users/me", headers=auth_headers)

    assert response.status_code == 200
    assert response.json["data"]["id"] == "00000000-0000-4000-8000-000000000001"


def test_profile_patch_updates_single_field(client, auth_headers):
    response = client.patch("/api/users/me", headers=auth_headers, json={"display_name": "  New Name  "})

    assert response.status_code == 200
    assert response.json["data"]["display_name"] == "New Name"
    assert response.json["data"]["email"] == "test@example.com"


def test_profile_patch_updates_multiple_fields(client, auth_headers):
    response = client.patch("/api/users/me", headers=auth_headers, json={
        "bio": "  Traveller and technology enthusiast  ",
        "home_city": "Colombo",
        "language": "si",
        "interests": ["beaches", "hiking"],
        "phone": "+94 77 123 4567",
    })

    assert response.status_code == 200
    assert response.json["data"]["bio"] == "Traveller and technology enthusiast"
    assert response.json["data"]["home_city"] == "Colombo"
    assert response.json["data"]["language"] == "si"
    assert response.json["data"]["interests"] == ["beaches", "hiking"]
    assert response.json["data"]["phone"] == "+94 77 123 4567"


def test_profile_patch_preserves_omitted_fields(client, auth_headers):
    response = client.patch("/api/users/me", headers=auth_headers, json={"bio": "Updated"})

    assert response.status_code == 200
    assert response.json["data"]["display_name"] == "Test"
    assert response.json["data"]["home_city"] == "Kandy"
    assert response.json["data"]["phone"] == "+94112223344"


@pytest.mark.parametrize("payload", [
    {"display_name": "   "},
    {"phone": "not-a-phone"},
    {"interests": "hiking"},
    {},
])
def test_profile_patch_rejects_invalid_input(client, auth_headers, payload):
    response = client.patch("/api/users/me", headers=auth_headers, json=payload)

    assert response.status_code == 400
    assert response.json["error"]["code"] == "INVALID_REQUEST"


def test_profile_patch_requires_authentication(client):
    response = client.patch("/api/users/me", json={"bio": "Updated"})

    assert response.status_code == 401


def test_profile_patch_cannot_update_auth_owned_email(client, auth_headers):
    response = client.patch("/api/users/me", headers=auth_headers, json={"email": "attacker@example.com"})

    assert response.status_code == 400
    assert response.json["error"]["code"] == "INVALID_REQUEST"
    profile = client.get("/api/users/me", headers=auth_headers)
    assert profile.json["data"]["email"] == "test@example.com"


def test_username_update_is_normalized(client, auth_headers):
    response = client.patch("/api/users/me", headers=auth_headers, json={"username": "@New_Name"})
    assert response.status_code == 200
    assert response.json["data"]["username"] == "new_name"


def test_user_search_returns_only_public_fields(client, auth_headers):
    response = client.get("/api/users/search?q=test", headers=auth_headers)
    assert response.status_code == 200
    assert response.json["data"] == [{
        "id": "00000000-0000-4000-8000-000000000001", "username": "test482913",
        "display_name": "Test", "avatar_url": None,
    }]
    assert "email" not in response.json["data"][0]
    assert "phone" not in response.json["data"][0]
    assert "home_city" not in response.json["data"][0]


def test_user_search_and_availability_require_authentication(client):
    assert client.get("/api/users/search?q=test").status_code == 401
    assert client.get("/api/users/username-availability?username=test123").status_code == 401


def test_username_availability_validates_format(client, auth_headers):
    invalid = client.get("/api/users/username-availability?username=Bad-Name", headers=auth_headers)
    assert invalid.status_code == 200
    assert invalid.json["data"] == {"username": "bad-name", "available": False, "valid": False}


def test_duplicate_username_update_returns_clear_conflict(auth_headers):
    from conftest import FakeSupabase
    from app import create_app

    class DuplicateUsernameFake(FakeSupabase):
        def __init__(self, config, token):
            super().__init__(config, token)
            self.rows["profiles"].append({
                "id": "00000000-0000-4000-8000-000000000002", "username": "already_taken",
                "display_name": "Another User", "avatar_url": None,
            })

    app = create_app({"TESTING": True, "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "test-key",
                      "SUPABASE_SERVICE_ROLE_KEY": "", "CORS_ORIGINS": [], "GEMINI_API_KEY": "",
                      "SUPABASE_FACTORY": DuplicateUsernameFake})
    response = app.test_client().patch("/api/users/me", headers=auth_headers, json={"username": "already_taken"})
    assert response.status_code == 409
    assert response.json["error"] == {"code": "USERNAME_TAKEN", "message": "That username is already taken."}


def test_profile_picture_upload_persists_storage_path_on_profile(auth_headers):
    from app import create_app
    from conftest import FakeSupabase

    class StorageUploadFake(FakeSupabase):
        uploaded = None

        def request(self, method, path, **kwargs):
            if method == "POST" and path.startswith("/storage/v1/object/profile-images/"):
                StorageUploadFake.uploaded = (path, kwargs["content"], kwargs["headers"])
                return {"Key": path}
            return None

    image = BytesIO()
    Image.new("RGB", (24, 24), "#238DD1").save(image, format="PNG")
    image.seek(0)
    app = create_app({"TESTING": True, "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "test-key",
                      "SUPABASE_SERVICE_ROLE_KEY": "", "CORS_ORIGINS": [], "GEMINI_API_KEY": "",
                      "SUPABASE_FACTORY": StorageUploadFake})

    response = app.test_client().post(
        "/api/storage/profile-picture",
        headers=auth_headers,
        data={"file": (image, "avatar.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    avatar_path = response.json["data"]["profile"]["avatar_path"]
    assert avatar_path.startswith("00000000-0000-4000-8000-000000000001/")
    assert avatar_path.endswith(".png")
    assert response.json["data"]["upload"]["path"] == avatar_path
    assert StorageUploadFake.uploaded[2]["Content-Type"] == "image/png"


def test_profile_picture_download_is_authenticated_and_account_scoped(auth_headers):
    from app import create_app
    from conftest import FakeSupabase

    image = BytesIO()
    Image.new("RGB", (12, 12), "#238DD1").save(image, format="JPEG")
    image_bytes = image.getvalue()

    class StorageDownloadFake(FakeSupabase):
        def __init__(self, config, token):
            super().__init__(config, token)
            self.rows["profiles"][0]["avatar_path"] = f"{self.user['id']}/avatar.jpg"

        def request_binary(self, method, path, **_kwargs):
            assert method == "GET"
            assert path == f"/storage/v1/object/authenticated/profile-images/{self.user['id']}/avatar.jpg"
            return image_bytes, "image/jpeg"

    app = create_app({"TESTING": True, "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "test-key",
                      "SUPABASE_SERVICE_ROLE_KEY": "", "CORS_ORIGINS": [], "GEMINI_API_KEY": "",
                      "SUPABASE_FACTORY": StorageDownloadFake})

    response = app.test_client().get("/api/storage/profile-picture", headers=auth_headers)

    assert response.status_code == 200
    assert response.content_type == "image/jpeg"
    assert response.data == image_bytes
    assert app.test_client().get("/api/storage/profile-picture").status_code == 401


def test_invalid_json_has_standard_error(client, auth_headers):
    response = client.post("/api/trips", headers=auth_headers, json={"name": "Only name"})
    assert response.status_code == 422
    assert response.json["success"] is False
    assert response.json["error"]["code"] == "INVALID_REQUEST"


def test_trip_creation_uses_authenticated_identity(client, auth_headers):
    response = client.post("/api/trips", headers=auth_headers, json={
        "name": "Hill Country", "destinations": ["Kandy", "Ella"], "start_date": "2026-10-01", "end_date": "2026-10-03",
        "budget": "50000.00", "travelers": 2,
    })
    assert response.status_code == 201
    assert response.json["success"] is True
    assert response.json["data"]["created_by"] == "00000000-0000-4000-8000-000000000001"


def test_wishlist_creation_uses_authenticated_identity(client, auth_headers):
    response = client.post("/api/wishlists", headers=auth_headers, json={"name": "Hill Country"})

    assert response.status_code == 201
    assert response.json["data"]["user_id"] == "00000000-0000-4000-8000-000000000001"
    assert response.json["data"]["name"] == "Hill Country"


def test_saved_place_validates_coordinate_pair(client, auth_headers):
    wishlist = client.post("/api/wishlists", headers=auth_headers, json={"name": "Beaches"}).json["data"]
    response = client.post(
        f"/api/wishlists/{wishlist['id']}/places", headers=auth_headers,
        json={"name": "Mirissa", "latitude": 5.9483},
    )

    assert response.status_code == 422
    assert response.json["error"]["code"] == "INVALID_REQUEST"


def test_cors_only_allows_configured_origin(client):
    allowed = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    denied = client.get("/api/health", headers={"Origin": "https://untrusted.example"})
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert "PATCH" in allowed.headers["Access-Control-Allow-Methods"]
    assert "Access-Control-Allow-Origin" not in denied.headers


def test_ai_is_optional_at_startup(app, client):
    assert app.extensions["ai_service"] is None
    assert client.get("/api/health").status_code == 200


def test_ai_endpoint_returns_503_when_not_configured(client, auth_headers):
    response = client.post("/api/itineraries/preview", headers=auth_headers, json={})

    assert response.status_code == 503
    assert response.json == {
        "success": False,
        "error": {"code": "ai_not_configured", "message": "AI itinerary generation is currently unavailable."},
    }


def test_weather_requires_authentication(client):
    response = client.get("/api/weather?latitude=7.29&longitude=80.63&date=2026-10-01")
    assert response.status_code == 401
    assert response.json["error"]["code"] == "UNAUTHORIZED"


def test_weather_accepts_profile_city_and_normalizes_provider_data(client, auth_headers, monkeypatch):
    class ProviderResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {"location": {"name": "Kandy"}, "forecast": {"forecastday": [{
                "day": {"condition": {"text": "Patchy rain", "icon": "//icon"}, "mintemp_c": 20,
                        "maxtemp_c": 28, "daily_chance_of_rain": 70, "uv": 5, "avghumidity": 81,
                        "maxwind_kph": 18.5}, "astro": {"sunrise": "06:01 AM"}}]}}

    provider_call = {}
    def fake_get(url, **kwargs):
        provider_call.update(url=url, **kwargs)
        return ProviderResponse()
    monkeypatch.setattr("app.services.weather_service.httpx.get", fake_get)
    from app import create_app
    from conftest import FakeSupabase
    app = create_app({"TESTING": True, "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "test-key",
                      "SUPABASE_SERVICE_ROLE_KEY": "", "CORS_ORIGINS": [], "GEMINI_API_KEY": "",
                      "WEATHER_API_KEY": "weather-key", "WEATHER_PROVIDER": "weatherapi",
                      "SUPABASE_FACTORY": FakeSupabase})
    response = app.test_client().get("/api/weather?location=Kandy&date=2026-10-01", headers=auth_headers)
    assert response.status_code == 200
    assert response.json["data"] | {"location": "Kandy", "humidity": 81, "wind_kph": 18.5, "sunrise": "06:01 AM"} == response.json["data"]
    assert provider_call["params"]["q"] == "Kandy"

    response = app.test_client().get(
        "/api/weather?latitude=6.9271&longitude=79.8612&date=2026-10-01",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert provider_call["params"]["q"] == "6.9271,79.8612"


def test_expense_delete_uses_authorized_atomic_rpc(client, auth_headers):
    from conftest import FakeSupabase

    # The fake is request-scoped, so exercise the adapter contract through a focused fake factory.
    class ExpenseFake(FakeSupabase):
        last_rpc = None
        def __init__(self, config, token):
            super().__init__(config, token)
            self.rows["trips"] = [{"id": "00000000-0000-4000-8000-000000000020", "created_by": self.user["id"]}]
            self.rows["expenses"] = [{"id": "00000000-0000-4000-8000-000000000030", "trip_id": "00000000-0000-4000-8000-000000000020", "created_by": self.user["id"]}]
        def rpc(self, name, data):
            ExpenseFake.last_rpc = (name, data)
            return True

    from app import create_app
    app = create_app({"TESTING": True, "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "test-key",
                      "SUPABASE_SERVICE_ROLE_KEY": "", "CORS_ORIGINS": [], "GEMINI_API_KEY": "",
                      "SUPABASE_FACTORY": ExpenseFake})
    response = app.test_client().delete("/api/expenses/00000000-0000-4000-8000-000000000030", headers=auth_headers)
    assert response.status_code == 200
    assert ExpenseFake.last_rpc[0] == "delete_expense"


def planner_payload(**overrides):
    payload = {
        "destinations": [{"name": "Ella"}], "traveller_type": "Solo", "traveller_count": 1,
        "start_date": "2026-10-01", "end_date": "2026-10-03", "transport_preferences": [],
        "accommodation_preference": None, "travel_style": None, "interests": [], "travel_pace": None,
        "special_requests": None, "allow_ai_destination_suggestions": False,
    }
    return payload | overrides


@pytest.mark.parametrize("payload,message", [
    (planner_payload(end_date="2026-09-30"), "Trip dates are invalid."),
    (planner_payload(destinations=[]), "Please select at least one destination."),
    (planner_payload(traveller_count=0), "Traveller count must be greater than zero."),
])
def test_planner_validation_errors_are_clean(client, auth_headers, payload, message):
    client.application.extensions["ai_service"] = object()
    response = client.post("/api/itineraries/preview", headers=auth_headers, json=payload)
    assert response.status_code == 400
    assert response.json["error"] == {"code": "validation_error", "message": message}


def test_ai_destination_suggestion_mode_allows_empty_destinations(client, auth_headers):
    class FakeAI:
        def generate_itinerary(self, planner):
            assert planner.allow_ai_destination_suggestions is True
            from app.utils.responses import APIError
            raise APIError("expected", "request reached AI", 418)
    client.application.extensions["ai_service"] = FakeAI()
    response = client.post("/api/itineraries/preview", headers=auth_headers,
                           json=planner_payload(destinations=[], allow_ai_destination_suggestions=True))
    assert response.status_code == 418


def test_planner_accepts_string_destinations_and_null_optional_fields(client, auth_headers):
    class FakeAI:
        def generate_itinerary(self, planner):
            assert [item.name for item in planner.destinations] == ["Kandy", "Ella"]
            assert planner.transport_preferences == []
            assert planner.interests == []
            assert planner.travel_style is None
            from app.utils.responses import APIError
            raise APIError("expected", "request reached AI", 418)

    client.application.extensions["ai_service"] = FakeAI()
    response = client.post(
        "/api/itineraries/preview",
        headers=auth_headers,
        json=planner_payload(
            destinations=["Kandy", "Ella"], transport_preferences=None,
            interests=None, travel_style="", special_requests="",
        ),
    )
    assert response.status_code == 418


def test_gemini_structured_output_retries_once():
    import json
    from app.services.ai_service import AIService

    valid = {
        "trip": {"title": "Ella Escape", "summary": "A balanced Ella trip.", "route": ["Ella"]},
        "days": [{
            "day_number": day, "date": f"2026-10-0{day}", "destination": "Ella",
            "title": f"Ella day {day}",
            "activities": [{
                "name": f"Ella activity {activity}", "location": "Ella",
                "start_time": f"{8 + activity:02d}:00", "duration_minutes": 60,
            } for activity in range(1, 4)],
        } for day in range(1, 4)],
        "cost_estimate": {"total": {"min": 20000, "max": 32000}},
    }
    class Interactions:
        def __init__(self): self.calls = []
        def create(self, **kwargs):
            self.calls.append(kwargs)
            return type("Interaction", (), {"output_text": "not-json" if len(self.calls) == 1 else json.dumps(valid)})()
    interactions = Interactions()
    client = type("Client", (), {"interactions": interactions})()
    service = AIService({"GEMINI_API_KEY": "test", "GEMINI_MODEL": "gemini-test", "GEMINI_TIMEOUT_SECONDS": "60"},
                        client_factory=lambda **_kwargs: client)
    result = service.generate_itinerary(planner_payload())
    assert len(interactions.calls) == 2
    assert interactions.calls[0]["response_format"]["mime_type"] == "application/json"
    assert "schema" in interactions.calls[0]["response_format"]
    assert interactions.calls[0]["generation_config"]["thinking_level"] == "low"
    assert result.trip.duration_days == 3


def test_gemini_initial_schema_is_compact():
    from app.services.ai_service import INITIAL_RESPONSE_SCHEMA

    assert set(INITIAL_RESPONSE_SCHEMA["properties"]) == {"trip", "days", "cost_estimate"}
    activity = INITIAL_RESPONSE_SCHEMA["properties"]["days"]["items"]["properties"]["activities"]["items"]
    assert set(activity["properties"]) == {"name", "location", "start_time", "duration_minutes"}


def test_gaos_bad_request_maps_to_clean_502():
    from app.services.ai_service import AIService
    from app.utils.responses import APIError

    BadRequestError = type(
        "BadRequestError", (Exception,), {"__module__": "google.genai._gaos.lib.compat_errors"}
    )

    class Interactions:
        def create(self, **_kwargs):
            error = BadRequestError("Request contains an invalid argument.")
            error.status_code = 400
            raise error

    client = type("Client", (), {"interactions": Interactions()})()
    service = AIService(
        {"GEMINI_API_KEY": "test", "GEMINI_MODEL": "gemini-test", "GEMINI_TIMEOUT_SECONDS": "60"},
        client_factory=lambda **_kwargs: client,
    )
    with pytest.raises(APIError) as raised:
        service.generate_itinerary(planner_payload())
    assert raised.value.status == 502
    assert raised.value.code == "ai_request_failed"


def test_trip_invitation_routes_use_authenticated_atomic_rpcs(auth_headers):
    from app import create_app
    from conftest import FakeSupabase

    trip_id = "00000000-0000-4000-8000-000000000020"
    invite_id = "00000000-0000-4000-8000-000000000030"
    target_id = "00000000-0000-4000-8000-000000000002"

    class InvitationFake(FakeSupabase):
        calls = []
        def __init__(self, config, token):
            super().__init__(config, token)
            self.rows["trips"] = [{"id": trip_id, "created_by": self.user["id"]}]
            self.rows["trip_members"] = [{"trip_id": trip_id, "user_id": self.user["id"], "role": "owner"}]

        def rpc(self, name, data):
            InvitationFake.calls.append((name, data))
            if name == "list_my_trip_invites": return []
            return {"id": invite_id, "status": "accepted" if data.get("p_accept") else "pending"}

    app = create_app({"TESTING": True, "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "test-key",
                      "SUPABASE_SERVICE_ROLE_KEY": "", "CORS_ORIGINS": [], "GEMINI_API_KEY": "",
                      "SUPABASE_FACTORY": InvitationFake})
    api = app.test_client()

    assert api.post(f"/api/trips/{trip_id}/invites", json={"user_id": target_id}).status_code == 401
    assert api.post(f"/api/trips/{trip_id}/invites", headers=auth_headers,
                    json={"user_id": target_id}).status_code == 201
    assert api.get("/api/trip-invites/me", headers=auth_headers).status_code == 200
    assert api.post(f"/api/trip-invites/{invite_id}/accept", headers=auth_headers).status_code == 200
    assert api.post(f"/api/trip-invites/{invite_id}/decline", headers=auth_headers).status_code == 200
    assert ("create_trip_invite", {"p_trip_id": trip_id, "p_invited_user_id": target_id}) in InvitationFake.calls
    assert ("respond_trip_invite", {"p_invite_id": invite_id, "p_accept": True}) in InvitationFake.calls
    assert ("respond_trip_invite", {"p_invite_id": invite_id, "p_accept": False}) in InvitationFake.calls


def test_admin_cannot_create_trip_invite(auth_headers):
    from app import create_app
    from conftest import FakeSupabase

    trip_id = "00000000-0000-4000-8000-000000000020"
    target_id = "00000000-0000-4000-8000-000000000002"

    class AdminFake(FakeSupabase):
        rpc_called = False

        def __init__(self, config, token):
            super().__init__(config, token)
            self.rows["trips"] = [{"id": trip_id, "created_by": "00000000-0000-4000-8000-000000000099"}]
            self.rows["trip_members"] = [{"trip_id": trip_id, "user_id": self.user["id"], "role": "admin"}]

        def rpc(self, name, data):
            AdminFake.rpc_called = True
            return super().rpc(name, data)

    app = create_app({"TESTING": True, "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "test-key",
                      "SUPABASE_SERVICE_ROLE_KEY": "", "CORS_ORIGINS": [], "GEMINI_API_KEY": "",
                      "SUPABASE_FACTORY": AdminFake})
    response = app.test_client().post(
        f"/api/trips/{trip_id}/invites", headers=auth_headers, json={"user_id": target_id}
    )

    assert response.status_code == 403
    assert AdminFake.rpc_called is False


def test_point_lookup_does_not_order_by_columns_absent_from_composite_key_tables():
    from app.services.supabase_service import SupabaseService

    service = SupabaseService({"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "test-key"}, "token")
    captured = {}

    def request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return [{"trip_id": "trip", "user_id": "user", "role": "member"}]

    service.request = request
    try:
        row = service.one("trip_members", {"trip_id": "trip", "user_id": "user"})
    finally:
        service.close()

    assert row["role"] == "member"
    assert "order" not in captured["params"]


def test_equal_expense_contract_delegates_atomic_split_to_database(auth_headers):
    from app import create_app
    from conftest import FakeSupabase

    trip_id = "00000000-0000-4000-8000-000000000020"
    user_id = "00000000-0000-4000-8000-000000000001"

    class ExpenseFake(FakeSupabase):
        calls = []
        def __init__(self, config, token):
            super().__init__(config, token)
            self.rows["trips"] = [{"id": trip_id, "created_by": user_id}]

        def rpc(self, name, data):
            ExpenseFake.calls.append((name, data))
            if name == "create_equal_expense":
                return {"id": "00000000-0000-4000-8000-000000000040", **data["p_data"]}
            if name == "list_trip_expenses_public": return []
            if name == "get_trip_expense_balances": return {"trip_id": trip_id, "balances": []}
            return super().rpc(name, data)

    app = create_app({"TESTING": True, "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "test-key",
                      "SUPABASE_SERVICE_ROLE_KEY": "", "CORS_ORIGINS": [], "GEMINI_API_KEY": "",
                      "SUPABASE_FACTORY": ExpenseFake})
    api = app.test_client()
    response = api.post(f"/api/trips/{trip_id}/expenses", headers=auth_headers, json={
        "title": "Hotel", "amount": "10000.00", "category": "Accommodation", "paid_by": user_id,
        "participant_ids": [user_id], "expense_date": "2026-09-13", "notes": "",
    })
    assert response.status_code == 201
    call = next(data for name, data in ExpenseFake.calls if name == "create_equal_expense")
    assert call["p_data"]["participant_ids"] == [user_id]
    assert "participants" not in call["p_data"]
    assert api.get(f"/api/trips/{trip_id}/expenses", headers=auth_headers).status_code == 200
    assert api.get(f"/api/trips/{trip_id}/expense-balances", headers=auth_headers).status_code == 200
