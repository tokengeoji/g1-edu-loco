# Author: Codex (IIC)
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from .status import status_details


class StatusTests(unittest.TestCase):
    def setUp(self):
        api = SimpleNamespace(ROBOT_API_ID_LOCO_GET_FSM_MODE=7002)
        modules = patch.dict(sys.modules, {"unitree_sdk2py.g1.loco.g1_loco_api": api})
        modules.start()
        self.addCleanup(modules.stop)
        self.client = Mock(spec_set=["GetServerApiVersion", "_Call"])
        self.client.GetServerApiVersion.return_value = 0, "1.0.0.0"

    def test_queries_only_version_and_fsm_mode_and_preserves_unrecognized_mode(self):
        for value, label in [(0, "정적 상태"), (1, "동적 상태"), (7, "알 수 없는 상태")]:
            with self.subTest(value=value):
                self.client.reset_mock()
                self.client._Call.return_value = 0, '{"data":%d}' % value
                details = status_details(self.client)
                self.assertIn("API 버전=1.0.0.0", details)
                self.assertIn(f"GetFsmMode={value} ({label})", details)
                self.assertEqual(self.client.mock_calls,
                                 [call.GetServerApiVersion(), call._Call(7002, "{}")])

    def test_failed_version_does_not_hide_fsm_mode(self):
        self.client.GetServerApiVersion.return_value = 3104, None
        self.client._Call.return_value = 0, '{"data":1}'
        details = status_details(self.client)
        self.assertIn("3104", details)
        self.assertIn("GetFsmMode=1", details)

    def test_failed_or_malformed_mode_does_not_hide_server_api_version(self):
        for response in [(3104, None), (0, ""), (0, "[]"), (0, '{"data":true}')]:
            with self.subTest(response=response):
                self.client._Call.return_value = response
                details = status_details(self.client)
                self.assertIn("API 버전=1.0.0.0", details)
                self.assertIn("GetFsmMode=조회 실패", details)
                if response[0]:
                    self.assertIn("3104", details)

    def test_sdk_exceptions_are_reported_independently(self):
        self.client.GetServerApiVersion.side_effect = RuntimeError("version timeout")
        self.client._Call.side_effect = RuntimeError("mode timeout")
        details = status_details(self.client)
        self.assertIn("version timeout", details)
        self.assertIn("mode timeout", details)
