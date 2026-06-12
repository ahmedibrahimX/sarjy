import sqlite3

import httpx
from openai.types.chat import ChatCompletionToolParam

from . import config

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes, as used by Open-Meteo.
WMO_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "drizzle",
    55: "dense drizzle",
    56: "freezing drizzle",
    57: "dense freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "heavy freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light rain showers",
    81: "rain showers",
    82: "violent rain showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with heavy hail",
}

TOOL_SCHEMAS: list[ChatCompletionToolParam] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g. 'Cairo' or 'San Francisco'",
                    }
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": (
                "Persist a lasting personal fact the user shared, so future "
                "sessions remember it. Use a short third-person statement, "
                "e.g. 'Favorite color is blue'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string", "description": "The fact to remember"}
                },
                "required": ["fact"],
            },
        },
    },
]


async def get_weather(
    http: httpx.AsyncClient, city: str, conn: sqlite3.Connection | None = None
) -> dict:
    """Geocode the city, then fetch current conditions.

    Returns a flat dict the LLM can read out; errors come back as
    {"error": ...} so the model can answer honestly instead of inventing data.
    City coordinates never change, so geocoding results are cached in SQLite
    behind OPT_GEOCODE_CACHE — a hit skips half the round-trips.
    """
    if not city.strip():
        return {"error": "no city given"}
    city_key = city.strip().lower()
    if not config.flags()["OPT_GEOCODE_CACHE"]:
        conn = None  # flag off: behave exactly like Phase 1
    place: dict | None = None
    if conn is not None:
        row = conn.execute(
            "SELECT name, country, latitude, longitude FROM geocode_cache WHERE city_key = ?",
            (city_key,),
        ).fetchone()
        if row:
            place = dict(row)
    if place is None:
        geo = await http.get(GEOCODE_URL, params={"name": city, "count": 1})
        geo.raise_for_status()
        results = geo.json().get("results") or []
        if not results:
            return {"error": f"could not find a city named '{city}'"}
        place = results[0]
        if conn is not None:
            conn.execute(
                "INSERT OR REPLACE INTO geocode_cache "
                "(city_key, name, country, latitude, longitude) VALUES (?, ?, ?, ?, ?)",
                (
                    city_key,
                    place.get("name"),
                    place.get("country"),
                    place["latitude"],
                    place["longitude"],
                ),
            )
            conn.commit()
    forecast = await http.get(
        FORECAST_URL,
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
        },
    )
    forecast.raise_for_status()
    current: dict = forecast.json().get("current") or {}
    code = current.get("weather_code")
    return {
        "city": place.get("name"),
        "country": place.get("country"),
        "conditions": WMO_CODES.get(code, "unknown") if isinstance(code, int) else "unknown",
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "humidity_pct": current.get("relative_humidity_2m"),
        "wind_kmh": current.get("wind_speed_10m"),
    }
