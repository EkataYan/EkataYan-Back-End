from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

from app.config import ai_is_configured, load_config, validate_config
from app.services.ai_service import AIService
from app.utils.responses import APIError


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(load_config())
    if config:
        app.config.update(config)
    validate_config(app.config)

    # AI is optional. Do not construct its service unless every provider setting exists.
    app.extensions["ai_service"] = AIService(app.config) if ai_is_configured(app.config) else None

    from app.routes import register_routes
    register_routes(app)

    @app.get("/health")
    @app.get("/api/health")
    def health():
        return jsonify(success=True, status="healthy")

    @app.errorhandler(APIError)
    def api_error(error):
        response = jsonify(success=False, error={"code": error.code, "message": error.message})
        if error.status == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        return response, error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        return api_error(APIError(error.name.upper().replace(" ", "_"), error.name, error.code))

    @app.errorhandler(Exception)
    def unexpected_error(error):
        # Never include request bodies, headers, JWTs, configuration, or prompts here.
        source = "gemini_sdk" if type(error).__module__.startswith("google.genai") else "application"
        app.logger.exception(
            "Unhandled exception source=%s class=%s message=%s",
            source, type(error).__name__, str(error),
        )
        return api_error(APIError("INTERNAL_ERROR", "An unexpected error occurred.", 500))

    @app.after_request
    def headers(response):
        origin = request.headers.get("Origin")
        if origin in app.config["CORS_ORIGINS"]:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response.vary.add("Origin")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.teardown_appcontext
    def close_client(_error):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    return app
