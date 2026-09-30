"""Fail closed if the packaged image is damaged or older than local firmware sources."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_digest(root=ROOT):
    files = sorted(p for p in (root / "src").glob("*") if p.suffix in (".c", ".h", ".S"))
    files += [root / "lpc1768.ld", root / "tools/build.py"]
    digest = hashlib.sha256()
    for path in files:
        digest.update(
            path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0"
        )
    return digest.hexdigest()


# Fail before erase if the image or its corresponding source snapshot has changed.
def validate(image=None, root=ROOT):
    image = image or root / "companion/firmware/mini-deck.bin"
    info = json.loads(image.with_suffix(".json").read_text(encoding="utf-8"))
    data = image.read_bytes()
    if hashlib.sha256(data).hexdigest() != info["sha256"] or len(data) != info["image_bytes"]:
        raise RuntimeError("Firmware paketi bozuk; yükleme durduruldu.")
    if (root / "src").is_dir() and info.get("source_sha256") != source_digest(root):
        raise RuntimeError(
            "Firmware kaynakları paketten daha yeni. Önce build.ps1 çalıştırılmalı; eski yazılım yüklenmedi."
        )
    return info
