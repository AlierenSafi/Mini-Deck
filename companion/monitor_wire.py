"""v9 extension: bounded unsigned values; explicit unknowns, sanitized names."""

import re
import unicodedata


def label(value):
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub("[^a-zA-Z0-9 .()+/-]", " ", value)[:26].ljust(26)


def number(value, divisor=1, maximum=999999):
    if value is None:
        return 999999
    try:
        n = round(value / divisor)
        return n if 0 <= n < maximum else 999999
    except (TypeError, ValueError, OverflowError):
        return 999999


def frames(perf):
    s = perf.get("sensors", {})
    w = perf.get("weather", (255, 255, 1))
    values = [
        number(s.get("temp"), maximum=201),
        number(s.get("fan"), maximum=101),
        number(s.get("power"), 100, 20001),
        number(s.get("clock"), maximum=20001),
        number(s.get("vram_used"), 1024**3 / 100),
        number(s.get("vram_total"), 1024**3 / 100),
    ]
    ram = [number(s.get("ram_used"), 1024**3 / 100), number(s.get("ram_total"), 1024**3 / 100)]
    return [
        "S," + ",".join(map(str, values)),
        "L," + ",".join(map(str, ram)),
        "O," + ",".join(map(str, w)),
        "I,0," + label(s.get("cpu_model", "CPU")),
        "I,1," + label(s.get("model", "GPU")),
    ]
