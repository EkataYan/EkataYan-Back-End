import httpx

from app.utils.responses import APIError


class WeatherService:
    """Weather provider boundary; WeatherAPI is the initial adapter."""
    def __init__(self, config):
        self.config = config

    def forecast(self, latitude, longitude, forecast_date):
        if not self.config.get("WEATHER_API_KEY"):
            raise APIError("WEATHER_NOT_CONFIGURED", "Weather service is not configured yet.", 503)
        if self.config.get("WEATHER_PROVIDER", "weatherapi") != "weatherapi":
            raise APIError("WEATHER_PROVIDER_UNSUPPORTED", "The configured weather provider is not supported.", 503)
        try:
            response = httpx.get("https://api.weatherapi.com/v1/forecast.json",
                                 params={"key": self.config["WEATHER_API_KEY"], "q": f"{latitude},{longitude}", "dt": forecast_date.isoformat()},
                                 timeout=httpx.Timeout(15, connect=5), follow_redirects=False)
            response.raise_for_status()
            data = response.json()
            day = data["forecast"]["forecastday"][0]["day"]
            return {"location": data["location"]["name"], "date": forecast_date.isoformat(),
                    "condition": day["condition"]["text"], "icon": day["condition"].get("icon"),
                    "min_celsius": day["mintemp_c"], "max_celsius": day["maxtemp_c"],
                    "rain_chance": day.get("daily_chance_of_rain"), "uv_index": day.get("uv")}
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            raise APIError("WEATHER_UNAVAILABLE", "Weather information is temporarily unavailable.", 502) from None
