"""Head-mounted RealSense D435i depth input from the Unitree G1 Development Guide."""

import math
import re
import sys
import time

import numpy as np


G1_HEAD_MODEL = "D435i"
G1_DEPTH_PROFILE = (640, 480, 60)


class CameraError(RuntimeError):
    """A camera failure with an actionable status."""


def _sdk():
    try:
        import pyrealsense2 as rs
    except (ImportError, OSError) as exc:
        raise CameraError(f"DEPENDENCY_MISSING: pyrealsense2 failed to load: {exc}") from exc
    return rs


def _enum_name(value):
    return str(value).rsplit(".", 1)[-1].lower()


def _device_info(device, field):
    return device.get_info(field) if device.supports(field) else None


def _devices(context):
    devices = list(context.query_devices())
    if not devices:
        raise CameraError("DEVICE_NOT_VISIBLE: RealSense SDK detected no device in this environment")
    return devices


def _is_g1_head_camera(model):
    return bool(model and re.search(r"\bD435I\b", model, re.IGNORECASE))


def _depth_profiles(rs, device):
    return {
        (video.width(), video.height(), video.fps())
        for sensor in device.query_sensors()
        for profile in sensor.get_stream_profiles()
        if profile.stream_type() == rs.stream.depth and profile.format() == rs.format.z16
        for video in (profile.as_video_stream_profile(),)
    }


def _describe_profile(profile):
    width, height, fps = profile
    return {"width": width, "height": height, "fps": fps}


def probe():
    """Read device capabilities without starting any stream."""
    rs = _sdk()
    results = []
    try:
        context = rs.context()
        for index, device in enumerate(_devices(context)):
            model = _device_info(device, rs.camera_info.name)
            profiles = _depth_profiles(rs, device)
            results.append({
                "device_index": index,
                "model": model,
                "matches_g1_head_model": _is_g1_head_camera(model),
                "supports_guide_depth_profile": G1_DEPTH_PROFILE in profiles,
                "z16_profiles": [_describe_profile(profile) for profile in sorted(profiles)],
            })
    except CameraError:
        raise
    except RuntimeError as exc:
        raise _classify(exc, "PROBE_FAILED") from exc
    return {
        "source": "realsense",
        "guide_camera_model": G1_HEAD_MODEL,
        "guide_depth_profile": dict(_describe_profile(G1_DEPTH_PROFILE), encoding="Z16"),
        "devices": results,
        "stream_started": False,
    }


def _classify(exc, fallback):
    message = str(exc)
    normalized = message.lower()
    if "busy" in normalized or "already streaming" in normalized:
        status = "DEVICE_BUSY"
    elif any(term in normalized for term in ("permission denied", "access denied", "insufficient permissions")):
        status = "DEVICE_ACCESS_BLOCKED"
    else:
        status = fallback
    return CameraError(f"{status}: {message}")


def _select_device(rs, context, config, device_index):
    devices = _devices(context)
    models = [_device_info(device, rs.camera_info.name) for device in devices]
    if device_index is None:
        matches = [index for index, model in enumerate(models) if _is_g1_head_camera(model)]
        if not matches:
            raise CameraError(f"DEVICE_MODEL_MISMATCH: expected {G1_HEAD_MODEL}; detected {models}")
        if len(matches) > 1:
            raise CameraError("DEVICE_AMBIGUOUS: multiple D435i cameras; run probe and pass --device-index")
        device_index = matches[0]
    elif not 0 <= device_index < len(devices):
        raise CameraError("DEVICE_NOT_VISIBLE: selected device index is unavailable")
    model = models[device_index]
    if not _is_g1_head_camera(model):
        raise CameraError(f"DEVICE_MODEL_MISMATCH: expected {G1_HEAD_MODEL}; selected {model!r}")
    device = devices[device_index]
    serial = _device_info(device, rs.camera_info.serial_number)
    if serial is not None:
        config.enable_device(serial)
    elif len(devices) > 1:
        raise CameraError("DEVICE_AMBIGUOUS: SDK cannot resolve the selected device")
    return device, model


