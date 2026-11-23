# Author: Codex (IIC)
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch, call

from .services import motion_service_details
from .__main__ import sdk_client


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


class NativeMoveTests(unittest.TestCase):
    def test_official_wrappers_keep_wire_values_and_surface_rejections(self):
        try:
            from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
        except (ImportError, OSError) as error:
            self.skipTest(f"Unitree SDK unavailable: {error}")

        # ClientBase constructs its DDS stub inside __init__. Replace it
        # before constructing either service client, so the test stays offline.
        with patch("unitree_sdk2py.rpc.client_base.ClientStub", autospec=True) as stub:
            for service in ("sport", "loco"):
                with self.subTest(service=service):
                    client = sdk_client(service)
                    stub.assert_called_with(service)
                    self.assertIs(type(client).Move, LocoClient.Move)
                    self.assertIs(type(client).StopMove, LocoClient.StopMove)
                    with patch.object(client, "_Call", return_value=(0, "")) as rpc:
                        client.Move(0.3, 0.0, 0.0)
                        client.StopMove()
                        payloads = [(api, json.loads(body)) for (api, body), _ in rpc.call_args_list]
                        self.assertEqual(payloads, [
                            (7105, {"velocity": [0.3, 0.0, 0.0], "duration": 1.0}),
                            (7105, {"velocity": [0.0, 0.0, 0.0], "duration": 1.0}),
                        ])
                        rpc.return_value = 3104, None
                        with self.assertRaisesRegex(RuntimeError, "RPC code=3104"):
                            client.Move(0.3, 0.0, 0.0)
                        with self.assertRaisesRegex(RuntimeError, "RPC code=3104"):
                            client.StopMove()
