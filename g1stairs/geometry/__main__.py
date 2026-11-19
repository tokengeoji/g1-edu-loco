"""Estimate horizontal stair geometry from a completed raw-depth recording."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from g1stairs.session import create_part, dump_line, read_json, read_jsonl, run_path

from .projection import Calibration, camera_rays, deproject
from .surfaces import MeasurementOptions, measure_surfaces


def _frame_file(depth_path, sample):
    relative = Path(sample["file"])
    if len(relative.parts) != 2 or relative.parts[0] != "frames" or relative.suffix != ".npy":
        raise ValueError("invalid recorded frame path: %s" % relative)
    frame_path = depth_path / relative
    if frame_path.resolve().parent != (depth_path / "frames").resolve():
        raise ValueError("recorded frame path leaves the frames directory: %s" % relative)
    return frame_path


def _selected_frames(depth_path, args):
    for sample in read_jsonl(depth_path / "frames.jsonl"):
        if args.frame_number is not None and sample["frame_number"] != args.frame_number:
            continue
        yield sample, _frame_file(depth_path, sample)
        if not args.all_frames:
            return


def _measure(args):
    run = run_path(args.runs_dir, args.run)
    depth_path = run / "depth"
    depth_manifest = read_json(depth_path / "manifest.json")
    if depth_manifest.get("complete") is not True:
        raise ValueError("finish the depth recording before measuring geometry")
    if depth_manifest.get("encoding") != "Z16" or depth_manifest.get("invalid_depth_code", 0) != 0:
        raise ValueError("expected recorded Z16 depth with invalid code 0")

    calibration_path = args.calibration or depth_path / "calibration.json"
    if not calibration_path.is_file():
        raise ValueError("provide an optical-to-gravity calibration with --calibration")
    calibration_json = read_json(calibration_path)
    if "frame_id" not in calibration_json and "target_frame" in calibration_json:
        calibration_json["frame_id"] = calibration_json["target_frame"]
    calibration = Calibration.from_mapping(calibration_json)
    rays = camera_rays(depth_manifest["intrinsics"])
    scale = float(depth_manifest["depth_scale_m"])
    options = MeasurementOptions(args.grid_m, args.height_tolerance_m, args.min_samples)
    metadata = {
        "source": depth_manifest["source"],
        "clock_domain": depth_manifest["clock_domain"],
        "frame_id": calibration.frame_id,
        "coordinate_axes": {"x": "forward", "y": "left", "z": "up"},
        "input_frame_id": depth_manifest.get("frame_id"),
        "calibration": calibration_json,
        "calibration_scope": "fixed_pose_per_run",
        "units": {"distance": "m", "host_rx_monotonic_ns": "ns"},
        "grid_origin_xy_m": [0, 0],
        "surface_options": vars(options),
        "frame_count": 0,
    }
    count = 0
    first = None
    with create_part(args.runs_dir, args.run, "geometry", metadata) as output:
        with (output / "stairs.jsonl").open("w", encoding="utf-8") as handle:
            for sample, frame_file in _selected_frames(depth_path, args):
                depth = np.load(frame_file, allow_pickle=False)
                points = deproject(depth, rays, scale, calibration)
                result = measure_surfaces(points, calibration.translation_m, calibration.ground_z_m, options)
                result.update(
                    frame_number=sample["frame_number"],
                    host_rx_monotonic_ns=sample["host_rx_monotonic_ns"],
                    frame_id=calibration.frame_id,
                )
                dump_line(handle, result)
                if first is None:
                    first = result
                count += 1
        if first is None:
            raise ValueError("no matching recorded depth frame")
        metadata["frame_count"] = count

    return {
        "source": metadata["source"],
        "part": str(run / "geometry"),
        "frame_count": count,
        "first_frame_number": first["frame_number"],
        "first_frame_status": first["status"],
        "treads": [
            {key: tread[key] for key in ("z_m", "riser_height_m", "tread_depth_m", "width_m", "dimension_status")}
            for tread in first["treads"]
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    measure = subparsers.add_parser("measure", help="write measured horizontal surfaces from saved frames")
    measure.add_argument("--runs-dir", type=Path, default=Path("runs"))
    measure.add_argument("--run", required=True)
    measure.add_argument("--calibration", type=Path, help="default: depth/calibration.json in this run")
    frames = measure.add_mutually_exclusive_group()
    frames.add_argument("--frame-number", type=int, help="default: first recorded frame")
    frames.add_argument("--all-frames", action="store_true", help="reuse the fixed calibration for all frames")
    measure.add_argument("--grid-m", type=float, default=0.025)
    measure.add_argument("--height-tolerance-m", type=float, default=0.018)
    measure.add_argument("--min-samples", type=int, default=45)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(_measure(args), ensure_ascii=False, allow_nan=False, indent=2))
    except (OSError, ValueError, KeyError) as error:
        print("geometry: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
