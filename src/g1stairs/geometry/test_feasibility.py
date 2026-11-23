# Author: Codex (IIC)
import argparse
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from .feasibility import Footprint, Reach, assess_tread, configure_parser, run


def surface():
    return {"surface_id": 0, "z_m": 0.2,
            "edges": {side: {"status": "observed_transition", "position_m": pos}
                      for side, pos in (("front", 0), ("back", 1), ("right", -0.5), ("left", 0.5))},
            "observed_cells": [[i, j] for i in range(10) for j in range(-5, 5)]}


class FeasibilityTest(unittest.TestCase):
    def setUp(self):
        self.foot = Footprint(.29, .15, 0, 0, 0, 0)
        self.tread = surface()
        self.reach = Reach((.1, 0, .05, 355), .18, .1, .5, 15, .01)

    def assess(self, xy=(.5, 0), **kwargs):
        return assess_tread(self.tread, .1, kwargs.get("foot", self.foot), xy, kwargs.get("reach"))

    def test_hole_at_interior_is_unknown_despite_measured_edges_and_supported_corners(self):
        self.assertEqual(self.assess()["status"], "support_observed")
        self.tread["observed_cells"].remove([5, 0])
        self.assertEqual(self.assess()["status"], "unknown")
        self.assertEqual(self.assess(None)["status"], "support_observed")

    def test_guarded_edges_missing_data_and_unknown_extent(self):
        self.assertEqual(self.assess(foot=replace(self.foot, length_m=1.2))["status"], "outside_measured_envelope")
        self.tread["edges"]["back"] = {"status": "unconfirmed", "position_m": None}
        self.assertEqual(self.assess(foot=replace(self.foot, length_m=1.2))["status"], "unknown")
        interior = self.assess()
        self.assertEqual(interior["status"], "support_observed")
        self.assertEqual(interior["unconfirmed_edges"], ["back"])
        self.assertEqual(interior["support_evidence_ring_cells"], 1)
        self.assertEqual(self.assess((.84, 0))["status"], "unknown")
        self.assertEqual(self.assess((1.2, 0))["status"], "unknown")
        self.assertEqual(self.assess((.05, 0))["reason"], "candidate_crosses_measured_edge")
        # A missing neighbor beside the footprint breaks the evidence collar.
        self.tread["observed_cells"].remove([5, 1])
        self.assertEqual(self.assess()["status"], "unknown")
        self.tread = surface()
        del self.tread["observed_cells"]
        self.assertEqual(self.assess()["reason"], "no_observed_support_cells")

    def test_malformed_evidence_is_distinct_from_an_unseen_edge(self):
        self.tread["edges"]["right"] = {"status": "observed_transition", "position_m": None}
        with self.assertRaisesRegex(ValueError, "right edge"):
            self.assess()
        self.tread = surface()
        self.tread["edges"]["back"]["position_m"] = -1.
        with self.assertRaisesRegex(ValueError, "positive extent"):
            self.assess()
        self.tread = surface()
        self.tread["observed_cells"] = {}
        with self.assertRaisesRegex(ValueError, "cell indices"):
            self.assess()

    def test_rotation_and_uncertainty_change_the_cells_required(self):
        self.tread["observed_cells"].remove([5, 1])
        self.assertEqual(self.assess()["status"], "support_observed")
        for foot in (replace(self.foot, yaw_deg=90), replace(self.foot, yaw_uncertainty_deg=18),
                     replace(self.foot, position_uncertainty_m=.035), replace(self.foot, edge_margin_m=.035)):
            with self.subTest(foot=foot):
                self.assertEqual(self.assess(foot=foot)["status"], "unknown")
        # An oblique sole need not cover the corners of its axis-aligned bounding box.
        self.tread = surface()
        self.tread["observed_cells"].remove([6, -2])
        self.assertEqual(self.assess(foot=replace(self.foot, yaw_deg=45))["status"], "support_observed")

    def test_arbitrary_candidate_and_negative_cell_indices(self):
        self.assertEqual(self.assess((.501, -.101))["candidate_center_m"], [.501, -.101, .2])
        self.assertEqual(self.assess((.05, -.25))["status"], "outside_measured_envelope")

    def test_reach_wraps_yaw_and_checks_height_in_both_directions(self):
        hit = self.assess(reach=self.reach)
        self.assertEqual(hit["status"], "support_and_reach_within_envelope")
        self.assertEqual(hit["reach"]["yaw_change_deg"], 5)
        tighter = replace(self.reach, max_rise_m=.155, max_horizontal_reach_m=.39, max_yaw_change_deg=4)
        self.assertEqual(self.assess(reach=tighter)["reach"]["outside_limits"], ["horizontal","rise","yaw"])
        self.tread["z_m"] = -.05
        self.assertEqual(self.assess(reach=self.reach)["reach"]["outside_limits"], ["drop"])

    def test_search_continues_after_supported_candidate_outside_reach(self):
        reach = replace(self.reach, stance_pose=(.15, -.25, .18, 0), max_horizontal_reach_m=.06)
        hit = self.assess(None, reach=reach)
        self.assertEqual(hit["status"], "support_and_reach_within_envelope")
        self.assertLessEqual(hit["reach"]["horizontal_m"], .06)

    def test_invalid_numeric_inputs_are_rejected(self):
        for change in ({"length_m":0}, {"yaw_deg":math.nan}, {"yaw_uncertainty_deg":181},
                       {"position_uncertainty_m":-.1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(self.foot, **change)
        with self.assertRaises(ValueError):
            self.assess((0, math.inf))

    def test_command_uses_completed_recorded_frame_and_keeps_climbability_unknown(self):
        parser = argparse.ArgumentParser()
        configure_parser(parser)
        with tempfile.TemporaryDirectory() as root:
            args = parser.parse_args(["--runs-dir", root, "--run", "example", "--foot-length-m", ".29",
                                      "--foot-width-m", ".15", "--yaw-deg", "0", "--edge-margin-m", ".012",
                                      "--position-uncertainty-m", ".01", "--yaw-uncertainty-deg", "3",
                                      "--frame-number", "4"])
            part = Path(root)/"example"/"geometry"
            part.mkdir(parents=True)
            manifest = {"complete": True, "frame_id": "survey", "grid_origin_xy_m": [0,0],
                        "coordinate_axes":{"x":"forward","y":"left","z":"up"}}
            (part/"manifest.json").write_text(json.dumps(manifest))
            records = [dict(frame_number=n, frame_id="survey", grid_m=.1, treads=[self.tread])
                       for n in (2, 4, 5)]
            records[1]["stair_flights"] = [{"surface_ids": [0, 1, 2]}]
            records[2]["stair_flights"] = []
            (part/"stairs.jsonl").write_text("".join(json.dumps(r)+"\n" for r in records))
            result = run(args)
            self.assertEqual(result["frame_number"], 4)
            self.assertEqual(result["robot_climbability"], "unknown")
            self.assertEqual(result["treads"][0]["support"], "covered_at_grid_resolution")
            self.assertEqual(result["treads"][0]["flight_membership"], "detected")
            self.assertEqual(result["treads"][0]["flight_indices"], [0])
            args.frame_number = 5
            self.assertEqual(run(args)["treads"][0]["flight_membership"], "not_in_detected_flight")
            args.frame_number = 2
            self.assertEqual(run(args)["treads"][0]["flight_membership"], "unknown")
            args.max_rise_m = .2
            with self.assertRaisesRegex(ValueError, "reach assessment requires"):
                run(args)
            args.max_rise_m = None
            manifest["complete"] = False
            (part/"manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "finish"):
                run(args)