def record(seconds, width, height, fps, device_index, write_frame, metadata):
    """Start a supported D435i Z16 stream for an explicitly requested recording window."""
    rs = _sdk()
    active = False
    try:
        context = rs.context()
        config = rs.config()
        device, model = _select_device(rs, context, config, device_index)
        requested_profile = (width, height, fps)
        if requested_profile not in _depth_profiles(rs, device):
            raise CameraError(
                f"DEPTH_PROFILE_UNSUPPORTED: {model} does not report {width}x{height} at {fps} Hz Z16; "
                "run probe and choose a listed profile with --width, --height and --fps"
            )
        pipeline = rs.pipeline(context)
        config.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
        pipeline_profile = pipeline.start(config)
        active = True
        profile = pipeline_profile.get_stream(rs.stream.depth).as_video_stream_profile()
        intr = profile.get_intrinsics()
        actual_profile = (intr.width, intr.height, profile.fps())
        if actual_profile != requested_profile or profile.format() != rs.format.z16:
            raise CameraError("DEPTH_PROFILE_MISMATCH: active depth profile differs from the request")
        metadata.update(
            model=model, guide_camera_model=G1_HEAD_MODEL, fps=actual_profile[2],
            requested_depth_profile=_describe_profile(requested_profile),
            depth_scale_source="librealsense.depth_frame.get_units",
            intrinsics_source="librealsense.video_stream_profile.get_intrinsics",
            intrinsics={
                "width": intr.width, "height": intr.height, "fx": intr.fx, "fy": intr.fy,
                "cx": intr.ppx, "cy": intr.ppy, "distortion": _enum_name(intr.model),
                "coefficients": [float(value) for value in intr.coeffs],
            },
        )
        depth_scale = None
        count = 0
        timeouts = 0
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            remaining_ms = math.ceil((deadline - time.monotonic()) * 1000)
            received, frames = pipeline.try_wait_for_frames(max(1, min(remaining_ms, 1000)))
            host_rx_ns = time.monotonic_ns()
            frame = frames.get_depth_frame() if received else None
            if not frame:
                timeouts += 1
                continue
            image = np.asanyarray(frame.get_data())
            if image.dtype != np.uint16 or image.shape != (intr.height, intr.width):
                raise CameraError("DEPTH_FORMAT_MISMATCH: expected native uint16 Z16 at the selected profile")
            scale = float(frame.get_units())
            if not math.isfinite(scale) or scale <= 0:
                raise CameraError("INVALID_DEPTH_SCALE: camera returned an invalid unit conversion")
            if depth_scale is None:
                depth_scale = scale
            elif not math.isclose(scale, depth_scale, rel_tol=1e-9):
                raise CameraError("DEPTH_SCALE_CHANGED: one recording requires a consistent conversion")
            timestamp_ms = float(frame.get_timestamp())
            write_frame(image, {
                "frame_number": int(frame.get_frame_number()),
                "host_rx_monotonic_ns": host_rx_ns,
                "device_timestamp_ms": timestamp_ms if math.isfinite(timestamp_ms) else None,
                "device_timestamp_domain": _enum_name(frame.get_frame_timestamp_domain()),
            })
            count += 1
        if not count:
            raise CameraError("NO_DEPTH_FRAMES: no valid Z16 frame arrived within the recording window")
        metadata.update(depth_scale_m=depth_scale, empty_polls=timeouts, requested_seconds=seconds)
    except CameraError:
        raise
    except RuntimeError as exc:
        raise _classify(exc, "STREAM_READ_FAILED" if active else "STREAM_OPEN_FAILED") from exc
    finally:
        if active:
            failed = sys.exc_info()[0] is not None
            try:
                pipeline.stop()
            except RuntimeError as exc:
                if not failed:
                    raise _classify(exc, "STREAM_CLOSE_FAILED") from exc
