# Author: Codex (IIC)
"""Tests exercise the same SDK methods that the terminal uses on G1."""
import unittest
from unittest.mock import Mock

from .control import CONFIRM_SECONDS, PULSE_SECONDS, REPEAT_INTERVAL, Controller, EndSession


class NativeClient:
    def __init__(self):
        self.state = 802
        self.read_code = self.write_code = self.velocity_code = 0
        self.on_read = lambda: None
        self.calls = []
        self.wrapper_calls = []

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

    def Move(self, vx, vy, yaw):
        self.wrapper_calls.append(("Move", vx, vy, yaw))
        return self.SetVelocity(vx, vy, yaw, 1) or None

    def StopMove(self):
        self.wrapper_calls.append(("StopMove",))
        return self.SetVelocity(0, 0, 0, 1) or None


ZERO = ("velocity", 0.0, 0.0, 0.0, PULSE_SECONDS)


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.now = 8.0
        self.client = NativeClient()
        self.control = Controller(self.client, clock=lambda: self.now)

    def advance(self, amount):
        self.now += amount

    def use_timed_velocity(self):
        self.control = Controller(self.client, timed_velocity=True, clock=lambda: self.now)

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
        self.assertIn("-1", self.control.handle("i"))
        self.request("2")
        self.assertEqual([("read",), ("read",)], self.client.calls)

    def test_old_enable_keys_have_no_function(self):
        self.control.handle("r")
        self.control.handle("g")
        self.assertEqual(self.client.calls, [])
        self.control.handle("i")
        self.assertEqual(self.client.calls[-1], ("velocity", .30, 0, 0, PULSE_SECONDS))

    def test_each_key_reads_actual_state_and_sends_one_finite_pulse(self):
        expected = {
            "u": (.15, 0, .3), "i": (.30, 0, 0), "o": (.15, 0, -.3),
            "j": (0, 0, .3), "l": (0, 0, -.3),
            "m": (-.15, 0, -.3), ",": (-.30, 0, 0), ".": (-.15, 0, .3),
            "U": (.15, .1, 0), "I": (.30, 0, 0), "O": (.15, -.1, 0),
            "J": (0, .1, 0), "L": (0, -.1, 0),
            "M": (-.15, .1, 0), "<": (-.30, 0, 0), ">": (-.15, -.1, 0),
        }
        for key, vector in expected.items():
            with self.subTest(key=key):
                self.client.calls.clear()
                self.control.handle(key)
                self.assertEqual(self.client.calls, [("read",), ("velocity", *vector, PULSE_SECONDS)])
                self.assertEqual(self.client.wrapper_calls[-1], ("Move", *vector))

    def test_stock_move_tap_checks_fsm_until_expiry_without_resending(self):
        start = self.now
        self.client.on_read = lambda: self.advance(.15)
        move = self.control.handle("i")
        self.assertIn("Move(7105) 수락", move)
        self.assertIn("SDK 명령 1초 · 입력 만료까지 0.85초", move)
        self.client.on_read = lambda: None
        self.now = start + .5
        self.control.tick()
        self.control.tick()
        self.now = start + .75
        self.control.tick()
        self.assertEqual(self.client.calls, [("read",), ("velocity", .30, 0, 0, 1), ("read",), ("read",)])
        self.now = start + 1
        self.assertIn("이동 입력 1회 · 속도 RPC 수락 1회", self.control.tick())
        self.control.tick()
        self.control.close()
        self.assertEqual(self.client.wrapper_calls, [("Move", .30, 0, 0), ("StopMove",)])

    def test_stock_real_repeat_rate_limit_and_read_only_poll_are_independent(self):
        self.control.handle("i")
        self.advance(.05)
        self.control.handle("i")
        self.assertEqual(self.client.wrapper_calls, [("Move", .30, 0, 0)])
        self.advance(.06)
        self.control.tick()
        self.advance(.01)
        self.control.handle("i")
        self.control.handle("o")
        self.assertEqual(self.client.wrapper_calls, [("Move", .30, 0, 0), ("Move", .30, 0, 0),
                                                    ("Move", .15, 0, -.3)])
        self.advance(.3)
        self.control.tick()
        self.assertIn("이동 입력 4회 · 속도 RPC 수락 3회", self.control.close())

    def test_stock_replayed_input_does_not_issue_a_new_full_second_pulse(self):
        start = self.now
        self.control.handle("i", received_at=start)
        self.advance(.4)
        self.control.handle("i", received_at=start)
        self.control.handle("k")
        self.advance(.1)
        self.control.handle("i", received_at=start+.1)
        self.control.tick()
        self.assertEqual(self.client.wrapper_calls, [("Move", .30, 0, 0), ("StopMove",)])
        self.client.on_read = lambda: self.advance(1.1)
        self.assertIn("만료", self.control.handle(","))
        self.assertEqual(len(self.client.wrapper_calls), 2)

    def test_stock_slow_timer_read_stops_on_expiry_or_changed_fsm(self):
        for state, read_time in [(802, 1.0), (801, .01)]:
            with self.subTest(state=state):
                client = NativeClient()
                control = Controller(client, clock=lambda: self.now)
                control.handle(",")
                self.advance(.2)
                client.state = state
                client.on_read = lambda: self.advance(read_time)
                self.assertIsNotNone(control.tick())
                self.assertEqual(client.wrapper_calls, [("Move", -.30, 0, 0), ("StopMove",)])
                self.assertIsNone(control.tick())

    def test_stock_wrapper_errors_trigger_stop_and_close_retries_only_stop(self):
        for failure in (24, RuntimeError("SetVelocity(7105) RPC code=24")):
            with self.subTest(failure=failure):
                client = NativeClient()
                control = Controller(client, clock=lambda: self.now)
                client.Move = Mock(side_effect=[failure])
                self.assertIn("24", control.handle("i"))
                client.Move.assert_called_once_with(.30, 0, 0)
                self.assertEqual(client.wrapper_calls, [("StopMove",)])
                self.advance(.2)
                self.assertIsNone(control.tick())
                client.StopMove = Mock(side_effect=[RuntimeError("lost stop reply"), None])
                self.assertIn("속도 0 요청 수락", control.close(force_stop=True))
                self.assertEqual(client.StopMove.call_count, 2)

    def test_stock_suppresses_command_if_stop_arrives_during_read(self):
        self.control.handle("J", cancel_requested=lambda: True)
        self.assertEqual(self.client.calls, [("read",)])
        self.control.handle("k")
        self.assertEqual(self.client.wrapper_calls, [("StopMove",)])

    def test_fixed_straight_speed_keeps_sign_and_ignores_scale_only_on_pure_x(self):
        control = Controller(self.client, straight_speed=.20, timed_velocity=True, clock=lambda: self.now)
        self.assertEqual(self.client.calls, [])
        control.handle("q")
        for key, sign in (("i", 1), ("I", 1), (",", -1), ("<", -1)):
            control.handle(key)
            self.assertEqual(self.client.calls[-1], ("velocity", sign * .20, 0, 0, PULSE_SECONDS))
            self.advance(.125)
            control.tick()
            self.assertEqual(self.client.calls[-1], ("velocity", sign * .20, 0, 0, .875))
            control.handle("k")
            self.assertEqual(self.client.calls[-1], ZERO)
        control.handle("o")
        self.assertAlmostEqual(self.client.calls[-1][1], .15 * 1.1)
        self.assertAlmostEqual(self.client.calls[-1][3], -.30 * 1.1)

    def test_default_straight_speed_follows_linear_scale_up_to_the_cap(self):
        for key, speed in (("w", .30), ("w", .30), ("z", .30), ("x", .29403)):
            with self.subTest(key=key, speed=speed):
                expected = f"직진·후진 ±{speed:.3f} m/s (상한 0.300 m/s)"
                self.assertIn(expected, self.control.handle(key))
                self.assertIn(expected, self.control.handle("f"))
                for direction, sign in (("i", 1), (",", -1), ("I", 1), ("<", -1)):
                    self.control.handle(direction)
                    operation, vx, vy, yaw = self.client.wrapper_calls[-1]
                    self.assertEqual((operation, vy, yaw), ("Move", 0, 0))
                    self.assertAlmostEqual(vx, sign * speed)

    def test_tap_refreshes_until_its_original_deadline_then_zeros_once(self):
        self.use_timed_velocity()
        start = self.now
        self.control.handle("i")
        self.control.handle("q")  # A speed change applies to the next direction input.
        for offset in (.125, .250, .750):
            self.now = start + offset
            self.client.calls.clear()
            self.control.tick()
            self.assertEqual(len(self.client.calls), 2)
            self.assertEqual(self.client.calls[0], ("read",))
            self.assertEqual(self.client.calls[1][:-1], ("velocity", .30, 0, 0))
            self.assertAlmostEqual(self.client.calls[1][-1], PULSE_SECONDS - offset)
            self.control.tick()
            self.assertEqual(len(self.client.calls), 2)
        self.now = start + PULSE_SECONDS
        self.client.calls.clear()
        summary = self.control.tick()
        self.control.tick()
        self.control.close()
        self.assertEqual(self.client.calls, [ZERO])
        self.assertIn("이동 입력 1회 · 속도 RPC 수락 4회", summary)

    def test_throttled_fresh_repeat_extends_deadline_and_older_repeat_cannot_shorten_it(self):
        self.use_timed_velocity()
        start = self.now
        self.control.handle("i")
        self.advance(.5)
        self.control.tick()
        self.advance(.03)
        self.control.handle("i")  # Fresh input within the send rate limit.
        self.now = start + PULSE_SECONDS + .01
        self.control.handle("i", received_at=start)
        self.control.tick()
        self.assertEqual(self.client.calls[-1][:-1], ("velocity", .30, 0, 0))
        self.assertAlmostEqual(self.client.calls[-1][-1], .52)
        self.now = start + .531 + PULSE_SECONDS
        self.control.tick()
        self.assertEqual(self.client.calls[-1], ZERO)

    def test_refresh_uses_time_left_after_fsm_lookup_and_stops_if_lookup_expires(self):
        self.use_timed_velocity()
        self.control.handle("o")
        self.advance(.25)
        self.client.on_read = lambda: self.advance(.125)
        self.control.tick()
        self.assertEqual(self.client.calls[-1][:-1], ("velocity", .15, 0, -.3))
        self.assertAlmostEqual(self.client.calls[-1][-1], PULSE_SECONDS - .375)
        self.advance(.55)
        self.client.calls.clear()
        self.control.tick()
        self.assertEqual(self.client.calls, [("read",), ZERO])
        self.control.tick()
        self.assertEqual(self.client.calls, [("read",), ZERO])

    def test_refresh_after_failed_fsm_read_waits_for_new_input(self):
        self.use_timed_velocity()
        self.control.handle("i")
        self.client.calls.clear()
        self.client.read_code = 8
        self.advance(.25)
        message = self.control.tick()
        self.client.read_code = 0
        self.advance(.25)
        self.control.tick()
        self.assertEqual(self.client.calls, [("read",), ZERO])
        self.assertIn("GetFsmId RPC code=8", message)

    def test_refresh_stops_if_fsm_changes_to_another_allowed_gait(self):
        self.use_timed_velocity()
        self.control.handle("i")
        self.client.calls.clear()
        self.client.state = 500
        self.advance(.25)
        self.control.tick()
        self.assertEqual(self.client.calls, [("read",), ZERO])
        self.advance(.25)
        self.control.tick()
        self.assertEqual(self.client.calls, [("read",), ZERO])
        self.control.handle("i")
        self.assertEqual(self.client.calls[-1], ("velocity", .30, 0, 0, PULSE_SECONDS))

    def test_refresh_yields_to_input_queued_before_or_during_fsm_lookup(self):
        self.use_timed_velocity()
        self.control.handle("i")
        self.client.calls.clear()
        self.advance(.25)
        self.control.tick(input_waiting=lambda: True)
        self.assertEqual(self.client.calls, [])
        pending = False

        def queue_stop():
            nonlocal pending
            pending = True

        self.client.on_read = queue_stop
        self.control.tick(input_waiting=lambda: pending)
        self.assertEqual(self.client.calls, [("read",)])
        self.control.handle("k")
        self.assertEqual(self.client.calls, [("read",), ZERO])

    def test_exit_already_requested_suppresses_a_due_refresh(self):
        self.control.handle("i")
        self.client.calls.clear()
        self.advance(.25)
        self.control.exit_requested = True
        self.control.tick()
        self.assertEqual(self.client.calls, [])

    def test_exit_during_refresh_lookup_prevents_nonzero_send(self):
        self.control.handle("i")
        self.advance(.25)
        self.client.calls.clear()
        self.client.on_read = lambda: setattr(self.control, "exit_requested", True)
        with self.assertRaises(EndSession):
            self.control.tick()
        self.control.close()
        self.assertEqual(self.client.calls, [("read",), ZERO])

    def test_slow_lookup_cannot_replay_expired_movement(self):
        self.use_timed_velocity()
        self.client.on_read = lambda: self.advance(PULSE_SECONDS + .01)
        self.control.handle("i")
        self.assertEqual(self.client.calls, [("read",)])
        # A 300 ms GET used to exhaust the entire 250 ms motion budget.
        self.client.on_read = lambda: self.advance(.3)
        status = self.control.handle("i")
        self.assertIn("SetVelocity(7105) 수락", status)
        self.assertIn("FSM=802", status)
        self.assertNotIn("→ Enter", status)
        self.assertEqual(self.client.calls[-1][:-1], ("velocity", .30, 0, 0))
        self.assertAlmostEqual(self.client.calls[-1][-1], .7)

    def test_external_mode_change_stops_owned_motion(self):
        self.control.handle("l")
        self.advance(REPEAT_INTERVAL + .01)
        self.client.state = 4
        self.control.handle("l")
        self.assertEqual(self.client.calls[-2:], [("read",), ZERO])

    def test_automatic_cleanup_only_touches_owned_motion(self):
        self.control.close()
        self.assertEqual(self.client.calls, [])
        self.control.handle(" ")
        self.assertEqual(self.client.calls, [ZERO])
        self.client.calls.clear()
        self.control.handle("L")
        self.control.close()
        self.control.close()
        self.assertEqual(self.client.calls.count(ZERO), 1)

    def test_final_stop_retries_zero_after_lost_reply_and_confirms_success(self):
        self.control.handle("i")
        stop = Mock(side_effect=[TimeoutError("lost reply"), 0])
        self.client.SetVelocity = stop
        self.assertIn("속도 0 요청 수락", self.control.close(force_stop=True))
        self.assertEqual([entry.args for entry in stop.call_args_list], [ZERO[1:], ZERO[1:]])
        self.assertIsNone(self.control.moving_key)

    def test_confirmation_is_distinct_one_shot_and_expires(self):
        self.control.handle("0")
        self.advance(CONFIRM_SECONDS / 2)
        self.control.handle("0")
        self.advance(CONFIRM_SECONDS / 2)
        self.control.handle("\r")
        self.assertEqual(self.client.calls, [])
        for cancel in ("\x1b", "i", "?"):
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
        self.control.handle("j")
        self.control.handle("1")
        self.assertEqual(self.client.calls[-1], ZERO)
        result = self.control.handle("\r")
        self.assertIn("현재 FSM=802", result)
        self.assertIn("진입 미확인", result)
        self.client.calls.clear()
        self.control.handle("i")
        self.assertEqual([("read",)], self.client.calls)
        self.client.state = 4
        self.assertNotIn("미확인", self.control.handle("f"))
        self.control.handle("i")
        self.assertEqual(self.client.calls[-1], ("read",))

    def test_802_transition_requires_readback_and_never_falls_back_to_500(self):
        self.client.state = 500
        self.assertIn("진입 미확인", self.request("2"))
        self.control.handle("i")
        self.assertNotIn(("fsm", 500), self.client.calls)
        self.assertFalse(any(call[0] == "velocity" for call in self.client.calls))
        self.client.state = 802
        self.control.handle("i")
        self.assertEqual(self.client.calls[-1], ("velocity", .30, 0, 0, PULSE_SECONDS))

    def test_only_documented_run_ids_allow_direction_without_a_mode_write(self):
        for observed in (800, 801, 802):
            with self.subTest(observed=observed):
                client = NativeClient()
                client.state = observed
                control = Controller(client, clock=lambda: self.now)
                status = control.handle("i")
                expected = [("read",)]
                if observed in (801, 802):
                    expected.append(("velocity", .30, 0, 0, PULSE_SECONDS))
                self.assertIn(f"FSM={observed}", status)
                self.assertEqual(client.calls, expected)

    def test_selecting_run_requires_readback_of_the_exact_requested_id(self):
        for observed, target in [(801, 802), (802, 801)]:
            with self.subTest(observed=observed, target=target):
                client = NativeClient()
                client.state = observed
                control = Controller(client, run_fsm=target, clock=lambda: self.now)
                self.assertIn(str(target), control.handle("2"))
                self.assertEqual(client.calls, [])
                self.assertIn("진입 미확인", control.handle("\r"))
                self.assertIn("진입 미확인", control.handle("i"))
                self.assertEqual(client.calls, [("read",), ("fsm", target), ("read",), ("read",)])
                client.state = target
                self.assertIn(f"FSM={target}", control.handle("i"))
                self.assertEqual(client.calls[-2:], [("read",), ("velocity", .30, 0, 0, PULSE_SECONDS)])

    def test_regular_walk_requires_actual_readback_and_fresh_direction(self):
        self.assertIn("Enter", self.control.handle("v"))
        self.assertEqual(self.client.calls, [])
        self.assertIn("진입 미확인", self.control.handle("\r"))
        self.assertEqual(self.client.calls, [("read",), ("fsm", 500), ("read",)])
        self.client.calls.clear()
        self.assertIn("진입 미확인", self.control.handle("i"))
        self.client.state = 500
        self.assertIn("FSM=500 (일반 보행)", self.control.handle("f"))
        self.assertEqual(self.client.calls, [("read",), ("read",)])
        self.assertIn("FSM=500", self.control.handle("i"))
        self.assertEqual(self.client.calls[-2:], [("read",), ("velocity", .30, 0, 0, PULSE_SECONDS)])

    def test_failed_regular_walk_request_keeps_motion_blocked_until_reselection(self):
        self.client.write_code = 12
        self.assertIn("SetFsmId RPC code=12", self.request("v"))
        self.assertIn("진입 미확인", self.control.handle("i"))
        self.assertEqual(self.client.calls, [("read",), ("fsm", 500), ("read",)])
        self.client.write_code = 0
        self.assertIn("FSM=802", self.request("2"))
        self.assertIn("FSM=802", self.control.handle("i"))
        self.assertEqual(self.client.calls[-1], ("velocity", .30, 0, 0, PULSE_SECONDS))

    def test_direction_in_already_selected_regular_mode_does_not_switch_modes(self):
        self.client.state = 500
        self.assertIn("FSM=500", self.control.handle("m"))
        self.assertEqual(self.client.calls, [("read",), ("velocity", -.15, 0, -.3, PULSE_SECONDS)])

    def test_queued_repeat_uses_original_deadline_and_cannot_revive_stale_motion(self):
        self.use_timed_velocity()
        self.control.handle("i")
        stamp = self.now
        self.advance(.4)
        self.control.handle("i", received_at=stamp)
        self.assertAlmostEqual(self.client.calls[-1][-1], .6)
        self.advance(.61)
        self.assertIn("만료", self.control.handle("i", received_at=stamp))
        self.assertEqual(self.client.calls[-1], ZERO)
        self.assertIsNone(self.control.moving_key)
        self.client.calls.clear()
        self.control.handle("i", received_at=stamp)
        self.assertEqual(self.client.calls, [])

    def test_repeat_rate_is_bounded_and_changing_direction_is_immediate(self):
        self.control.handle("i")
        self.advance(REPEAT_INTERVAL / 2)
        self.control.handle("i")
        self.assertEqual(self.client.calls, [("read",), ("velocity", .30, 0, 0, PULSE_SECONDS)])
        self.control.handle(",")
        self.assertEqual(self.client.calls[-1], ("velocity", -.30, 0, 0, PULSE_SECONDS))

    def test_timer_sends_only_remaining_pulse_until_input_deadline(self):
        self.use_timed_velocity()
        self.control.handle("i")
        start = self.now
        for dt in (.2, .4, .6, .8):
            self.now = start + dt
            self.control.tick()
            self.assertEqual(self.client.calls[-1][:-1], ("velocity", .30, 0, 0))
            self.assertAlmostEqual(self.client.calls[-1][-1], 1.0 - dt)
        self.advance(.21)
        self.assertIn("이동 입력 1회 · 속도 RPC 수락 5회", self.control.tick())
        self.control.tick()
        self.assertEqual(self.client.calls[-1], ZERO)
        self.assertEqual(self.client.calls.count(ZERO), 1)

    def test_rate_limited_repeat_renews_deadline_but_speed_key_does_not_change_active_command(self):
        self.use_timed_velocity()
        self.control.handle("i")
        self.advance(.075)
        self.control.handle("i")
        self.control.handle("w")
        self.advance(.925)
        self.control.tick()
        self.assertEqual(self.client.calls[-1][:-1], ("velocity", .30, 0, 0))
        self.assertAlmostEqual(self.client.calls[-1][-1], .075)
        self.advance(.08)
        self.assertIn("이동 입력 2회", self.control.tick())

    def test_timer_read_gives_precedence_to_queued_keys_and_external_mode_changes(self):
        self.use_timed_velocity()
        self.control.handle("i")
        self.advance(.2)
        self.control.tick(lambda: True)
        self.control.tick(Mock(side_effect=[False, True]))
        self.assertEqual(self.client.calls, [("read",), ("velocity", .30, 0, 0, 1), ("read",)])
        self.client.state = 4
        self.assertIn("FSM=4", self.control.tick())
        self.assertEqual(self.client.calls[-1], ZERO)
        self.advance(.2)
        self.assertIsNone(self.control.tick())

    def test_refresh_stops_if_the_gait_changes_even_between_enabled_gaits(self):
        self.control = Controller(self.client, waist_3dof=True, clock=lambda: self.now)
        self.control.handle("i")
        self.client.state = 501
        self.advance(.2)
        self.assertIn("FSM 501", self.control.tick())
        self.assertEqual(self.client.calls[-1], ZERO)

    def test_ros_speed_keys_have_independent_linear_and_turn_controls(self):
        for key, linear, turn in [("q", 1.1, 1.1), ("z", .99, .99), ("w", 1.089, .99),
                                  ("x", .9801, .99), ("e", .9801, 1.089), ("c", .9801, .9801)]:
            self.assertIn("선속도", self.control.handle(key))
            self.assertAlmostEqual(self.control.linear_scale, linear)
            self.assertAlmostEqual(self.control.turn_scale, turn)
        self.assertEqual(self.client.calls, [])
        self.control.handle("u")
        self.assertAlmostEqual(self.client.calls[-1][1], .15 * .9801)
        self.assertAlmostEqual(self.client.calls[-1][3], .3 * .9801)

    def test_stop_keys_and_unbound_input_stop_owned_motion(self):
        for key in ("k", "K", " ", "h", "\x1b"):
            self.control.handle("i")
            self.assertIn("속도 0", self.control.handle(key))
            self.assertEqual(self.client.calls[-1], ZERO)
            self.assertIsNone(self.control.moving_key)
            self.client.calls.clear()
            self.advance(.25)
            self.control.tick()
            self.assertEqual(self.client.calls, [])

    def test_waist_model_gate_for_request_movement_and_balance(self):
        self.request("8")
        self.assertEqual(self.client.calls, [])
        self.client.state = 501
        self.control.handle("i")
        self.request("5")
        self.assertEqual(self.client.calls, [("read",), ("read",)])
        self.control = Controller(self.client, waist_3dof=True, clock=lambda: self.now)
        self.client.state = 4
        self.request("8")
        self.client.state = 501
        self.control.handle(",")
        self.assertIn(("fsm", 501), self.client.calls)
        self.assertEqual(self.client.calls[-1], ("velocity", -.30, 0, 0, PULSE_SECONDS))
        self.client.state = 802
        self.assertNotIn("→ Enter", self.control.handle("i"))

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
        self.control.handle("i")
        self.assertEqual(self.client.calls, [("read",), ("fsm", 706), ("read",)])
        self.request("2")
        self.assertEqual(self.client.calls[-3:], [("read",), ("fsm", 802), ("read",)])

    def test_does_not_override_user_control_mode(self):
        self.client.state = 1000
        self.request("0")
        self.control.handle("i")
        self.assertEqual(self.client.calls, [("read",), ("read",)])

    def test_velocity_failure_stops_and_waits_for_a_fresh_key(self):
        self.use_timed_velocity()
        self.client.velocity_code = 23
        message = self.control.handle("j")
        self.assertIn("SetVelocity(7105) RPC code=23", message)
        self.assertEqual(self.client.calls[-1], ZERO)
        self.client.calls.clear()
        self.client.velocity_code = 0
        self.advance(1.0)
        self.control.tick()
        self.assertEqual(self.client.calls, [])
        self.control.handle("j")
        self.assertEqual(self.client.calls[-1], ("velocity", 0, 0, .3, PULSE_SECONDS))

    def test_invalid_readback_stops_owned_motion(self):
        self.control.handle("J")
        self.client.state = None
        self.control.handle("L")
        self.assertEqual(self.client.calls[-2:], [("read",), ZERO])
        self.client.calls.clear()
        self.client.read_code = 8
        self.control.handle("i")
        self.assertEqual(self.client.calls, [("read",)])

    def test_uncertain_fsm_request_blocks_motion_until_verified(self):
        self.client.state = 500
        self.client.write_code = 12
        self.assertIn("12", self.request("2"))
        self.assertEqual(self.client.calls, [("read",), ("fsm", 802)])
        self.assertIn("미확인", self.control.handle("i"))
        self.assertEqual(self.client.calls[-1], ("read",))

    def test_running_speed_caps_send_sdk_modes_without_changing_velocity(self):
        for run_fsm in (801, 802):
            self.client.state = run_fsm
            for key, mode, limit in [("!", 0, 1.0), ("@", 1, 2.0), ("#", 2, 2.7), ("$", 3, 3.0)]:
                with self.subTest(run_fsm=run_fsm, key=key):
                    self.client.calls.clear()
                    self.assertIn(f"{limit:.1f} m/s", self.control.handle(key))
                    self.assertEqual(self.client.calls, [("read",), ("speed", mode)])
        self.control.handle("i")
        self.assertEqual(self.client.calls[-1], ("velocity", .30, 0, 0, PULSE_SECONDS))
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
        self.control.handle("j")
        self.assertEqual(self.client.calls[-1], ("velocity", 0, 0, .6, PULSE_SECONDS))
        self.client.calls.clear()
        for _ in range(10):
            self.control.handle("-")
        self.assertEqual(self.client.calls, [])
        self.control.handle("L")
        self.assertEqual(self.client.calls[-1], ("velocity", 0, -.05, 0, PULSE_SECONDS))


if __name__ == "__main__":
    unittest.main()
