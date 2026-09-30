import sys
from pathlib import Path
import queue
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))
from protocol import Decoder, encode, parse_event
from bridge import Bridge, EventHandler, Sampler
from actions import Actions, INPUT
import ctypes


class FakeActions:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def run(self, action, revision=None):
        self.calls.append(action)
        if self.fail:
            raise OSError("test failure")
        return str(action)


class ProtocolTests(unittest.TestCase):
    def test_crc_known_vector(self):
        self.assertEqual(encode("123456789"), b"@123456789*29B1\n")

    def test_fragmented_and_coalesced(self):
        wire = encode("R,1") + encode("E,21,11")
        decoder = Decoder()
        result = []
        for byte in wire:
            result.extend(decoder.feed(bytes([byte])))
        self.assertEqual(result, ["R,1", "E,21,11"])
        self.assertEqual(Decoder().feed(wire), result)

    def test_corruption_noise_overflow_resynchronization(self):
        decoder = Decoder()
        bad = encode("E,1,2").replace(b"E,1,2", b"E,1,3")
        wire = b"boot log\n" + bad + b"@" + b"x" * 10000 + b"\n@broken" + encode("R,1")
        self.assertEqual(decoder.feed(wire), ["R,1"])
        self.assertLessEqual(len(decoder.buffer), 96)

    def test_event_validation(self):
        for raw in (
            "E,0,1,1",
            "E,1,24,1",
            "E,1,-1,1",
            "E,4294967296,0,1",
            "E,+1,0,1",
            "E,1,2,0",
            "M,1,2",
            "E,1,a,1",
        ):
            self.assertIsNone(parse_event(raw), raw)
        self.assertEqual(parse_event("E,4294967295,17,1"), (4294967295, 17, 1))

    def test_duplicate_action_only_once(self):
        actions = FakeActions()
        handler = EventHandler(actions, lambda *args: None)
        self.assertEqual(handler.handle("E,8,1,1"), "K,8,1")
        self.assertEqual(handler.handle("E,8,1,1"), "K,8,1")
        self.assertEqual(actions.calls, [1])

    def test_failure_is_acknowledged_and_not_replayed(self):
        actions = FakeActions(fail=True)
        handler = EventHandler(actions, lambda *args: None)
        self.assertEqual(handler.handle("E,8,1,1"), "K,8,0")
        self.assertEqual(handler.handle("E,8,1,1"), "K,8,0")
        self.assertEqual(actions.calls, [1])

    def test_recent_sequence_cache_is_bounded(self):
        handler = EventHandler(FakeActions(), lambda *args: None)
        for seq in range(1, 200):
            handler.handle(f"E,{seq},0,1")
        self.assertEqual(len(handler.seen), 64)

    def test_default_actions_dry_run(self):
        actions = Actions(
            Path(__file__).resolve().parents[1] / "companion/actions.example.json", True
        )
        for i in range(6):
            self.assertTrue(actions.run(i).startswith("DENEME:"))
        for i in range(6, 24):
            with self.assertRaises(ValueError):
                actions.run(i)
        self.assertEqual(ctypes.sizeof(INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_live_metrics_ranges(self):
        sampler = Sampler()
        time.sleep(0.02)
        values = sampler.sample()
        self.assertEqual(len(values), 7)
        self.assertTrue(all(0 <= v <= 100 for v in values[:3]))
        self.assertTrue(all(0 <= v <= 999999 for v in values[3:5]))
        self.assertTrue(0 <= values[5] < 24 and 0 <= values[6] < 60)

    def test_serial_service_handshake_metrics_and_ack(self):
        stop = threading.Event()
        actions = FakeActions()

        class FakeSerial:
            def __init__(self):
                self.incoming = bytearray(
                    encode("E,90,0,1") + encode("R,3") + encode("E,1,5,1") + encode("E,1,5,1")
                )
                self.outgoing = []

            @property
            def in_waiting(self):
                return len(self.incoming)

            def read(self, count):
                time.sleep(0.002)
                result = bytes(self.incoming[:count])
                del self.incoming[:count]
                return result

            def write(self, data):
                bodies = Decoder().feed(data)
                self.outgoing.extend(bodies)
                if any(body.startswith("M,") for body in bodies):
                    stop.set()

        connection = FakeSerial()
        bridge = Bridge("FAKE", actions, queue.Queue(128), stop)
        watchdog = threading.Timer(2, stop.set)
        watchdog.start()
        try:
            bridge.serve(connection)
        finally:
            watchdog.cancel()
        self.assertEqual(actions.calls, [5])
        self.assertEqual(connection.outgoing[:2], ["K,1,1", "K,1,1"])
        self.assertTrue(any(body.startswith("M,") for body in connection.outgoing))


if __name__ == "__main__":
    unittest.main()
