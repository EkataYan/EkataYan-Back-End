def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json == {"success": True, "status": "healthy"}


def test_protected_endpoint_requires_bearer_token(client):
    response = client.get("/api/users/me")
    assert response.status_code == 401
    assert response.json["success"] is False
    assert response.json["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_profile_fetch_uses_authenticated_user_id(client, auth_headers):
    response = client.get("/api/users/me", headers=auth_headers)

    assert response.status_code == 200
    assert response.json["data"]["id"] == "00000000-0000-4000-8000-000000000001"


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


def test_cors_only_allows_configured_origin(client):
    allowed = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    denied = client.get("/api/health", headers={"Origin": "https://untrusted.example"})
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert "Access-Control-Allow-Origin" not in denied.headers
