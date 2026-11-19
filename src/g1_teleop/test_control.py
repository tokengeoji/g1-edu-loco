# Author: Codex (IIC)
"""Tests exercise the same SDK methods that the terminal uses on G1."""
import unittest

from .control import CONFIRM_SECONDS, PULSE_SECONDS, Controller


class NativeClient:
    def __init__(self):
        self.state = 802
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

    def SetSpeedMode(self, value):
        self.calls.append(("speed", value))
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

    def request(self, key):
        self.control.handle(key)
        return self.control.handle("\r")

    def test_startup_idle_and_exit_are_passive(self):
        self.control.tick()
        self.control.close()
        self.assertEqual([], self.client.calls)
        self.assertIn("802", self.control.handle("f"))
        self.assertEqual([("read",)], self.client.calls)

    def test_unknown_negative_fsm_never_sends(self):
        self.client.state = -1
        self.assertIn("-1", self.control.handle("w"))
        self.request("2")
        self.assertEqual([("read",), ("read",)], self.client.calls)

    def test_old_enable_keys_have_no_function(self):
        self.control.handle("r")
        self.control.handle("g")
        self.assertEqual(self.client.calls, [])
        self.control.handle("w")
        self.assertEqual(self.client.calls[-1], ("velocity", .15, 0, 0, PULSE_SECONDS))

    def test_each_key_reads_actual_state_and_sends_one_finite_pulse(self):
        expected = {"w": (.15, 0, 0), "s": (-.15, 0, 0), "a": (0, .1, 0),
                    "d": (0, -.1, 0), "q": (0, 0, .3), "e": (0, 0, -.3)}
        for key, vector in expected.items():
            with self.subTest(key=key):
                self.client.calls.clear()
                self.control.handle(key)
                self.assertEqual(self.client.calls, [("read",), ("velocity", *vector, PULSE_SECONDS)])

    def test_fresh_key_extends_deadline_but_idle_only_zeros_once(self):
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
        self.client.on_read = lambda: self.advance(PULSE_SECONDS + .01)
        self.control.handle("w")
        self.assertEqual(self.client.calls, [("read",)])
        self.client.on_read = lambda: self.advance(.125)
        self.control.handle("w")
        self.assertEqual(self.client.calls[-1], ("velocity", .15, 0, 0, .125))

    def test_external_mode_change_stops_owned_motion(self):
        self.control.handle("e")
        self.client.state = 4
        self.control.handle("e")
        self.assertEqual(self.client.calls[-2:], [("read",), ZERO])

    def test_automatic_cleanup_only_touches_owned_motion(self):
        self.control.close()
        self.assertEqual(self.client.calls, [])
        self.control.handle(" ")
        self.assertEqual(self.client.calls, [ZERO])
        self.client.calls.clear()
        self.control.handle("d")
        self.control.close()
        self.control.close()
        self.assertEqual(self.client.calls.count(ZERO), 1)

    def test_confirmation_is_distinct_one_shot_and_expires(self):
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
        self.control.handle("q")
        self.control.handle("1")
        self.assertEqual(self.client.calls[-1], ZERO)
        result = self.control.handle("\r")
        self.assertIn("현재 FSM=802", result)
        self.assertIn("진입 미확인", result)
        self.client.calls.clear()
        self.control.handle("w")
        self.assertEqual([("read",)], self.client.calls)
        self.client.state = 4
        self.assertNotIn("미확인", self.control.handle("f"))
        self.control.handle("w")
        self.assertEqual(self.client.calls[-1], ("read",))

    def test_802_transition_requires_readback_and_never_falls_back_to_500(self):
        self.client.state = 500
        self.control.handle("w")
        self.assertEqual(self.client.calls, [("read",)])
        self.assertIn("진입 미확인", self.request("2"))
        self.control.handle("w")
        self.assertNotIn(("fsm", 500), self.client.calls)
        self.assertFalse(any(call[0] == "velocity" for call in self.client.calls))
        self.client.state = 802
        self.control.handle("w")
        self.assertEqual(self.client.calls[-1], ("velocity", .15, 0, 0, PULSE_SECONDS))

    def test_regular_walk_already_in_500_requires_deliberate_selection(self):
        self.client.state = 500
        self.assertIn("m", self.control.handle("w"))
        self.control.handle("m")
        self.control.handle("\x1b")
        self.control.handle("w")
        self.assertEqual(self.client.calls, [("read",), ("read",)])
        self.assertIn("선택됨", self.request("m"))
        self.control.handle("w")
        self.assertEqual(self.client.calls[-3:], [("read",), ("read",), ("velocity", .15, 0, 0, PULSE_SECONDS)])
        self.assertNotIn(("fsm", 500), self.client.calls)
        self.control.handle("@")
        self.assertEqual(self.client.calls[-1], ("read",))

    def test_regular_walk_requires_readback_and_forgets_an_observed_departure(self):
        self.assertIn("진입 미확인", self.request("m"))
        self.control.handle("w")
        self.assertEqual(self.client.calls, [("read",), ("fsm", 500), ("read",), ("read",)])
        self.client.state = 500
        self.control.handle("w")
        self.assertEqual(self.client.calls[-1], ("velocity", .15, 0, 0, PULSE_SECONDS))
        self.control.handle(" ")
        self.client.state = 4
        self.control.handle("f")
        self.client.state = 500
        self.client.calls.clear()
        self.control.handle("w")
        self.assertEqual(self.client.calls, [("read",)])
        self.client.state = 802
        self.control.handle("w")
        self.assertEqual(self.client.calls[-1], ("velocity", .15, 0, 0, PULSE_SECONDS))

    def test_refused_802_cancels_previous_500_selection(self):
        self.client.state = 500
        self.request("m")
        self.client.write_code = 23
        self.assertIn("23", self.request("2"))
        self.assertIn("802 진입 미확인", self.control.handle("w"))
        self.assertFalse(any(call[0] == "velocity" for call in self.client.calls))
        self.assertNotIn(("fsm", 500), self.client.calls)
        self.assertIn("선택됨", self.request("m"))
        self.control.handle("w")
        self.assertEqual(self.client.calls[-1], ("velocity", .15, 0, 0, PULSE_SECONDS))

    def test_refused_500_request_does_not_adopt_later_external_500(self):
        self.client.state = 4
        self.client.write_code = 12
        self.assertIn("12", self.request("m"))
        self.client.state = 500
        self.control.handle("w")
        self.assertEqual(self.client.calls, [("read",), ("fsm", 500), ("read",)])

    def test_waist_model_gate_for_request_movement_and_balance(self):
        self.request("8")
        self.assertEqual(self.client.calls, [])
        self.client.state = 501
        self.control.handle("w")
        self.request("5")
        self.assertEqual(self.client.calls, [("read",), ("read",)])
        self.control = Controller(self.client, waist_3dof=True, clock=lambda: self.now)
        self.client.state = 4
        self.request("8")
        self.client.state = 501
        self.control.handle("s")
        self.assertIn(("fsm", 501), self.client.calls)
        self.assertEqual(self.client.calls[-1], ("velocity", -.15, 0, 0, PULSE_SECONDS))

    def test_mode_requests_use_sdk_codes(self):
        self.client.state = 500
        for key, value in [("0", 1), ("1", 4), ("2", 802), ("3", 2), ("7", 3), ("9", 3)]:
            with self.subTest(key=key):
                self.client.calls.clear()
                self.request(key)
                self.assertEqual(self.client.calls, [("read",), ("fsm", value), ("read",)])
        self.control = Controller(self.client, clock=lambda: self.now)
        for key, value in [("4", 0), ("5", 1)]:
            with self.subTest(key=key):
                self.client.calls.clear()
                self.request(key)
                self.assertEqual(self.client.calls, [("read",), ("balance", value)])
        self.client.state = 4
        self.client.calls.clear()
        self.request("5")
        self.assertEqual(self.client.calls, [("read",)])

    def test_squat_toggle_is_not_automatically_repeated(self):
        self.request("6")
        self.control.handle("\r")
        self.control.handle("w")
        self.assertEqual(self.client.calls, [("read",), ("fsm", 706), ("read",)])
        self.request("2")
        self.assertEqual(self.client.calls[-3:], [("read",), ("fsm", 802), ("read",)])

    def test_does_not_override_user_control_mode(self):
        self.client.state = 1000
        self.request("0")
        self.control.handle("w")
        self.assertEqual(self.client.calls, [("read",), ("read",)])

    def test_velocity_failure_stops_and_waits_for_a_fresh_key(self):
        self.client.velocity_code = 23
        message = self.control.handle("q")
        self.assertIn("23", message)
        self.assertEqual(self.client.calls[-1], ZERO)
        self.client.calls.clear()
        self.client.velocity_code = 0
        self.advance(1.0)
        self.control.tick()
        self.assertEqual(self.client.calls, [])
        self.control.handle("q")
        self.assertEqual(self.client.calls[-1], ("velocity", 0, 0, .3, PULSE_SECONDS))

    def test_invalid_readback_stops_owned_motion(self):
        self.control.handle("a")
        self.client.state = None
        self.control.handle("d")
        self.assertEqual(self.client.calls[-2:], [("read",), ZERO])
        self.client.calls.clear()
        self.client.read_code = 8
        self.control.handle("w")
        self.assertEqual(self.client.calls, [("read",)])

    def test_uncertain_fsm_request_blocks_motion_until_verified(self):
        self.client.state = 500
        self.client.write_code = 12
        self.assertIn("12", self.request("2"))
        self.assertEqual(self.client.calls, [("read",), ("fsm", 802)])
        self.assertIn("미확인", self.control.handle("w"))
        self.assertEqual(self.client.calls[-1], ("read",))

    def test_running_speed_caps_send_sdk_modes_without_changing_velocity(self):
        for key, mode, limit in [("!", 0, 1.0), ("@", 1, 2.0), ("#", 2, 2.7), ("$", 3, 3.0)]:
            self.client.calls.clear()
            self.assertIn(f"{limit:.1f} m/s", self.control.handle(key))
            self.assertEqual(self.client.calls, [("read",), ("speed", mode)])
        self.control.handle("w")
        self.assertEqual(self.client.calls[-1], ("velocity", .15, 0, 0, PULSE_SECONDS))
        self.client.calls.clear()
        self.client.state = 500
        self.control.handle("$")
        self.assertEqual(self.client.calls, [("read",)])

    def test_balance_mode_is_not_used_in_802(self):
        self.request("5")
        self.assertEqual(self.client.calls, [("read",)])

    def test_speed_keys_have_limits_and_do_not_dispatch(self):
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
