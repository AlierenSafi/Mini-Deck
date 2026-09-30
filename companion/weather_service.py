"""Optional Open-Meteo weather; bounded requests isolated from serial/telemetry."""

import json
import math
from pathlib import Path
import threading
import time
from urllib.parse import urlencode
from urllib.request import urlopen, Request

PATH = Path(__file__).with_name("weather-settings.json")


def request(base, params):
    with urlopen(
        Request(base + "?" + urlencode(params), headers={"User-Agent": "MiniDeck/9"}), timeout=8
    ) as response:
        return json.loads(response.read(262144))


def search(query):
    if not 2 <= len(query.strip()) <= 100:
        raise ValueError("En az iki harfle il veya ilçe ara.")
    result = request(
        "https://geocoding-api.open-meteo.com/v1/search",
        dict(name=query.strip(), count=8, language="tr", format="json"),
    )
    return [
        dict(
            name=", ".join(filter(None, [p["name"], p.get("admin1"), p.get("country")])),
            latitude=p["latitude"],
            longitude=p["longitude"],
        )
        for p in result.get("results", [])
    ][:8]


def load(path=PATH):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return {}
        lat = float(value["latitude"])
        lon = float(value["longitude"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return {}
        return dict(
            name=str(value["name"])[:160],
            latitude=lat,
            longitude=lon,
            enabled=value.get("enabled") is True,
        )
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def save(value, path=PATH):
    path = Path(path)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def fetch(config):
    data = request(
        "https://api.open-meteo.com/v1/forecast",
        dict(
            latitude=config["latitude"],
            longitude=config["longitude"],
            current="temperature_2m,weather_code,is_day",
            timezone="auto",
        ),
    )["current"]
    temp = float(data["temperature_2m"])
    code = int(data["weather_code"])
    if not math.isfinite(temp) or not -100 <= temp <= 100 or not 0 <= code <= 99:
        raise ValueError("Geçersiz hava verisi")
    # Wire: temperature + 100, WMO code; 255 denotes unavailable.
    return (round(temp) + 100, code, int(bool(data["is_day"])))


class Weather(threading.Thread):
    def __init__(self, path=PATH):
        super().__init__(daemon=True, name="deck-weather")
        self.path = path
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.value = (255, 255, 1)
        self.updated = 0
        self.config = {}

    def snapshot(self):
        with self.lock:
            return self.value if time.monotonic() - self.updated < 1800 else (255, 255, 1)

    def run(self):
        due = 0
        while not self.stop_event.is_set():
            config = load(self.path)
            now = time.monotonic()
            if config != self.config:
                self.config = config
                due = 0
                with self.lock:
                    self.value = (255, 255, 1)
                    self.updated = 0
            if config.get("enabled") and now >= due:
                try:
                    value = fetch(config)
                    with self.lock:
                        self.value = value
                        self.updated = time.monotonic()
                    due = now + 600
                except (OSError, ValueError, KeyError, TypeError):
                    due = now + 60
            self.stop_event.wait(1)

    def close(self):
        self.stop_event.set()
