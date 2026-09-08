"""Supabase HTTP adapter. Each instance is request-scoped; no shared auth state.

Uses Auth, PostgREST and Storage directly, avoiding a second HTTP client stack.
Every database/storage request uses the caller's JWT and is subject to RLS.
"""
import httpx

from app.utils.responses import APIError


class SupabaseService:
    def __init__(self, config, token):
        self.client = httpx.Client(
            base_url=config["SUPABASE_URL"].rstrip("/"),
            headers={"apikey": config["SUPABASE_KEY"], "Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(20, connect=5), follow_redirects=False,
        )

    def close(self):
        self.client.close()

    def request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.RequestError:
            raise APIError("UPSTREAM_UNAVAILABLE", "Supabase is temporarily unavailable.", 503) from None
        if response.is_error:
            try:
                code = response.json().get("code", "")
            except (ValueError, AttributeError):
                code = ""
            if response.status_code == 401:
                raise APIError("UNAUTHORIZED", "Invalid or expired access token.", 401)
            if response.status_code == 403 or code == "42501":
                raise APIError("FORBIDDEN", "You do not have permission for this action.", 403)
            if response.status_code == 409 or code in ("23505", "23503"):
                raise APIError("CONFLICT", "The record conflicts with existing data or references.", 409)
            if code in ("23514", "22023", "22P02"):
                raise APIError("INVALID_REQUEST", "The data violates a database constraint.", 422)
            if response.status_code == 429:
                raise APIError("RATE_LIMITED", "Too many requests. Try again later.", 429)
            raise APIError("UPSTREAM_ERROR", "Supabase could not complete the request.", 502)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise APIError("UPSTREAM_ERROR", "Supabase returned an invalid response.", 502) from None

    def get_user(self):
        user = self.request("GET", "/auth/v1/user")
        if not isinstance(user, dict) or not user.get("id"):
            raise APIError("UNAUTHORIZED", "Invalid or expired access token.", 401)
        return user

    def select(self, table, filters=None, select="*", limit=50, offset=0, order="created_at.desc,id.desc"):
        params = {"select": select, "limit": str(limit), "offset": str(offset), "order": order}
        params.update({k: f"eq.{v}" for k, v in (filters or {}).items()})
        return self.request("GET", f"/rest/v1/{table}", params=params)

    def one(self, table, filters, select="*"):
        rows = self.select(table, filters, select, limit=1)
        if not rows:
            raise APIError("NOT_FOUND", "Resource not found or not accessible.", 404)
        return rows[0]

    def insert(self, table, data):
        rows = self.request("POST", f"/rest/v1/{table}", json=data, headers={"Prefer": "return=representation"})
        return rows[0]

    def update(self, table, filters, data):
        rows = self.request("PATCH", f"/rest/v1/{table}", json=data,
                            params={k: f"eq.{v}" for k, v in filters.items()},
                            headers={"Prefer": "return=representation"})
        if not rows:
            raise APIError("NOT_FOUND", "Resource not found or not accessible.", 404)
        return rows[0]

    def delete(self, table, filters):
        rows = self.request("DELETE", f"/rest/v1/{table}",
                            params={k: f"eq.{v}" for k, v in filters.items()},
                            headers={"Prefer": "return=representation"})
        if not rows:
            raise APIError("NOT_FOUND", "Resource not found or not accessible.", 404)

    def rpc(self, name, data):
        return self.request("POST", f"/rest/v1/rpc/{name}", json=data)
