from flask import Blueprint, current_app, request
from app.services.weather_service import WeatherService
from app.utils.responses import success
from app.utils.validators import WeatherQuery, parse

bp = Blueprint("weather", __name__)


@bp.get("/weather")
def weather():
    query = parse(WeatherQuery, request.args.to_dict())
    data = WeatherService(current_app.config).forecast(query.latitude, query.longitude, query.date)
    return success(data)
