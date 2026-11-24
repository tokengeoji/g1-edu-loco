"""Convert stored depth samples to metric coordinates without filling missing pixels."""

from dataclasses import dataclass

import numpy as np
from g1stairs.session import read_json


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


def load_calibration(path, input_frame):
    values = read_json(path)
    if "frame_id" not in values and "target_frame" in values:
        values["frame_id"] = values["target_frame"]
    if "source_frame" in values:
        source = values["source_frame"]
        if not isinstance(source, str) or not source.strip() or source != input_frame:
            raise ValueError(f"calibration source_frame {source!r} does not match depth frame {input_frame!r}")
    return Calibration.from_mapping(values), values


def _sdk_rays(width, height, intrinsics, model, coefficients):
    try:
        import pyrealsense2 as rs
    except (ImportError, OSError) as error:
        raise ValueError(
            "cannot load the RealSense SDK (pyrealsense2) for depth deprojection: %s" % error
        ) from error
    sdk_intrinsics = rs.intrinsics()
    sdk_intrinsics.width, sdk_intrinsics.height = width, height
    sdk_intrinsics.fx, sdk_intrinsics.fy, sdk_intrinsics.ppx, sdk_intrinsics.ppy = intrinsics
    sdk_intrinsics.model = getattr(rs.distortion, model)
    sdk_intrinsics.coeffs = list(coefficients)
    # Every depth frame in this recording shares these unit-depth rays.
    rays = np.empty((height, width, 3), dtype=np.float32)
    for v, row in enumerate(rays):
        for u in range(width):
            row[u] = rs.rs2_deproject_pixel_to_point(sdk_intrinsics, [u, v], 1.0)
    if not np.all(np.isfinite(rays)):
        raise ValueError("RealSense SDK returned non-finite rays for the recorded intrinsics")
    return rays


def camera_rays(intrinsics):
    """Compute reusable optical rays with librealsense for every recorded depth source."""
    width, height = int(intrinsics["width"]), int(intrinsics["height"])
    fx, fy, cx, cy = (float(intrinsics[key]) for key in ("fx", "fy", "cx", "cy"))
    if width < 2 or height < 2 or fx <= 0 or fy <= 0 or not np.all(np.isfinite((fx, fy, cx, cy))):
        raise ValueError("invalid depth intrinsics")
    model = str(intrinsics["distortion"]).strip().lower().split(".")[-1]
    coefficients = np.asarray(intrinsics.get("coefficients", []), dtype=float)
    if coefficients.ndim != 1 or not np.all(np.isfinite(coefficients)):
        raise ValueError("invalid distortion coefficients")
    if model not in ("none", "brown_conrady", "inverse_brown_conrady", "kannala_brandt4", "ftheta"):
        raise ValueError("unsupported depth distortion model: %s" % model)
    if model == "none":
        coefficients = np.zeros(5)
    elif coefficients.shape != (5,):
        raise ValueError("%s requires five distortion coefficients" % model)
    return _sdk_rays(width, height, (fx, fy, cx, cy), model, coefficients)


def deproject(depth, rays, depth_scale_m, calibration):
    if depth.dtype.kind != "u" or depth.dtype.itemsize != 2 or depth.shape != rays.shape[:2]:
        raise ValueError("depth must be a uint16 image matching the recorded intrinsics")
    if not np.isfinite(depth_scale_m) or depth_scale_m <= 0:
        raise ValueError("depth_scale_m must be finite and positive")
    points = (rays * (depth.astype(float) * depth_scale_m)[..., None]) @ calibration.rotation.T
    points += calibration.translation_m
    points[depth == 0] = np.nan
    return points
