"""Regression tests for calibrated, partially observed synthetic stairs."""

import unittest

import numpy as np

from g1stairs.camera.synthetic import stairs_fixture

from .projection import Calibration, camera_rays, deproject
from .surfaces import MeasurementOptions, measure_surfaces


class StairMeasurementTest(unittest.TestCase):
    def setUp(self):
        self.depth, intrinsics, self.scale, calibration, self.truth = stairs_fixture()
        self.rays = camera_rays(intrinsics)
        self.calibration = Calibration.from_mapping(calibration)

    def measure(self, depth):
        points = deproject(depth, self.rays, self.scale, self.calibration)
        return measure_surfaces(points, self.calibration.translation_m, self.calibration.ground_z_m, MeasurementOptions())

    def test_analytic_stair_boundaries_and_rises(self):
        result = self.measure(self.depth)
        self.assertTrue(result["ground_observed"])
        self.assertEqual(len(result["treads"]), 4)
        for tread, truth in zip(result["treads"], self.truth["treads"]):
            self.assertAlmostEqual(tread["z_m"], truth["z_m"], delta=0.002)
            self.assertAlmostEqual(tread["riser_height_m"], truth["riser_height_m"], delta=0.002)
        first = result["treads"][0]
        self.assertAlmostEqual(first["tread_depth_m"], self.truth["treads"][0]["tread_depth_m"], delta=0.02)
        self.assertAlmostEqual(first["width_m"], self.truth["treads"][0]["width_m"], delta=0.02)

    def test_missing_side_does_not_become_full_width(self):
        occluded = self.depth.copy()
        occluded[:, :self.depth.shape[1] // 2] = 0
        first = self.measure(occluded)["treads"][0]
        self.assertIsNone(first["width_m"])
        self.assertLess(first["observed_width_span_m"], 0.55)

    def test_zero_depth_does_not_create_ground(self):
        result = self.measure(np.zeros_like(self.depth))
        self.assertFalse(result["ground_observed"])
        self.assertEqual(result["treads"], [])

    def test_reflected_calibration_is_rejected(self):
        with self.assertRaises(ValueError):
            Calibration.from_mapping({"rotation": np.diag((1, 1, -1)), "translation_m": [0, 0, 0]})


if __name__ == "__main__":
    unittest.main()
