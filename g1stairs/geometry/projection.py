"""Convert stored depth samples to metric coordinates without filling missing pixels."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Calibration:
    rotation: np.ndarray
    translation_m: np.ndarray
    frame_id: str
    ground_z_m: float = None

    @classmethod
    def from_mapping(cls, values):
        rotation = np.asarray(values["rotation"], dtype=float)
        translation = np.asarray(values["translation_m"], dtype=float)
        if rotation.shape != (3, 3) or translation.shape != (3,):
            raise ValueError("calibration rotation must be 3×3 and translation_m must have three values")
        if not (np.all(np.isfinite(rotation)) and np.all(np.isfinite(translation))):
            raise ValueError("calibration must be finite")
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-4) or not np.isclose(
            np.linalg.det(rotation), 1.0, atol=1e-4
        ):
            raise ValueError("calibration requires a proper camera-to-gravity rotation")
        frame_id = values.get("frame_id", "gravity_aligned")
        if not isinstance(frame_id, str) or not frame_id.strip():
            raise ValueError("calibration frame_id must be a nonempty string")
        ground = values.get("ground_z_m")
        ground = None if ground is None else float(ground)
        if ground is not None and not np.isfinite(ground):
            raise ValueError("calibration ground_z_m must be finite")
        return cls(rotation, translation, frame_id, ground)


def _brown_conrady_rays(x_distorted, y_distorted, coefficients):
    k1, k2, p1, p2, k3 = coefficients
    x, y = x_distorted, y_distorted
    for _ in range(16):
        radius_sq = x * x + y * y
        radial = 1 + radius_sq * (k1 + radius_sq * (k2 + radius_sq * k3))
        tangent_x = 2 * p1 * x * y + p2 * (radius_sq + 2 * x * x)
        tangent_y = 2 * p2 * x * y + p1 * (radius_sq + 2 * y * y)
        if not np.all(np.isfinite(radial)) or np.any(np.abs(radial) < 1e-9):
            raise ValueError("Brown-Conrady intrinsics produced an invalid inverse")
        next_x = (x_distorted - tangent_x) / radial
        next_y = (y_distorted - tangent_y) / radial
        error = max(float(np.max(np.abs(next_x - x))), float(np.max(np.abs(next_y - y))))
        x, y = next_x, next_y
        if error < 1e-7:
            return x, y
    raise ValueError("Brown-Conrady depth deprojection did not converge")


def _sdk_rays(width, height, intrinsics, model, coefficients):
    try:
        import pyrealsense2 as rs
    except ImportError as error:
        raise ValueError(
            "distortion %s requires the optional pyrealsense2 SDK for exact deprojection" % model
        ) from error
    sdk_intrinsics = rs.intrinsics()
    sdk_intrinsics.width, sdk_intrinsics.height = width, height
    sdk_intrinsics.fx, sdk_intrinsics.fy, sdk_intrinsics.ppx, sdk_intrinsics.ppy = intrinsics
    sdk_intrinsics.model = getattr(rs.distortion, model)
    sdk_intrinsics.coeffs = list(coefficients)
    return np.array(
        [
            rs.rs2_deproject_pixel_to_point(sdk_intrinsics, [float(u), float(v)], 1.0)
            for v in range(height)
            for u in range(width)
        ]
    ).reshape(height, width, 3)


def camera_rays(intrinsics):
    width, height = int(intrinsics["width"]), int(intrinsics["height"])
    fx, fy, cx, cy = (float(intrinsics[key]) for key in ("fx", "fy", "cx", "cy"))
    if width < 2 or height < 2 or fx <= 0 or fy <= 0 or not np.all(np.isfinite((fx, fy, cx, cy))):
        raise ValueError("invalid depth intrinsics")
    model = str(intrinsics["distortion"]).strip().lower().split(".")[-1]
    coefficients = np.asarray(intrinsics.get("coefficients", []), dtype=float)
    if coefficients.ndim != 1 or not np.all(np.isfinite(coefficients)):
        raise ValueError("invalid distortion coefficients")
    if model != "none" and coefficients.shape != (5,):
        raise ValueError("%s requires five distortion coefficients" % model)
    if model in ("inverse_brown_conrady", "kannala_brandt4", "ftheta"):
        return _sdk_rays(width, height, (fx, fy, cx, cy), model, coefficients)
    if model not in ("none", "brown_conrady"):
        raise ValueError("unsupported depth distortion model: %s" % model)
    u, v = np.meshgrid(np.arange(width, dtype=float), np.arange(height, dtype=float))
    x, y = (u - cx) / fx, (v - cy) / fy
    if model == "brown_conrady":
        x, y = _brown_conrady_rays(x, y, coefficients)
    return np.stack((x, y, np.ones_like(x)), axis=-1)


def deproject(depth, rays, depth_scale_m, calibration):
    if depth.dtype.kind != "u" or depth.dtype.itemsize != 2 or depth.shape != rays.shape[:2]:
        raise ValueError("depth must be a uint16 image matching the recorded intrinsics")
    if not np.isfinite(depth_scale_m) or depth_scale_m <= 0:
        raise ValueError("depth_scale_m must be finite and positive")
    points = (rays * (depth.astype(float) * depth_scale_m)[..., None]) @ calibration.rotation.T
    points += calibration.translation_m
    points[depth == 0] = np.nan
    return points
