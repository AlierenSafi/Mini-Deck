"""Upgrade v1 -> v2, preserving the current calibrated RAM before writing flash.
Enter ISP using ISP+RESET without unplugging power. Reserved sector 29 is backed up
before its first migration write. A mismatching old image/RAM never becomes calibration.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))
from protocol import encode
from firmware_package import validate
from isp import ISP, RAM

ROOT = Path(__file__).resolve().parents[1]
CAL_START = 0x78000
MAGIC = 0x324C4143


def points_valid(points):
    if len(points) != 6 or any(not 50 <= n <= 4045 for n in points):
        return False
    x0, y0, x1, y1, x2, y2 = points
    return abs((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)) > 50000


def pack_record(points):
    if not points_valid(points):
        raise ValueError("Invalid calibration points")
    header = struct.pack("<8I", MAGIC, 1, *points)
    return header + struct.pack("<I", zlib.crc32(header)) + b"\xff" * (256 - 36)


def valid_record(data):
    return (
        len(data) >= 36
        and struct.unpack_from("<2I", data) == (MAGIC, 1)
        and zlib.crc32(data[:32]) == struct.unpack_from("<I", data, 32)[0]
        and points_valid(struct.unpack_from("<6I", data, 8))
    )


def migrate(isp):
    source = ROOT / "backups/mini-deck-v1/mini-deck.bin"
    if not source.exists():
        return None
    old = source.read_bytes()
    # Exact v1 flashed program and determinant guard against stale/overwritten RAM.
    actual = isp.read(1024, len(old) - 1024)
    if actual != old[1024:]:
        print("Current image is not the saved v1; no RAM calibration migration.", flush=True)
        return None
    data = isp.read(0x10000348, 32)
    determinant, *points = struct.unpack("<q6i", data)
    if not points_valid(points):
        print(
            "No usable v1 RAM calibration; touch can be configured manually after recovery.",
            flush=True,
        )
        return None
    x0, y0, x1, y1, x2, y2 = points
    if determinant != (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0):
        print("RAM calibration determinant mismatch; calibration will not be imported.", flush=True)
        return None
    report = {
        "source": "verified v1 RAM at 0x10000348",
        "points": points,
        "determinant": determinant,
        "v1_sha256": hashlib.sha256(old).hexdigest(),
    }
    (ROOT / "build/calibration-migration.json").write_text(json.dumps(report, indent=2))
    print("Existing calibration verified and captured:", points, flush=True)
    return pack_record(points)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--image", type=Path, default=ROOT / "companion/firmware/mini-deck.bin")
    args = parser.parse_args()
    image = args.image.resolve()
    info = validate(image)
    data = image.read_bytes()
    if (
        not 1024 <= len(data) <= CAL_START
        or hashlib.sha256(data).hexdigest() != info["sha256"]
        or len(data) != info["image_bytes"]
    ):
        raise RuntimeError("Firmware package integrity check failed; flash unchanged.")
    if (
        sum(struct.unpack("<8I", data[:32])) & 0xFFFFFFFF
        or struct.unpack_from("<I", data, 0x2FC)[0] != 0xFFFFFFFF
    ):
        raise RuntimeError("Firmware vector/CRP check failed; flash unchanged.")
    (ROOT / "build").mkdir(exist_ok=True)
    (ROOT / "backups").mkdir(exist_ok=True)
    print("Firmware package SHA256 verified.", flush=True)
    isp = ISP(args.port, 9600)
    try:
        isp.sync()
        isp.identify()
        sector = isp.read(CAL_START, 32768)
        existing = next(
            (
                sector[i : i + 256]
                for i in range(32768 - 256, -1, -256)
                if valid_record(sector[i : i + 256])
            ),
            sector[:256],
        )
        record = migrate(isp)
        # Preserve any prior bytes in the reserved sector before migration erases it.
        if record and not valid_record(existing):
            backup = ROOT / "backups" / f"calibration-sector-before-v2-{time.time_ns()}.bin"
            backup.write_bytes(isp.read(CAL_START, 32768))
            print("Reserved-sector backup:", backup, flush=True)
        isp.flash(image)
        if record and not valid_record(existing):
            isp.write_ram(RAM, record)
            if isp.read(RAM, 256) != record:
                raise RuntimeError("Calibration RAM preflight mismatch")
            isp.command("U 23130")
            isp.command("P 29 29")
            isp.command("E 29 29")
            isp.command("P 29 29")
            isp.command(f"C {CAL_START} {RAM} 256")
            if isp.read(CAL_START, 256) != record:
                raise RuntimeError("Calibration flash verification failed")
            print("Calibration saved to dedicated flash sector and read back.", flush=True)
        elif valid_record(existing):
            print("Existing saved calibration retained.", flush=True)
        else:
            print(
                "No saved calibration. UI will open; hold both keys to configure touch.", flush=True
            )
        isp.reset()
        isp.s.timeout = 0.1
        deadline = time.monotonic() + 5
        output = bytearray()
        while time.monotonic() < deadline:
            output.extend(isp.s.read(512))
            if b"FLASH_CRC32=" in output and (
                b"R,3*" in output
                or b"R,4*" in output
                or b"R,5*" in output
                or b"R,6*" in output
                or b"R,7*" in output
                or b"R,8*" in output
                or b"R,9*" in output
                or b"R,10*" in output
            ):
                break
        (ROOT / "build/upgrade-v2-boot.log").write_bytes(output)
        if not re.search(rb"FLASH_CRC32=([0-9A-F]{8}) LEN=(\d+)", output):
            isp.s.write(encode("V"))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                output.extend(isp.s.read(1024))
                if re.search(rb"FLASH_CRC32=([0-9A-F]{8}) LEN=(\d+)", output):
                    break
        text = output.decode("ascii", errors="backslashreplace")
        (ROOT / "build/upgrade-v2-boot.log").write_text(text, encoding="utf-8")
        print(text, flush=True)
        match = re.search(r"FLASH_CRC32=([0-9A-F]{8}) LEN=(\d+)", text)
        if not match or match[1] != info["crc32"] or int(match[2]) != len(data):
            raise RuntimeError("Flash written, but runtime CRC verification did not pass.")
        report = {
            "full_image_matches": True,
            "runtime_crc32": match[1],
            "image_bytes": len(data),
            "port": args.port,
            "sha256": info["sha256"],
        }
        (ROOT / "build/runtime-verification.json").write_text(json.dumps(report, indent=2))
        print("FULL IMAGE CRC VERIFIED. UPDATE COMPLETE.", flush=True)
    finally:
        isp.s.close()


if __name__ == "__main__":
    main()
