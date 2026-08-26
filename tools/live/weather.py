"""live.weather: current live weather conditions for a place, wrapped as a Tool.

Same dependency-injection pattern as tools/web/search.py - see
tools/base.py's "HOW TO ADD A NEW TOOL" for the full walkthrough.
"""
from tools.base import Permission, Tool


class LiveWeatherTool(Tool):
    name = "live.weather"
    description = (
        "Get the current live weather for a place: temperature, feels-like temperature, "
        "conditions (clear/rain/snow/etc.), humidity, and wind speed, observed right now - "
        "not a multi-hour forecast. Use for any question about current/today's weather."
    )
    parameters = {"location": "string - a city, region, or place name"}
    permission = Permission.SAFE

    def __init__(self, lookup_fn):
        self._lookup_fn = lookup_fn

    def execute(self, location):
        return self._lookup_fn(location)
