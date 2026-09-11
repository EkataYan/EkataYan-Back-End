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
        row = self.one(table, filters)
        row.update(data)
        return row

    def rpc(self, name, data):
        return {"rpc": name, **data}


@pytest.fixture
def app():
    from app import create_app
    app = create_app({"TESTING": True, "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "test-key",
                      "SUPABASE_SERVICE_ROLE_KEY": "", "CORS_ORIGINS": ["http://localhost:3000"],
                      "AI_API_KEY": "", "AI_BASE_URL": "", "AI_MODEL": "",
                      "SUPABASE_FACTORY": FakeSupabase})
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer valid-token"}
