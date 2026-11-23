# Author: Codex (IIC)
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch, call

from .services import motion_service_details
from .__main__ import connect


class ServiceReadingsTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(spec_set=["ServiceList", "GetPkgVersion"])

    def test_read_only_with_mixed_services(self):
        self.client.ServiceList.return_value = 0, [("vui_service", 0), ("ai_sport", 1)]
        self.client.GetPkgVersion.return_value = 0, "1.5.3", {"ai_sport": "8.x"}
        value = motion_service_details(self.client)
        self.assertIn("ai_sport status=1", value)
        self.assertIn("1.5.3 · ai_sport=8.x", value)
        self.assertEqual(self.client.mock_calls, [call.ServiceList(), call.GetPkgVersion()])

    def test_absent_service_and_unavailable_version_remain_unknown(self):
        self.client.ServiceList.return_value = 0, []
        self.client.GetPkgVersion.return_value = 3104, None, None
        value = motion_service_details(self.client)
        self.assertIn("목록에 없음", value)
        self.assertIn("3104", value)

    def test_version_available_when_list_fails(self):
        self.client.ServiceList.return_value = 3104, None
        self.client.GetPkgVersion.return_value = 0, "abc", {}
        self.assertIn("기체 보고 패키지 버전=abc", motion_service_details(self.client))


class LiveClientTests(unittest.TestCase):
    def test_official_native_client_receives_domain_and_nic_and_only_reads_fsm_on_open(self):
        robot = Mock()
        robot.GetFsmId.return_value = (0, 802)
        factory = Mock(return_value=robot)
        with patch.dict(sys.modules, {"_g1_loco": SimpleNamespace(connect=factory)}):
            self.assertEqual(connect(7, "enp4s0", "auto"), (robot, "sport", 802))
        factory.assert_called_once_with(7, "enp4s0")
        self.assertEqual(robot.mock_calls, [call.GetFsmId()])

    def test_legacy_endpoint_cannot_redirect_the_official_client(self):
        factory = Mock()
        with patch.dict(sys.modules, {"_g1_loco": SimpleNamespace(connect=factory)}):
            with self.assertRaisesRegex(RuntimeError, "loco.*Unitree G1 LocoClient"):
                connect(0, "eth0", "loco")
        factory.assert_not_called()
