# Author: Codex (IIC)
"""Check that plan view orientation, coverage and mixed surfaces remain distinct."""

import unittest

from .terminal_map import format_stair_map


def geometry(ground, treads):
    return {
        "grid_m": .025,
        "observed_ground_patches": [{"observed_cells": ground}],
        "treads": [
            {"surface_id": surface_id, "observed_cells": cells} for surface_id, cells in treads
        ],
    }


class TerminalMapTests(unittest.TestCase):
    def test_positive_x_is_up_and_positive_y_is_left_without_filling_gaps(self):
        frame = geometry([(-1, -1)], [(10, [(0, 1)]), (36, [(0, -1)])])
        lines = format_stair_map(frame).splitlines()
        self.assertEqual(lines[2:-2], ["A · +", "· · ="])
        self.assertIn("2.5 × 2.5 cm", lines[1])

    def test_duplicate_coordinates_distinguish_overlap_from_coverage(self):
        frame = geometry([(0, 0), (0, 0)], [(0, [(0, 0), (0, 1)])])
        self.assertEqual(format_stair_map(frame).splitlines()[2:-2], ["0 *"])

    def test_downsampling_marks_sparse_cells_and_complete_tiles(self):
        frame = geometry([], [(0, [(0, 0), (0, 1), (1, 0), (1, 1), (16, 0)])])
        lines = format_stair_map(frame).splitlines()
        self.assertIn("5 × 5 cm", lines[1])
        self.assertEqual(lines[2:-2], ["0:"] + ["·"] * 7 + ["0"])
        frame["treads"][0]["observed_cells"].append((10000000, 10000000))
        lines = format_stair_map(frame).splitlines()[2:-2]
        self.assertLessEqual(len(lines), 16)
        self.assertTrue(all(len(line) <= 48 for line in lines))

    def test_empty_geometry(self):
        self.assertIn("표시할 관측 셀이 없습니다", format_stair_map(geometry([], [])))
