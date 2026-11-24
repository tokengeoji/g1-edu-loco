# Author: Codex (IIC)
"""Unit conversion and evidence labels for the operator's terminal."""

import unittest

from .terminal import format_stairs


class StairTerminalTest(unittest.TestCase):
    def test_reports_stored_dimensions_and_observed_direction(self):
        tread = {
            "surface_id": 4, "riser_height_m": .17, "height_above_reference_ground_m": -.33,
            "tread_depth_m": .29, "width_m": None, "riser_status": "estimated_common_boundary",
            "observed_width_span_m": .84,
        }
        frame = {
            "frame_number": 81, "ground_observed": False, "treads": [tread],
            "stair_flights": [{"direction": "descending", "surface_ids": [2, 3, 4],
                              "median_riser_height_m": .165}],
        }
        report = format_stairs(frame)
        self.assertIn("기준 바닥 미관측", report)
        row = next(line for line in report.splitlines() if line.lstrip().startswith("4 "))
        self.assertEqual(row.split()[:5], ["4", "17.0", "-33.0", "29.0", "--"])
        self.assertIn("인접한 두 면의 경계", row)
        self.assertIn("내림 구간 · 면 2 → 3 → 4 · 단높이 중앙값 16.5 cm", report)
        self.assertIn("G1 연속 등반 가능 여부 미확인", report)

    def test_no_depth_and_legacy_frames_are_rendered_as_recorded(self):
        frame = {"frame_number": 2, "ground_observed": False, "treads": [], "valid_depth_sample_count": 0}
        legacy = format_stairs(frame)
        self.assertIn("유효한 깊이 픽셀이 없습니다.", legacy)
        self.assertNotIn("연속 계단 구간", legacy)
        frame.update(stair_flights=[], ground_observed=True, valid_depth_sample_count=50)
        report = format_stairs(frame)
        self.assertIn("기준 바닥 관측 · 디딤면 후보 0개", report)
        self.assertIn("연속 계단 구간 미확인", report)
        self.assertNotIn("유효한 깊이 픽셀이 없습니다.", report)
