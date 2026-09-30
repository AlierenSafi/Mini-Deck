"""Portable profile backups include icons, never execute imported commands."""

import base64
import hashlib
import io
import json
from pathlib import Path
from PIL import Image
from actions import normalize_config
from icons import ROOT


def export_profile(path, items, images):
    assets = []
    for image in images:
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        assets.append(base64.b64encode(stream.getvalue()).decode("ascii"))
    Path(path).write_text(
        json.dumps({"version": 3, "slots": items, "images": assets}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def import_profile(path):
    source = Path(path)
    if source.stat().st_size > 2_000_000:
        raise ValueError("Profil dosyası çok büyük.")
    value = json.loads(source.read_text(encoding="utf-8-sig"))
    items = normalize_config(value)
    assets = value.get("images") if isinstance(value, dict) else None
    if assets is not None:
        if not isinstance(assets, list) or len(assets) != len(value.get("slots", [])):
            raise ValueError("Profil simge sayısı geçersiz.")
        prepared = []
        for encoded in assets:
            if not isinstance(encoded, str) or len(encoded) > 200_000:
                raise ValueError("Geçersiz profil simgesi.")
            raw = base64.b64decode(encoded, validate=True)
            with Image.open(io.BytesIO(raw)) as image:
                if image.width > 128 or image.height > 128:
                    raise ValueError("Profil simgesi en fazla 128 piksel olmalı.")
                buffer = io.BytesIO()
                image.convert("RGBA").save(buffer, format="PNG")
                prepared.append(buffer.getvalue())
        target = ROOT / "assets"
        target.mkdir(exist_ok=True)
        for item, data in zip(items, prepared):
            file = target / (hashlib.sha256(data).hexdigest()[:24] + ".png")
            file.write_bytes(data)
            item["icon"] = str(file.relative_to(ROOT))
    return items
