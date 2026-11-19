# Author: Codex (IIC)
"""Tests exercise the same SDK methods that the terminal uses on G1."""
import unittest

from .control import CONFIRM_SECONDS, PULSE_SECONDS, Controller


class NativeClient:
    def __init__(self):
        self.state = 500
        self.read_code = self.write_code = self.velocity_code = 0
        self.on_read = lambda: None
        self.calls = []

    def GetFsmId(self):
        self.calls.append(("read",))
        self.on_read()
        return self.read_code, self.state

    def SetFsmId(self, value):
        # Real firmware can change FSM after the request returns.
        self.calls.append(("fsm", value))
        return self.write_code

    def SetBalanceMode(self, value):
        self.calls.append(("balance", value))
        return self.write_code

    def SetVelocity(self, vx, vy, yaw, duration):
        self.calls.append(("velocity", vx, vy, yaw, duration))
        return self.velocity_code


ZERO = ("velocity", 0.0, 0.0, 0.0, PULSE_SECONDS)


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.now = 8.0
        self.client = NativeClient()
        self.control = Controller(self.client, clock=lambda: self.now)

    def advance(self, amount):
        self.now += amount

    def arm(self):
        self.control.handle("r")
        self.assertTrue(self.control.armed)
        self.client.calls.clear()

    def request(self, key):
        self.control.handle(key)
        return self.control.handle("\r")

    def test_startup_idle_and_exit_are_passive(self):
        self.control.handle("w")
        self.request("2")
        self.control.tick()
        self.control.close()
        self.assertEqual([], self.client.calls)
        self.assertIn("500", self.control.handle("f"))
        self.assertEqual([("read",)], self.client.calls)

    def test_unknown_negative_fsm_never_arms_or_sends(self):
        self.client.state = -1
        self.assertIn("-1", self.control.handle("r"))
        self.request("2")
        self.control.handle("w")
        self.assertFalse(self.control.armed)
        self.assertEqual([("read",)], self.client.calls)

    def test_each_key_reads_actual_state_and_sends_one_finite_pulse(self):
        self.arm()
        expected = {"w": (.15, 0, 0), "s": (-.15, 0, 0), "a": (0, .1, 0),
                    "d": (0, -.1, 0), "q": (0, 0, .3), "e": (0, 0, -.3)}
        for key, vector in expected.items():
            with self.subTest(key=key):
                self.client.calls.clear()
                self.control.handle(key)
                self.assertEqual(self.client.calls, [("read",), ("velocity", *vector, PULSE_SECONDS)])

    def test_fresh_key_extends_deadline_but_idle_only_zeros_once(self):
        self.arm()
        self.control.handle("w")
        self.advance(.125)
        self.control.tick()
        self.control.handle("w")
        self.advance(.20)
        self.control.tick()
        self.assertNotIn(ZERO, self.client.calls)
        self.advance(.10)
        self.control.tick()
        self.control.tick()
        self.control.close()
        self.assertEqual(self.client.calls.count(ZERO), 1)
        self.assertEqual(self.client.calls[-1], ZERO)

    def test_slow_lookup_cannot_replay_expired_movement(self):
        self.arm()
        self.client.on_read = lambda: self.advance(PULSE_SECONDS + .01)
        self.control.handle("w")
        self.assertEqual(self.client.calls, [("read",)])
        self.client.on_read = lambda: self.advance(.125)
        self.control.handle("w")
        self.assertEqual(self.client.calls[-1], ("velocity", .15, 0, 0, .125))

    def test_external_mode_change_stops_owned_motion(self):
        self.arm()
        self.control.handle("e")
        self.client.state = 4
        self.control.handle("e")
        self.assertEqual(self.client.calls[-2:], [("read",), ZERO])

    def test_automatic_cleanup_only_touches_owned_motion(self):
        self.arm()
        self.control.close()
        self.assertEqual(self.client.calls, [])
        self.control.handle(" ")
        self.assertEqual(self.client.calls, [ZERO])
        self.arm()
        self.control.handle("d")
        self.control.handle("g")
        self.assertFalse(self.control.armed)
        self.control.close()
        self.assertEqual(self.client.calls.count(ZERO), 1)

    def test_confirmation_is_distinct_one_shot_and_expires(self):
        self.arm()
        self.control.handle("0")
        self.advance(CONFIRM_SECONDS / 2)
        self.control.handle("0")
        self.advance(CONFIRM_SECONDS / 2)
        self.control.handle("\r")
        self.assertEqual(self.client.calls, [])
        for cancel in ("\x1b", "w", "?"):
            self.control.handle("0")
            self.control.handle(cancel)
            self.control.handle("\r")
        self.assertEqual(self.client.calls, [])
        self.control.handle("0")
        self.control.handle("0")
        self.control.handle("\r")
        self.control.handle("\r")
        self.assertEqual(self.client.calls, [("read",), ("fsm", 1), ("read",)])

    def test_requested_mode_gates_motion_until_actual_readback(self):
        self.arm()
        self.control.handle("q")
        self.control.handle("1")
        self.assertEqual(self.client.calls[-1], ZERO)
        result = self.control.handle("\r")
        self.assertIn("현재 FSM=500", result)
        self.assertIn("진입 미확인", result)
        self.client.calls.clear()
        self.control.handle("r")
        self.control.handle("w")
        self.assertEqual([("read",), ("read",)], self.client.calls)
        self.client.state = 4
        self.assertNotIn("미확인", self.control.handle("f"))
        self.control.handle("w")
        self.assertEqual(self.client.calls[-1], ("read",))

    def test_asynchronous_transition_observed_during_first_balance_command(self):
        self.arm()
        self.client.state = 4
        self.request("2")
        self.client.state = 500
        self.request("4")
        self.assertEqual(self.client.calls[-1], ("balance", 0))

    def test_waist_model_gate_for_request_movement_and_balance(self):
        self.arm()
        self.request("8")
        self.assertEqual(self.client.calls, [])
        self.client.state = 501
        self.control.handle("w")
        self.request("5")
        self.assertEqual(self.client.calls, [("read",), ("read",)])
        self.control = Controller(self.client, waist_3dof=True, clock=lambda: self.now)
        self.arm()
        self.request("8")
        self.control.handle("s")
        self.assertIn(("fsm", 501), self.client.calls)
        self.assertEqual(self.client.calls[-1], ("velocity", -.15, 0, 0, PULSE_SECONDS))

    def test_mode_requests_use_sdk_codes(self):
        self.arm()
        for key, value in [("0", 1), ("1", 4), ("2", 500), ("3", 2), ("7", 3), ("9", 3)]:
            with self.subTest(key=key):
                self.client.calls.clear()
                self.request(key)
                self.assertEqual(self.client.calls, [("read",), ("fsm", value), ("read",)])
        self.request("2")
        for key, value in [("4", 0), ("5", 1)]:
            with self.subTest(key=key):
                self.client.calls.clear()
                self.request(key)
                self.assertEqual(self.client.calls, [("read",), ("balance", value)])
        self.client.state = 4
        self.client.calls.clear()
        self.request("5")
        self.assertEqual(self.client.calls, [("read",)])

    def test_squat_toggle_sent_once_and_requires_rearm(self):
        self.arm()
        self.request("6")
        self.control.handle("\r")
        self.request("6")
        self.control.handle("w")
        self.assertFalse(self.control.armed)
        self.assertEqual(self.client.calls, [("read",), ("fsm", 706)])

    def test_does_not_override_user_control_mode(self):
        self.client.state = 1000
        self.control.handle("r")
        self.assertFalse(self.control.armed)
        self.client.state = 500
        self.arm()
        self.control.handle("0")
        self.client.state = 1000
        self.control.handle("\r")
        self.assertFalse(self.control.armed)
        self.assertEqual(self.client.calls, [("read",)])

    def test_velocity_failure_stops_and_requires_rearm(self):
        self.arm()
        self.client.velocity_code = 23
        message = self.control.handle("q")
        self.assertIn("23", message)
        self.assertEqual(self.client.calls[-1], ZERO)
        self.assertFalse(self.control.armed)
        self.client.calls.clear()
        self.client.velocity_code = 0
        self.control.handle("q")
        self.assertEqual(self.client.calls, [])
        self.arm()
        self.control.handle("q")
        self.assertEqual(self.client.calls[-1], ("velocity", 0, 0, .3, PULSE_SECONDS))

    def test_invalid_readback_disarms_and_stops_if_owned(self):
        self.arm()
        self.control.handle("a")
        self.client.state = None
        self.control.handle("d")
        self.assertFalse(self.control.armed)
        self.assertEqual(self.client.calls[-2:], [("read",), ZERO])
        self.client.calls.clear()
        self.client.read_code = 8
        self.control.handle("r")
        self.assertFalse(self.control.armed)
        self.assertEqual(self.client.calls, [("read",)])

    def test_mode_write_error_disarms_and_never_reports_confirmation(self):
        self.arm()
        self.client.write_code = 12
        self.assertIn("12", self.request("2"))
        self.assertFalse(self.control.armed)
        self.assertEqual(self.client.calls, [("read",), ("fsm", 500)])

    def test_speed_keys_have_limits_and_do_not_dispatch(self):
        self.arm()
        for _ in range(10):
            self.control.handle("+")
        self.assertEqual(self.client.calls, [])
        self.control.handle("q")
        self.assertEqual(self.client.calls[-1], ("velocity", 0, 0, .6, PULSE_SECONDS))
        self.client.calls.clear()
        for _ in range(10):
            self.control.handle("-")
        self.assertEqual(self.client.calls, [])
        self.control.handle("d")
        self.assertEqual(self.client.calls[-1], ("velocity", 0, -.05, 0, PULSE_SECONDS))


if __name__ == "__main__":
    unittest.main()
