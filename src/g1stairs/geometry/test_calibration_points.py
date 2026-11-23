# Author: Codex (IIC)
"""Recorded-frame and held-out-point checks for fixed-pose calibration."""

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from g1stairs.session import read_json, write_json

from . import calibration_points


class CalibrationPointsTest(unittest.TestCase):
    def test_fits_only_training_points_and_preserves_prior_output(self):
        # Independent pinhole rays; perturb the fourth (held-out) measured point.
        raw = np.array([[1000, 800], [600, 900]], dtype=np.uint16)
        v, u = np.indices(raw.shape)
        rays = np.stack((u, v, np.ones_like(u)), axis=-1)
        rotation = np.array([[0, 0, 1], [-1, 0, 0], [0, -1, 0]])
        translation = np.array([0.12, -0.35, 0.91])
        surveyed = (rays * (0.001 * raw)[..., None]) @ rotation.T + translation
        surveyed[1, 1, 2] += 0.04
        with TemporaryDirectory() as tmp:
            run = Path(tmp) / 'survey'
            depth = run / 'depth'
            (depth / 'frames').mkdir(parents=True)
            np.save(depth / 'frames/000000.npy', raw)
            (depth / 'frames.jsonl').write_text('{"file":"frames/000000.npy","frame_number":349}\n')
            write_json(depth / 'manifest.json', dict(complete=True, encoding='Z16', depth_scale_m=0.001,
                       frame_id='depth_optical', intrinsics=dict(height=2, width=2)))
            points = run / 'pairs.csv'
            with points.open('w', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(['use', 'u', 'v', 'x_m', 'y_m', 'z_m'])
                for y, x in np.ndindex(raw.shape):
                    writer.writerow(['check' if (y, x) == (1, 1) else 'fit', x, y, *surveyed[y, x]])
            args = SimpleNamespace(runs_dir=Path(tmp), run='survey', frame_number=349,
                                   points=points, output=None, ground_z_m=None)
            with patch.object(calibration_points, 'camera_rays', return_value=rays):
                result = calibration_points.run(args)
                with self.assertRaises(FileExistsError):
                    calibration_points.run(args)
            cal = read_json(result['output'])
            np.testing.assert_allclose(cal['rotation'], rotation, atol=1e-9)
            np.testing.assert_allclose(cal['translation_m'], translation, atol=1e-9)
            self.assertEqual(cal['source_frame'], 'depth_optical')
            self.assertEqual(result['source_file'], 'frames/000000.npy')
            self.assertAlmostEqual(result['check_points'][0]['error_m'], 0.04)
            self.assertLess(result['fit_rmse_m'], 1e-9)
            args.frame_number = 0
            with self.assertRaisesRegex(ValueError, 'no matching recorded frame'):
                calibration_points.run(args)

    def test_collinear_points_cannot_determine_rotation(self):
        line = np.array([[0., 0., 0.], [0., 1., 0.], [0., 2., 0.]])
        with self.assertRaisesRegex(ValueError, 'non-collinear'):
            calibration_points._fit_transform(line, line + 1)
