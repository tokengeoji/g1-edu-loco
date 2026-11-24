"""Measure and display stairs from live or recorded depth."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from g1stairs.camera.realsense import CameraError
from g1stairs.session import create_part, dump_line, read_json, read_jsonl, recorded_frame_path, run_path

from . import calibration_points, feasibility, live
from .projection import camera_rays, deproject, load_calibration
from .surfaces import MeasurementOptions, measure_surfaces
from .terminal import format_stairs
from .terminal_map import format_stair_map


def _selected_frames(depth_path, args):
    for sample in read_jsonl(depth_path / "frames.jsonl"):
        if args.frame_number is not None and sample["frame_number"] != args.frame_number:
            continue
        yield sample, recorded_frame_path(depth_path, sample)
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
    input_frame = depth_manifest.get("frame_id")
    calibration, calibration_json = load_calibration(calibration_path, input_frame)
    rays = camera_rays(depth_manifest["intrinsics"])
    scale = float(depth_manifest["depth_scale_m"])
    options = MeasurementOptions(args.grid_m, args.height_tolerance_m, args.min_samples)
    metadata = {
        "source": depth_manifest["source"],
        "clock_domain": depth_manifest["clock_domain"],
        "frame_id": calibration.frame_id,
        "coordinate_axes": {"x": "forward", "y": "left", "z": "up"},
        "input_frame_id": input_frame,
        "calibration_source_frame_check": "matched" if "source_frame" in calibration_json else "unspecified",
        "deprojection": "librealsense.rs2_deproject_pixel_to_point",
        "surface_estimation": "project_horizontal_surfaces",
        "flight_estimation": "monotonic_treads_with_witnessed_shared_boundaries",
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
        "stair_flights": first["stair_flights"],
        "treads": [
            {key: tread[key] for key in ("z_m", "riser_height_m", "tread_depth_m", "width_m", "dimension_status")}
            for tread in first["treads"]
        ],
    }


def _view(args):
    geometry = run_path(args.runs_dir, args.run) / "geometry"
    if read_json(geometry / "manifest.json").get("complete") is not True:
        raise ValueError("finish the geometry measurement before viewing it")
    for frame in read_jsonl(geometry / "stairs.jsonl"):
        if args.frame_number is None or frame["frame_number"] == args.frame_number:
            print(format_stairs(frame))
            if args.map:
                print(format_stair_map(frame))
            return
    raise ValueError("no matching measured frame")


def add_surface_options(parser):
    parser.add_argument("--grid-m", type=float, default=0.025)
    parser.add_argument("--height-tolerance-m", type=float, default=0.018)
    parser.add_argument("--min-samples", type=int, default=45)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="g1 stairs", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    calibrate = subparsers.add_parser("calibrate", help="calibrate a fixed camera pose from surveyed depth pixels")
    calibration_points.configure_parser(calibrate)
    calibrate.set_defaults(handler=calibration_points.run)
    live_parser = subparsers.add_parser("live", help="show stair measurements from the head camera in this terminal")
    live.configure_parser(live_parser)
    add_surface_options(live_parser)
    live_parser.set_defaults(handler=live.run)
    measure = subparsers.add_parser("measure", help="write measured horizontal surfaces from saved frames")
    measure.set_defaults(handler=_measure)
    measure.add_argument("--runs-dir", type=Path, default=Path("runs"))
    measure.add_argument("--run", required=True)
    measure.add_argument("--calibration", type=Path, help="default: depth/calibration.json in this run")
    frames = measure.add_mutually_exclusive_group()
    frames.add_argument("--frame-number", type=int, help="default: first recorded frame")
    frames.add_argument("--all-frames", action="store_true", help="reuse the fixed calibration for all frames")
    add_surface_options(measure)
    view = subparsers.add_parser("view", help="show a saved stair measurement in this terminal")
    view.add_argument("--runs-dir", type=Path, default=Path("runs"))
    view.add_argument("--run", required=True)
    view.add_argument("--frame-number", type=int, help="default: first measured frame")
    view.add_argument("--map", action="store_true", help="also show a top-down view of observed cells")
    view.set_defaults(handler=_view)
    assess = subparsers.add_parser("assess", help="check foot support and optional reach on a saved measurement")
    feasibility.configure_parser(assess)
    assess.set_defaults(handler=feasibility.run)
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, CameraError) as error:
        print("geometry: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
