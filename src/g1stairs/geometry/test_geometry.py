"""Regression tests for calibrated, partially observed synthetic stairs."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np

from g1stairs.camera.synthetic import stairs_fixture

from g1stairs.session import write_json

from .__main__ import _measure
from .projection import Calibration, camera_rays, deproject
from .surfaces import MeasurementOptions, measure_surfaces


class StairMeasurementTest(unittest.TestCase):
    def setUp(self):
        self.depth, intrinsics, self.scale, calibration, self.truth = stairs_fixture()
        # An independent pinhole scene tests the project estimator without hardware.
        v, u = np.indices(self.depth.shape, dtype=float)
        self.rays = np.stack(((u - intrinsics["cx"]) / intrinsics["fx"],
                              (v - intrinsics["cy"]) / intrinsics["fy"], np.ones_like(u)), axis=-1)
        self.intrinsics = intrinsics
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

    def test_sdk_unit_rays_match_fixture_and_preserve_metric_stairs(self):
        try:
            import pyrealsense2  # The wheel can also require access to the host udev monitor.
        except (ImportError, OSError) as error:
            self.skipTest(f"RealSense Python bindings unavailable: {error}")
        rays = camera_rays(self.intrinsics)
        np.testing.assert_allclose(rays, self.rays, rtol=0, atol=1e-6)
        points = deproject(self.depth, rays, self.scale, self.calibration)
        result = measure_surfaces(points, self.calibration.translation_m, self.calibration.ground_z_m, MeasurementOptions())
        self.assertAlmostEqual(result["treads"][0]["riser_height_m"], 0.15, delta=0.002)

    def test_conflicting_optical_frame_rejected_before_measurement(self):
        with TemporaryDirectory() as root:
            depth = Path(root) / "example" / "depth"
            depth.mkdir(parents=True)
            write_json(depth / "manifest.json", {"complete": True, "encoding": "Z16", "frame_id": "head_depth"})
            write_json(depth / "calibration.json", {"rotation": np.eye(3).tolist(), "translation_m": [0, 0, 0],
                                                    "source_frame": "other_camera"})
            with self.assertRaisesRegex(ValueError, "other_camera.*head_depth"):
                _measure(SimpleNamespace(runs_dir=root, run="example", calibration=None))
            self.assertFalse((depth.parent / "geometry").exists())

    def test_reflected_calibration_is_rejected(self):
        with self.assertRaises(ValueError):
            Calibration.from_mapping({"rotation": np.diag((1, 1, -1)), "translation_m": [0, 0, 0]})


if __name__ == "__main__":
    unittest.main()
