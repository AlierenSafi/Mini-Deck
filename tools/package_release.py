"""Export only reviewed project files; local state is never discovered implicitly.

Run from a clean or actively used checkout. The same allowlist excludes API
settings, personal shortcuts, caches, compiler downloads and flash backups.
"""

from pathlib import Path
import hashlib
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "companion"))
from firmware_package import validate


def release_files():
    files = []
    for name in (
        "README.md",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        ".gitignore",
        ".clang-format",
        "pyproject.toml",
        "lpc1768.ld",
        "start-deck.ps1",
        "build.ps1",
    ):
        files.append(ROOT / name)
    for folder, suffixes in {
        "src": {".c", ".h", ".S"},
        "companion": {".py"},
        "tests": {".py"},
        "tools": {".py"},
    }.items():
        files.extend(p for p in (ROOT / folder).iterdir() if p.is_file() and p.suffix in suffixes)
    for name in (
        "companion/requirements.txt",
        "tests/requirements.txt",
        "companion/actions.example.json",
        "companion/mini-deck.ico",
        "companion/firmware/mini-deck.bin",
        "companion/firmware/mini-deck.json",
        "tools/presentmon/README.md",
        "tools/presentmon/LICENSE.txt",
        "tools/presentmon/PresentMon.exe",
        "third_party/roboto-mono/RobotoMono.ttf",
        "third_party/roboto-mono/OFL.txt",
        "third_party/roboto-mono/PROVENANCE.json",
        "docs/ARCHITECTURE.md",
        "docs/HARDWARE.md",
        "docs/monitor-preview.png",
        "docs/enclosure/README.md",
        "docs/enclosure/measurements.json",
        "docs/enclosure/cad-dependencies.txt",
        "docs/enclosure/01_body.stl",
        "docs/enclosure/02_bezel.stl",
        "docs/enclosure/02_bezel_v1.stl",
        "docs/enclosure/03_stand.stl",
        "docs/enclosure/04_fit_check.stl",
        "docs/enclosure/mini-deck-bezel-v1.3mf",
        "docs/enclosure/mini-deck-fit-check.3mf",
    ):
        files.append(ROOT / name)
    return sorted(set(files))


def main():
    validate(root=ROOT)
    files = release_files()
    # Reject accidental local paths even inside documentation or source comments.
    for path in files:
        if path.suffix in (".py", ".c", ".h", ".md", ".json", ".ps1"):
            text = path.read_text(encoding="utf-8").lower()
            text = text.replace("c:/users/public", "")  # Standard Windows shared desktop, not a personal path.
            for marker in ("c:/users/", "c:\\users\\", "e:/lpc1768-mini-dk2", "codex-clipboard-"):
                # This checker itself necessarily contains these generic patterns.
                if path.name != "package_release.py" and marker in text:
                    raise RuntimeError("Local path found in " + str(path.relative_to(ROOT)))
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archive = output / "Mini-Deck-GitHub.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        for path in files:
            package.write(path, "Mini-Deck/" + path.relative_to(ROOT).as_posix())
    report = dict(
        files=len(files),
        bytes=archive.stat().st_size,
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        paths=[p.relative_to(ROOT).as_posix() for p in files],
    )
    (output / "release-manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{archive.name}: {len(files)} files, {archive.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
