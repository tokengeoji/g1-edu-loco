# Author: Codex (IIC)
"""Offline tests for correlating high-level requests and gait state."""

import io
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from g1stairs.session import read_json, read_jsonl

from . import __main__ as monitor
from .teleop_trace import FSM_TOPIC, REQUEST_TOPICS, TeleopTrace, hg_sport_state_type
from .test_temperature import lowstate


def request(number, parameter, api=7105):
    identity = SimpleNamespace(id=number, api_id=api)
    return SimpleNamespace(header=SimpleNamespace(identity=identity), parameter=json.dumps(parameter))


class TraceTest(unittest.TestCase):
    def test_drop_invalid_and_missing_sources(self):
        stream = io.StringIO()
        trace = TeleopTrace(stream, capacity=1)
        sport, loco = REQUEST_TOPICS
        trace.receive(loco, request(1, {}, api=7001))
        trace.receive(sport, request(2, {"velocity": [0, 1, 2]}))
        fsm = SimpleNamespace(fsm_id=802, fsm_mode=0)
        trace.receive(FSM_TOPIC, fsm)
        trace.drain()
        trace.receive(FSM_TOPIC, fsm)
        trace.receive(FSM_TOPIC, fsm)
        trace.finish()
        trace.receive(FSM_TOPIC, fsm)
        self.assertEqual(trace.stats[sport]["invalid"], 1)
        self.assertEqual(trace.stats[loco]["received"], 0)
        self.assertEqual(trace.stats[FSM_TOPIC]["dropped"], 1)
        self.assertEqual(trace.stats[FSM_TOPIC]["received"], 3)
        self.assertEqual(trace.stats[FSM_TOPIC]["written"], 1)
        self.assertEqual(json.loads(stream.getvalue())["fsm_mode"], 0)

    def test_sdk_reader_payloads_and_short_recording(self):
        try:
            import unitree_sdk2py.core.channel as channel
        except (ImportError, OSError):
            self.skipTest("requires Unitree Python SDK; DDS transport is mocked")
        # Complete TypeIdentifier in the manufacturer's HG SportModeState_.hpp.
        self.assertEqual(hg_sport_state_type().__idl__.get_type_id().value.hex(),
                         "8c32bb556f4d30a5cc29211499d6")
        callbacks = {}
        subscribers = []

        def subscriber(topic, msg_type):
            reader = Mock()
            reader.Init.side_effect = lambda callback, count: callbacks.update({topic: callback})
            subscribers.append(reader)
            return reader

        def lowstate_wait(timeout):
            if callbacks and not lowstate_wait.first:
                # Deliver all events as the final LowState wait returns. The recorder
                # must flush them even without another LowState sample.
                sport, loco = REQUEST_TOPICS
                callbacks[FSM_TOPIC](SimpleNamespace(fsm_id=802, fsm_mode=0))
                callbacks[sport](request(123, {"velocity": [0.3, 0, 0], "duration": 1.0}))
                callbacks[FSM_TOPIC](SimpleNamespace(fsm_id=802, fsm_mode=1))
                callbacks[FSM_TOPIC](SimpleNamespace(fsm_id=802, fsm_mode=1))
                callbacks[loco](request(124, {"velocity": [0, 0, 0], "duration": 0.25}))
                return None
            lowstate_wait.first = False
            return 101, lowstate(1)

        lowstate_wait.first = True
        receiver = Mock()
        receiver.wait.side_effect = lowstate_wait
        receiver.snapshot.return_value = None, 0
        with tempfile.TemporaryDirectory() as directory:
            args = monitor.parser().parse_args([
                "record", "--with-teleop", "--seconds", "0.01", "--run", "walk", "--runs-dir", directory])
            with patch.object(channel, "ChannelSubscriber", side_effect=subscriber), \
                    patch.object(monitor, "subscribe", return_value=nullcontext()), \
                    patch.object(monitor, "Receiver", return_value=receiver):
                monitor.record(args)
            folder = Path(directory) / "walk/state"
            events = list(read_jsonl(folder / "teleop.jsonl"))
            self.assertEqual([e["topic"] for e in events],
                             [FSM_TOPIC, REQUEST_TOPICS[0], FSM_TOPIC, REQUEST_TOPICS[1]])
            self.assertEqual([e["fsm_mode"] for e in events if "fsm_mode" in e], [0, 1])
            self.assertEqual([(e["request_id"], e["velocity"], e["duration"]) for e in events if "api_id" in e],
                             [(123, [0.3, 0, 0], 1.0), (124, [0, 0, 0], 0.25)])
            self.assertTrue(all(isinstance(e["host_rx_monotonic_ns"], int) for e in events))
            manifest = read_json(folder / "manifest.json")
            self.assertEqual(manifest["teleop_trace"]["topics_without_samples"], [])
            self.assertEqual(manifest["teleop_trace"]["topics"][FSM_TOPIC]["received"], 3)
            self.assertEqual(manifest["sample_count"], 1)
        for sub in subscribers:
            sub.Close.assert_called_once()
