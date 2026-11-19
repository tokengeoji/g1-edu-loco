"""Analytic pinhole fixture with known metric stair dimensions."""

import math

import numpy as np


def stairs_fixture():
    """Return raw Z16, metadata, optical-to-gravity calibration, and truth."""
    width, height = 240, 180
    fx = fy = 155.0
    cx, cy = (width - 1) / 2, (height - 1) / 2
    depth_scale = 0.001
    pitch = math.radians(40)
    sin, cos = math.sin(pitch), math.cos(pitch)
    rotation = np.array([[0, -sin, cos], [-1, 0, 0], [0, -cos, -sin]])
    origin = np.array([0.0, 0.0, 1.22])

    rows, cols = np.indices((height, width), dtype=np.float64)
    optical_rays = np.stack(((cols - cx) / fx, (rows - cy) / fy, np.ones_like(rows)), axis=-1)
    rays = optical_rays @ rotation.T
    nearest = np.full((height, width), np.inf)

    def hit(axis, plane, other_bounds=()):
        distance = np.full_like(nearest, np.inf)
        np.divide(plane - origin[axis], rays[:, :, axis], out=distance,
                  where=np.abs(rays[:, :, axis]) > 1e-12)
        valid = np.isfinite(distance) & (distance > 0)
        for other_axis, lower, upper in other_bounds:
            coordinate = origin[other_axis] + np.where(valid, distance, 0) * rays[:, :, other_axis]
            valid &= (coordinate >= lower) & (coordinate <= upper)
        np.minimum(nearest, np.where(valid, distance, np.inf), out=nearest)

    hit(2, 0.0)
    edges = (0.65, 1.00, 1.35, 1.70, 2.05)
    heights = (0.15, 0.30, 0.45, 0.60)
    y_min, y_max = -0.50, 0.50
    treads = []
    previous_height = 0.0
    for x_min, x_max, z in zip(edges, edges[1:], heights):
        hit(2, z, ((0, x_min, x_max), (1, y_min, y_max)))
        hit(0, x_min, ((1, y_min, y_max), (2, previous_height, z)))
        for side in (y_min, y_max):
            hit(1, side, ((0, x_min, x_max), (2, 0.0, z)))
        treads.append({
            "x_min_m": x_min, "x_max_m": x_max, "y_min_m": y_min, "y_max_m": y_max,
            "z_m": z, "riser_height_m": 0.15, "tread_depth_m": 0.35, "width_m": 1.0,
        })
        previous_height = z
    hit(0, edges[-1], ((1, y_min, y_max), (2, 0.0, heights[-1])))

    quantized = np.rint(nearest / depth_scale)
    valid = (quantized >= 1) & (quantized <= np.iinfo(np.uint16).max)
    raw = np.where(valid, quantized, 0).astype(np.uint16)
    intrinsics = {
        "width": width, "height": height, "fx": fx, "fy": fy, "cx": cx, "cy": cy,
        "distortion": "none", "coefficients": [],
    }
    calibration = {
        "rotation": rotation.tolist(), "translation_m": origin.tolist(),
        "target_frame": "gravity", "ground_z_m": 0.0, "source": "synthetic",
    }
    truth = {
        "frame_id": "gravity", "axes": {"x": "forward", "y": "left", "z": "up"},
        "ground_z_m": 0.0, "treads": treads,
    }
    return raw, intrinsics, depth_scale, calibration, truth
