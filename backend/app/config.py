import base64
import json
import os
from urllib.parse import urlparse

from dotenv import load_dotenv
from pathlib import Path


def load_config():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    names = ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_ROLE_KEY", "AI_PROVIDER",
             "AI_API_KEY", "AI_BASE_URL", "AI_MODEL", "WEATHER_API_KEY", "WEATHER_PROVIDER")
    config = {name: os.getenv(name, "").strip() for name in names}
    config.update(
        ENVIRONMENT=os.getenv("FLASK_ENV", "production"),
        DEBUG=os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true"),
        CORS_ORIGINS=[x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()],
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        MAX_FORM_MEMORY_SIZE=64 * 1024,
        MAX_FORM_PARTS=10,
    )
    return config


def validate_config(config):
    missing = [k for k in ("SUPABASE_URL", "SUPABASE_KEY") if not config.get(k)]
    if missing:
        raise RuntimeError("Missing required configuration: " + ", ".join(missing))
    parsed = urlparse(config["SUPABASE_URL"])
    local = parsed.hostname in ("localhost", "127.0.0.1")
    if not parsed.hostname or parsed.username or parsed.query or parsed.fragment or (
        parsed.scheme != "https" and not (parsed.scheme == "http" and local)
    ):
        raise RuntimeError("SUPABASE_URL must be HTTPS (HTTP allowed only for local Supabase).")
    key = config["SUPABASE_KEY"]
    role = None
    try:
        payload = key.split(".")[1]
        role = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("role")
    except (IndexError, ValueError, TypeError, AttributeError):
        pass
    if key.startswith("sb_secret_") or role == "service_role" or key == config.get("SUPABASE_SERVICE_ROLE_KEY"):
        raise RuntimeError("SUPABASE_KEY must be a publishable or anon key, not a privileged key.")
    if config.get("DEBUG") and config["ENVIRONMENT"] != "development":
        raise RuntimeError("FLASK_DEBUG is allowed only with FLASK_ENV=development.")
    if "*" in config["CORS_ORIGINS"]:
        raise RuntimeError("CORS_ORIGINS must contain explicit origins, not a wildcard.")
