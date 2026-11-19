"""Read-only RealSense depth adapter, loaded only for hardware CLI commands."""

import math
import sys
import time

import numpy as np


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


def probe():
    """Read device capabilities without starting any stream."""
    rs = _sdk()
    results = []
    try:
        context = rs.context()
        for index, device in enumerate(_devices(context)):
            profiles = {
                (video.width(), video.height(), video.fps())
                for sensor in device.query_sensors()
                for profile in sensor.get_stream_profiles()
                if profile.stream_type() == rs.stream.depth and profile.format() == rs.format.z16
                for video in (profile.as_video_stream_profile(),)
            }
            results.append({
                "device_index": index,
                "model": _device_info(device, rs.camera_info.name),
                "z16_profiles": [{"width": w, "height": h, "fps": fps} for w, h, fps in sorted(profiles)],
            })
    except CameraError:
        raise
    except RuntimeError as exc:
        raise _classify(exc, "PROBE_FAILED") from exc
    return {"source": "realsense", "devices": results, "stream_started": False}


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
    if device_index is None:
        if len(devices) != 1:
            raise CameraError("DEVICE_AMBIGUOUS: run probe and pass --device-index")
        device_index = 0
    if not 0 <= device_index < len(devices):
        raise CameraError("DEVICE_NOT_VISIBLE: selected device index is unavailable")
    device = devices[device_index]
    serial = _device_info(device, rs.camera_info.serial_number)
    if serial is not None:
        config.enable_device(serial)
    elif len(devices) > 1:
        raise CameraError("DEVICE_AMBIGUOUS: SDK cannot resolve the selected device")
    return _device_info(device, rs.camera_info.name)


def record(seconds, width, height, fps, device_index, write_frame, metadata):
    """Start one Z16 stream for an explicitly requested recording window."""
    rs = _sdk()
    active = False
    try:
        context = rs.context()
        pipeline = rs.pipeline(context)
        config = rs.config()
        model = _select_device(rs, context, config, device_index)
        config.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
        pipeline_profile = pipeline.start(config)
        active = True
        profile = pipeline_profile.get_stream(rs.stream.depth).as_video_stream_profile()
        intr = profile.get_intrinsics()
        metadata.update(
            model=model, fps=profile.fps(),
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
