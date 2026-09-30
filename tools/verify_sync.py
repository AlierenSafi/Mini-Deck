"""Measure acknowledged transfers on a running v6 card; preserve the saved profile.

Close the companion first. No PC actions execute. The temporary label is restored
in finally; a subsequent companion connection also restores the saved profile.
"""

import argparse
import copy
import json
from pathlib import Path
import queue
import sys
import threading
import time
import serial

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "companion"))
from actions import Actions
from icons import AssetWorker
from protocol import Decoder, encode
from sync import Sync


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    args = parser.parse_args()
    events = queue.Queue()
    stop = threading.Event()
    worker = AssetWorker(
        Actions(ROOT / "companion/actions.json", True), lambda k, v: events.put((k, v)), stop
    )
    worker.start()
    try:
        while True:
            kind, layout = events.get(timeout=30)
            if kind == "layout":
                break
    finally:
        stop.set()
    decoder = Decoder()
    with serial.Serial(args.port, 115200, timeout=0.005, write_timeout=0.5) as port:

        def diagnostics():
            port.write(encode("Q"))
            end = time.monotonic() + 3
            while time.monotonic() < end:
                for body in decoder.feed(port.read(max(1, port.in_waiting))):
                    if body.startswith("D,"):
                        return list(map(int, body.split(",")[1:]))
            raise RuntimeError("Card did not answer diagnostics")

        before = diagnostics()
        if before[2] < 6:
            raise RuntimeError("v6 firmware required")

        def transfer(sync):
            start = time.monotonic()
            sent = 0
            while not sync.done:
                if time.monotonic() - start > 90 or sync.failed:
                    raise RuntimeError("Transfer failed")
                packet = sync.next_packet()
                if packet:
                    port.write(packet)
                    sent += 1
                for body in decoder.feed(port.read(max(1, port.in_waiting))):
                    sync.acknowledge(body)
            return dict(
                seconds=round(time.monotonic() - start, 3),
                packets=len(sync.jobs),
                retries=sent - len(sync.jobs),
            )

        result = {"before": before}
        try:
            result["legacy_full"] = transfer(Sync(layout, version=5))
            print("Legacy:", result["legacy_full"], flush=True)
            result["v6_full"] = transfer(Sync(layout, version=6))
            print("Full v6:", result["v6_full"], flush=True)
            changed = copy.deepcopy(layout)
            changed["revision"] = layout["revision"] ^ 1 or 2
            index = next(i for i, item in enumerate(changed["items"]) if item["type"] != "empty")
            changed["items"][index]["label"] = "SYNC TEST"
            result["v6_single_slot"] = transfer(Sync(changed, layout, 6))
            print("Single slot:", result["v6_single_slot"], flush=True)
        finally:
            result["restore"] = transfer(Sync(layout, version=6))
        result["after"] = diagnostics()
        if (
            result["after"][0] != before[0]
            or result["after"][3] != layout["revision"]
            or result["after"][4]
        ):
            raise RuntimeError("Diagnostic verification failed")
        (ROOT / "build/sync-verification.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        print("Profile restored; no new UART errors.", flush=True)


if __name__ == "__main__":
    main()
