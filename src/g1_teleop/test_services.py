# Author: Codex (IIC)
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch, call

from .services import motion_service_details


class ServiceReadingsTests(unittest.TestCase):
    def setUp(self):
        api = SimpleNamespace(ROBOT_STATE_API_ID_SERVICE_LIST=1003, ROBOT_STATE_API_ID_GET_PKG_VERSION=1006,
                              ROBOT_STATE_SERVICE_NAME="robot_state", ROBOT_STATE_API_VERSION="1.0.0.2")
        self.client = Mock(spec_set=["_Call", "_RegistApi", "_SetApiVerson", "SetTimeout"])
        factory = Mock(return_value=self.client)
        self.enter = patch.dict(sys.modules, {
            "unitree_sdk2py.b2.robot_state": SimpleNamespace(robot_state_api=api),
            "unitree_sdk2py.rpc.client": SimpleNamespace(Client=factory),
        })
        self.enter.start()
        self.addCleanup(self.enter.stop)

    def test_read_only_with_mixed_services(self):
        self.client._Call.side_effect = [
            (0, '[{"name":"vui_service","status":0},{"name":"ai_sport","status":1}]'),
            (0, '{"packageVersion":"1.5.3","moduleVersionMap":{"ai_sport":"8.x"}}')]
        value = motion_service_details()
        self.assertIn("ai_sport status=1", value)
        self.assertIn("1.5.3 · ai_sport=8.x", value)
        self.assertEqual(self.client._Call.call_args_list, [call(1003, "{}"), call(1006, "{}")])

    def test_absent_service_and_unavailable_version_remain_unknown(self):
        self.client._Call.side_effect = [(0, "[]"), (3104, None)]
        value = motion_service_details()
        self.assertIn("목록에 없음", value)
        self.assertIn("3104", value)

    def test_version_available_when_list_fails(self):
        self.client._Call.side_effect = [(3104, None), (0, '{"packageVersion":"abc"}')]
        self.assertIn("기체 보고 패키지 버전=abc", motion_service_details())
