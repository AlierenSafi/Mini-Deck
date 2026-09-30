"""Build a standalone Cortex-M3 image, patch LPC checksum, emit BIN + Intel HEX."""

from pathlib import Path
import hashlib
import json
import os
import shutil
import struct
import subprocess
import zlib
import sys

root = Path(__file__).resolve().parent.parent
os.chdir(root)
sys.path.insert(0, str(root / "companion"))
from firmware_package import source_digest

gcc = shutil.which("arm-none-eabi-gcc")
if not gcc:
    gcc = next((str(p) for p in (root / "tools/arm").rglob("arm-none-eabi-gcc.exe")), None)
if not gcc:
    raise SystemExit("Install Arm GNU Toolchain and add arm-none-eabi-gcc to PATH; see README.md.")
prefix = str(Path(gcc).parent / "arm-none-eabi-")
out = root / "build"
out.mkdir(exist_ok=True)
flags = [
    "-mcpu=cortex-m3",
    "-mthumb",
    "-Os",
    "-g3",
    "-std=c11",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-ffreestanding",
    "-fno-builtin",
    "-ffunction-sections",
    "-fdata-sections",
    "-fstack-usage",
]
objects = []
for src in sorted((root / "src").glob("*")):
    if src.suffix not in (".c", ".S"):
        continue
    obj = out / (src.stem + ".o")
    objects.append(str(obj))
    subprocess.run([gcc, *flags, "-c", str(src), "-o", str(obj)], check=True)
elf = out / "mini-deck.elf"
subprocess.run(
    [
        gcc,
        "-mcpu=cortex-m3",
        "-mthumb",
        "-nostdlib",
        "-T",
        "lpc1768.ld",
        "-Wl,--gc-sections,-Map=build/mini-deck.map",
        *objects,
        "-lgcc",
        "-o",
        str(elf),
    ],
    check=True,
)
subprocess.run(
    [prefix + "objcopy", "-O", "binary", str(elf), str(out / "mini-deck.raw.bin")], check=True
)
data = bytearray((out / "mini-deck.raw.bin").read_bytes())
words = struct.unpack("<8I", data[:32])
checksum = (-sum(words[:7])) & 0xFFFFFFFF
struct.pack_into("<I", data, 28, checksum)
assert sum(struct.unpack("<8I", data[:32])) & 0xFFFFFFFF == 0
assert struct.unpack_from("<I", data, 0x2FC)[0] == 0xFFFFFFFF
# Keep ELF, BIN and HEX vector checksums identical for debugger/Flash Magic use.
(out / "vectors.bin").write_bytes(data[:204])
subprocess.run(
    [prefix + "objcopy", "--update-section", ".vectors=" + str(out / "vectors.bin"), str(elf)],
    check=True,
)
(out / "mini-deck.bin").write_bytes(data)
subprocess.run([prefix + "objcopy", "-O", "ihex", str(elf), str(out / "mini-deck.hex")], check=True)
subprocess.run([prefix + "size", str(elf)], check=True)
info = {
    "version": 10,
    "ui_theme": "alieren-mint-stone-1",
    "source_sha256": source_digest(root),
    "image_bytes": len(data),
    "sha256": hashlib.sha256(data).hexdigest(),
    "crc32": f"{zlib.crc32(data):08X}",
    "vector_checksum": hex(checksum),
    "crp": "disabled (0xffffffff)",
    "compiler": subprocess.check_output([gcc, "--version"], text=True).splitlines()[0],
    "flags": flags,
}
(out / "build-info.json").write_text(json.dumps(info, indent=2))
print(json.dumps(info, indent=2))

# Recovery image is bundled with the desktop companion; manifest checked before erase.
bundle = root / "companion/firmware"
bundle.mkdir(exist_ok=True)
(bundle / "mini-deck.bin").write_bytes(data)
(bundle / "mini-deck.json").write_text(json.dumps(info, indent=2))
