"""CLI for native uint16 depth capture, fixtures and replay."""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from g1stairs.session import create_part, dump_line, read_json, read_jsonl, run_path, write_json

from . import realsense
from .synthetic import stairs_fixture


def _metadata(source, clock):
    return {
        "source": source,
        "clock_domain": clock,
        "encoding": "Z16",
        "dtype": "uint16",
        "invalid_depth_code": 0,
        "frame_id": "camera_depth_optical",
    }


def _point_to_frame(path, handle, index, image, sample):
    relative_file = f"frames/{index:06d}.npy"
    np.save(path / relative_file, image, allow_pickle=False)
    dump_line(handle, dict(sample, file=relative_file))


def _fixture(args):
    image, intrinsics, scale, calibration, truth = stairs_fixture()
    metadata = _metadata("synthetic", "synthetic_monotonic_ns")
    metadata.update(intrinsics=intrinsics, depth_scale_m=scale, fps=args.fps, frame_count=args.frames)
    with create_part(args.runs_dir, args.run, "depth", metadata) as path:
        (path / "frames").mkdir()
        write_json(path / "calibration.json", calibration)
        write_json(path / "truth.json", truth)
        with (path / "frames.jsonl").open("w", encoding="utf-8") as handle:
            for index in range(args.frames):
                timestamp_ns = 1_000_000_000 + round(index * 1_000_000_000 / args.fps)
                _point_to_frame(path, handle, index, image, {
                    "frame_number": index,
                    "host_rx_monotonic_ns": timestamp_ns,
                    "device_timestamp_ms": timestamp_ns / 1_000_000,
                    "device_timestamp_domain": "synthetic",
                })
    return {"source": "synthetic", "part": str(run_path(args.runs_dir, args.run) / "depth"),
            "frame_count": args.frames}


def _record(args):
    if bool(args.width) != bool(args.height):
        raise ValueError("--width and --height must be given together")
    calibration = read_json(args.calibration) if args.calibration else None
    metadata = _metadata("realsense", "host_monotonic_ns")
    with create_part(args.runs_dir, args.run, "depth", metadata) as path:
        if calibration is not None:
            write_json(path / "calibration.json", calibration)
        (path / "frames").mkdir()
        index = 0
        with (path / "frames.jsonl").open("w", encoding="utf-8") as handle:
            def write_frame(image, sample):
                nonlocal index
                _point_to_frame(path, handle, index, image, sample)
                index += 1

            realsense.record(args.seconds, args.width, args.height, args.fps, args.device_index,
                             write_frame, metadata)
        metadata["frame_count"] = index
    return _replay(args)


def _recorded_frames(path):
    for sample in read_jsonl(path / "frames.jsonl"):
        relative = Path(sample["file"])
        if (len(relative.parts) != 2 or relative.parts[0] != "frames" or
                relative.suffix != ".npy"):
            raise ValueError(f"invalid frame path: {relative}")
        frame_path = path / relative
        if frame_path.resolve().parent != (path / "frames").resolve():
            raise ValueError(f"frame path leaves the session frame directory: {relative}")
        yield sample, np.load(frame_path, allow_pickle=False)


def _replay(args):
    path = run_path(args.runs_dir, args.run) / "depth"
    metadata = read_json(path / "manifest.json")
    intrinsics = metadata["intrinsics"]
    expected_shape = (intrinsics["height"], intrinsics["width"])
    scale = metadata["depth_scale_m"]
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("manifest depth_scale_m must be positive and finite")
    first_host_ns = previous_host_ns = previous_number = None
    minimum = maximum = None
    invalid = pixels = skipped = discontinuities = count = 0
    for sample, image in _recorded_frames(path):
        if image.dtype != np.uint16 or image.shape != expected_shape:
            raise ValueError(f"invalid shape or dtype in {sample['file']}")
        number = sample["frame_number"]
        host_ns = sample["host_rx_monotonic_ns"]
        if previous_number is not None:
            if number > previous_number:
                skipped += number - previous_number - 1
            else:
                discontinuities += 1
            if host_ns < previous_host_ns:
                raise ValueError("host receive timestamps are out of order")
        else:
            first_host_ns = host_ns
        previous_number, previous_host_ns = number, host_ns
        valid = image[image != metadata["invalid_depth_code"]]
        if valid.size:
            frame_min, frame_max = int(valid.min()), int(valid.max())
            minimum = frame_min if minimum is None else min(minimum, frame_min)
            maximum = frame_max if maximum is None else max(maximum, frame_max)
        pixels += image.size
        invalid += image.size - valid.size
        count += 1
    if not count or count != metadata["frame_count"]:
        raise ValueError("recording frame count is empty or inconsistent with its manifest")
    elapsed = (previous_host_ns - first_host_ns) / 1e9
    return {
        "part": str(path),
        "source": metadata["source"],
        "frame_count": count,
        "clock_domain": metadata["clock_domain"],
        "width": intrinsics["width"],
        "height": intrinsics["height"],
        "depth_scale_m": scale,
        "elapsed_s": elapsed,
        "observed_fps": (count - 1) / elapsed if elapsed > 0 else None,
        "frame_number_gap_total": skipped,
        "nonincreasing_frame_numbers": discontinuities,
        "invalid_depth_fraction": invalid / pixels,
        "min_depth_m": None if minimum is None else minimum * scale,
        "max_depth_m": None if maximum is None else maximum * scale,
        "empty_polls": metadata.get("empty_polls", 0),
        "calibration_available": (path / "calibration.json").is_file(),
    }


def _int_at_least(minimum):
    def parse(raw):
        value = int(raw)
        if value < minimum:
            raise argparse.ArgumentTypeError(f"must be at least {minimum}")
        return value
    return parse


def _positive(raw):
    value = float(raw)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("must be positive and finite")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("fixture", help="write a synthetic staircase run")
    probe = commands.add_parser("probe", help="enumerate native Z16 profiles without streaming")
    record = commands.add_parser("record", help="start a RealSense depth stream and record it")
    replay = commands.add_parser("replay", help="validate and summarize every stored frame")
    for command in (fixture, probe, record, replay):
        command.add_argument("--runs-dir", type=Path, default=Path("runs"))
        if command is not probe:
            command.add_argument("--run", required=True)
    fixture.add_argument("--frames", type=_int_at_least(1), default=8)
    fixture.add_argument("--fps", type=_int_at_least(1), default=30)
    for command in (probe, record):
        command.add_argument("--source", choices=("realsense",), default="realsense")
    record.add_argument("--device-index", type=_int_at_least(0))
    record.add_argument("--width", type=_int_at_least(0), default=0)
    record.add_argument("--height", type=_int_at_least(0), default=0)
    record.add_argument("--fps", type=_int_at_least(0), default=0)
    record.add_argument("--seconds", type=_positive, default=10.0)
    record.add_argument("--calibration", type=Path)
    probe.set_defaults(action=lambda _: realsense.probe())
    fixture.set_defaults(action=_fixture)
    record.set_defaults(action=_record)
    replay.set_defaults(action=_replay)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(args.action(args), ensure_ascii=False, indent=2, allow_nan=False))
    except (KeyError, TypeError, ValueError, OSError, realsense.CameraError) as exc:
        if isinstance(exc, realsense.CameraError):
            status, _, detail = str(exc).partition(": ")
        else:
            status, detail = "DEPTH_COMMAND_FAILED", str(exc)
        print(json.dumps({"status": status, "detail": detail}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("카메라 작업을 중단했습니다.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
