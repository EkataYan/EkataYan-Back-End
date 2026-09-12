import pytest


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
        "AI_API_KEY": "",
        "AI_BASE_URL": "",
        "AI_MODEL": "",
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
        "AI_API_KEY": "",
        "AI_BASE_URL": "",
        "AI_MODEL": "",
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
    response = client.post("/api/itineraries/generate", headers=auth_headers, json={})

    assert response.status_code == 503
    assert response.json == {
        "success": False,
        "error": {"code": "AI_NOT_CONFIGURED", "message": "AI service is not configured"},
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
                      "SUPABASE_SERVICE_ROLE_KEY": "", "CORS_ORIGINS": [], "AI_API_KEY": "", "AI_BASE_URL": "",
                      "AI_MODEL": "", "WEATHER_API_KEY": "weather-key", "WEATHER_PROVIDER": "weatherapi",
                      "SUPABASE_FACTORY": FakeSupabase})
    response = app.test_client().get("/api/weather?location=Kandy&date=2026-10-01", headers=auth_headers)
    assert response.status_code == 200
    assert response.json["data"] | {"location": "Kandy", "humidity": 81, "wind_kph": 18.5, "sunrise": "06:01 AM"} == response.json["data"]
    assert provider_call["params"]["q"] == "Kandy"


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
                      "SUPABASE_SERVICE_ROLE_KEY": "", "CORS_ORIGINS": [], "AI_API_KEY": "", "AI_BASE_URL": "",
                      "AI_MODEL": "", "SUPABASE_FACTORY": ExpenseFake})
    response = app.test_client().delete("/api/expenses/00000000-0000-4000-8000-000000000030", headers=auth_headers)
    assert response.status_code == 200
    assert ExpenseFake.last_rpc[0] == "delete_expense"


def test_complete_ai_config_initializes_existing_service(monkeypatch):
    import json
    from datetime import date

    from app import create_app
    from conftest import FakeSupabase

    class ProviderResponse:
        content = b"json"

        def raise_for_status(self):
            pass

        def json(self):
            itinerary = {
                "overview": "A day in Kandy",
                "currency": "LKR",
                "days": [{
                    "day_number": 1,
                    "date": "2026-10-01",
                    "locations": ["Kandy"],
                    "activities": [{
                        "title": "Temple visit",
                        "location": "Kandy",
                        "suggested_time": "09:00:00",
                        "description": "Visit the Temple of the Tooth",
                        "estimated_cost": "2000.00",
                        "transport": "Walk",
                    }],
                }],
            }
            return {"choices": [{"message": {"content": json.dumps(itinerary)}}]}

    provider_call = {}

    def fake_post(url, **kwargs):
        provider_call.update(url=url, **kwargs)
        return ProviderResponse()

    monkeypatch.setattr("app.services.ai_service.httpx.post", fake_post)

    configured = create_app({
        "TESTING": True,
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_KEY": "test-key",
        "SUPABASE_SERVICE_ROLE_KEY": "",
        "CORS_ORIGINS": [],
        "AI_API_KEY": "test-ai-key",
        "AI_BASE_URL": "https://ai.example/v1",
        "AI_MODEL": "test-model",
        "AI_PROVIDER": "gemini",
        "SUPABASE_FACTORY": FakeSupabase,
    })

    service = configured.extensions["ai_service"]
    assert service is not None
    result = service.generate_itinerary({
        "start_date": date(2026, 10, 1),
        "end_date": date(2026, 10, 1),
        "currency": "LKR",
    })
    assert result["days"][0]["date"] == "2026-10-01"
    assert provider_call["url"] == "https://ai.example/v1/chat/completions"
    assert provider_call["json"]["model"] == "test-model"
    assert provider_call["headers"]["Authorization"] == "Bearer test-ai-key"
