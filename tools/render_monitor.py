"""Render actual ARM monitor code with sample values, no connected board required."""

import sys, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "companion"))
from test_firmware import Firmware
from test_game import feed
from monitor_wire import frames
from PIL import Image

out = Image.new("RGB", (720, 640))
for theme in (0, 1):
    for bank in range(3):
        fw = Firmware()
        fw.write("preferences", struct.pack("<I", theme))
        fw.write("page", struct.pack("<I", 2))
        fw.write("monitor_bank", struct.pack("<I", bank))
        feed(fw, "T,43,144,1")
        feed(fw, "M,13,49,68,2458,180,16,23")
        fw.write("history_count", struct.pack("<I", 60))
        fw.write("history", struct.pack("<300H", *([10 + i % 35 for i in range(300)])))
        for body in frames(
            dict(
                sensors=dict(
                    cpu_model="Ryzen 5 3600",
                    model="RTX 2060",
                    temp=49,
                    fan=0,
                    power=53900,
                    clock=1740,
                    vram_used=1.25 * 1024**3,
                    vram_total=6 * 1024**3,
                    ram_used=7.76 * 1024**3,
                    ram_total=15.91 * 1024**3,
                ),
                weather=(122, 0, 1),
            )
        ):
            feed(fw, body)
        fw.call("screen")
        out.paste(fw.image, (bank * 240, theme * 320))
out.resize((1440, 1280), Image.Resampling.NEAREST).save(ROOT / "docs/monitor-preview.png")
