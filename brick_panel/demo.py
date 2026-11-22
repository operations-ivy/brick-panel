"""Made-up data for trying the page on a laptop: python3 -m brick_panel --demo."""

from __future__ import annotations

import time


class DemoWeather:
    point = (0.0, 0.0)
    source = "demo"
    error = ""

    def __init__(self) -> None:
        self.updated = time.time()

    def current(self) -> dict:
        return {
            "temperature": 58.6,
            "condition": "LIGHT RAIN",
            "humidity": 87,
            "wind_mph": 9,
            "wind_from": "SW",
            "time": None,
        }

    def periods(self) -> list[dict]:
        return [
            {"name": "TONIGHT", "temperature": 49, "forecast": "RAIN SHOWERS LIKELY", "rain": 70, "day": False},
            {"name": "MONDAY", "temperature": 61, "forecast": "PARTLY SUNNY", "rain": 20, "day": True},
            {"name": "MONDAY NIGHT", "temperature": 44, "forecast": "MOSTLY CLEAR", "rain": None, "day": False},
            {"name": "TUESDAY", "temperature": 57, "forecast": "SUNNY", "rain": None, "day": True},
        ]

    def alerts(self) -> list:
        return []

    def age(self) -> float:
        return time.time() - self.updated

    def start(self) -> None:
        pass
