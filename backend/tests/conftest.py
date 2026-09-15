import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeSupabase:
    def __init__(self, _config, token):
        self.token = token
        self.user = {"id": "00000000-0000-4000-8000-000000000001", "email": "test@example.com"}
        self.rows = {"trips": [], "profiles": [{
            "id": self.user["id"],
            "email": self.user["email"],
            "display_name": "Test",
            "username": "test482913",
            "avatar_url": None,
            "bio": "Original bio",
            "home_city": "Kandy",
            "language": "en",
            "interests": ["history"],
            "avatar_path": None,
            "phone": "+94112223344",
        }]}

    def close(self):
        pass

    def get_user(self):
        if self.token == "valid-token":
            return self.user
        from app.utils.responses import APIError
        raise APIError("UNAUTHORIZED", "Invalid or expired access token.", 401)

    def insert(self, table, data):
        result = {"id": "00000000-0000-4000-8000-000000000010"} | data
        self.rows.setdefault(table, []).append(result)
        return result

    def select(self, table, filters=None, **_kwargs):
        return [row for row in self.rows.get(table, []) if all(str(row.get(k)) == str(v) for k, v in (filters or {}).items())]

    def one(self, table, filters, **kwargs):
        from app.utils.responses import APIError
        rows = self.select(table, filters, **kwargs)
        if not rows:
            raise APIError("NOT_FOUND", "Resource not found or not accessible.", 404)
        return rows[0]

    def update(self, table, filters, data):
        if table == "profiles" and "username" in data and any(
            row.get("username", "").lower() == data["username"].lower() and row.get("id") != filters.get("id")
            for row in self.rows[table]
        ):
            from app.utils.responses import APIError
            raise APIError("CONFLICT", "The record conflicts with existing data or references.", 409)
        row = self.one(table, filters)
        row.update(data)
        return row

    def delete(self, table, filters):
        row = self.one(table, filters)
        self.rows[table].remove(row)

    def rpc(self, name, data):
        if name == "search_public_profiles":
            query = data["p_query"].lower()
            return [{key: row.get(key) for key in ("id", "username", "display_name", "avatar_url")}
                    for row in self.rows["profiles"]
                    if row.get("username", "").lower().startswith(query) or query in row.get("display_name", "").lower()]
        if name == "is_username_available":
            username = data["p_username"].lower()
            return not any(row.get("username", "").lower() == username and row["id"] != self.user["id"]
                           for row in self.rows["profiles"])
        if name == "save_ai_trip":
            trip = self.insert("trips", data["p_trip"] | {"source": "ai"})
            itinerary = self.insert("itineraries", data["p_itinerary"] | {"trip_id": trip["id"]})
            return {"trip": trip, "itinerary_id": itinerary["id"]}
        return {"rpc": name, **data}


@pytest.fixture
def app():
    from app import create_app
    app = create_app({"TESTING": True, "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "test-key",
                      "SUPABASE_SERVICE_ROLE_KEY": "", "CORS_ORIGINS": ["http://localhost:3000"],
                      "GEMINI_API_KEY": "",
                      "SUPABASE_FACTORY": FakeSupabase})
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer valid-token"}
