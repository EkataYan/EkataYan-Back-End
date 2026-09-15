import base64
import json
import os
from urllib.parse import urlparse

from dotenv import load_dotenv
from pathlib import Path

AI_CONFIG_KEYS = ("GEMINI_API_KEY",)


def load_config():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    names = ("SUPABASE_URL", "AI_PROVIDER", "AI_MODEL", "AI_TIMEOUT_SECONDS", "GEMINI_API_KEY",
             "WEATHER_API_KEY", "WEATHER_PROVIDER")
    config = {name: os.getenv(name, "").strip() for name in names}
    config["AI_PROVIDER"] = config["AI_PROVIDER"] or "gemini"
    config["AI_MODEL"] = config["AI_MODEL"] or "gemini-3.5-flash-lite"
    config["AI_TIMEOUT_SECONDS"] = config["AI_TIMEOUT_SECONDS"] or "60"
    config["WEATHER_PROVIDER"] = config["WEATHER_PROVIDER"] or "weatherapi"
    config["SUPABASE_KEY"] = next((os.getenv(name, "").strip() for name in (
        "SUPABASE_KEY", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY"
    ) if os.getenv(name, "").strip()), "")
    config.update(
        ENVIRONMENT=os.getenv("FLASK_ENV", "production"),
        DEBUG=os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true"),
        CORS_ORIGINS=[x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()],
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        MAX_FORM_MEMORY_SIZE=64 * 1024,
        MAX_FORM_PARTS=10,
    )
    return config


def supabase_config_error(config):
    """Return a safe configuration error without contacting Supabase."""
    missing = [k for k in ("SUPABASE_URL", "SUPABASE_KEY") if not config.get(k)]
    if missing:
        return "Missing required configuration: " + ", ".join(missing)
    parsed = urlparse(config["SUPABASE_URL"])
    local = parsed.hostname in ("localhost", "127.0.0.1")
    if not parsed.hostname or parsed.username or parsed.query or parsed.fragment or (
        parsed.scheme != "https" and not (parsed.scheme == "http" and local)
    ):
        return "SUPABASE_URL must be HTTPS (HTTP allowed only for local Supabase)."
    key = config["SUPABASE_KEY"]
    role = None
    try:
        payload = key.split(".")[1]
        role = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("role")
    except (IndexError, ValueError, TypeError, AttributeError):
        pass
    if key.startswith("sb_secret_") or role == "service_role":
        return "SUPABASE_KEY must be a publishable or anon key, not a privileged key."
    return None


def validate_config(config):
    """Validate process-wide security settings that must never be accepted."""
    if config.get("DEBUG") and config["ENVIRONMENT"] != "development":
        raise RuntimeError("FLASK_DEBUG is allowed only with FLASK_ENV=development.")
    if "*" in config["CORS_ORIGINS"]:
        raise RuntimeError("CORS_ORIGINS must contain explicit origins, not a wildcard.")


def ai_is_configured(config):
    """AI is an optional feature and is enabled only by a complete configuration."""
    return config.get("AI_PROVIDER", "").lower() == "gemini" and all(
        config.get(name) for name in AI_CONFIG_KEYS
    )
