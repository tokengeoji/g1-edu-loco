# Author: Codex (IIC)
"""Estimate a fixed camera-to-gravity transform from measured depth-image landmarks."""

import csv
import json
import os
import tempfile
from pathlib import Path

import numpy as np

from g1stairs.camera.inspection import save_depth_preview
from g1stairs.session import read_json, read_jsonl, recorded_frame_path, run_path

from .projection import Calibration, camera_rays


def configure_parser(parser):
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--frame-number", type=int, help="recorded frame number (default: first frame)")
    parser.add_argument("--points", type=Path, help="CSV with use,u,v,x_m,y_m,z_m; omit to export a pixel preview")
    parser.add_argument("--ground-z-m", type=float, help="surveyed reference floor z in metres, for a fitted transform")
    parser.add_argument("--output", type=Path, help="new preview PNG or calibration JSON file")


def _read_points(csv_path, raw, rays, scale):
    pixels, surveyed, optical, fit = [], [], [], []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["use", "u", "v", "x_m", "y_m", "z_m"]:
            raise ValueError("CSV header must be use,u,v,x_m,y_m,z_m")
        for row in reader:
            try:
                role = row["use"].strip()
                u, v = int(row["u"]), int(row["v"])
                point = tuple(float(row[key]) for key in ("x_m", "y_m", "z_m"))
            except (AttributeError, TypeError, ValueError) as exc:
                raise ValueError("invalid point on CSV line %d" % reader.line_num) from exc
            if role not in ("fit", "check") or not np.isfinite(point).all() or None in row:
                raise ValueError("invalid use, coordinates or extra columns on CSV line %d" % reader.line_num)
            if (u, v) in pixels or point in surveyed:
                raise ValueError("repeated reference point on CSV line %d" % reader.line_num)
            if not (0 <= u < raw.shape[1] and 0 <= v < raw.shape[0]) or raw[v, u] == 0:
                raise ValueError("invalid depth at pixel (%d, %d)" % (u, v))
            pixels.append((u, v))
            surveyed.append(point)
            optical.append(rays[v, u].astype(float) * (int(raw[v, u]) * scale))
            fit.append(role == "fit")
    if sum(fit) < 3 or len(fit) == sum(fit):
        raise ValueError("supply at least three fit points and one independent check point")
    return pixels, np.array(optical), np.array(surveyed), np.array(fit)


def _fit_transform(optical, surveyed):
    a, b = optical.mean(axis=0), surveyed.mean(axis=0)
    left, singular, right_t = np.linalg.svd((optical - a).T @ (surveyed - b))
    if singular[0] <= 0 or singular[1] <= singular[0] * 1e-10:
        raise ValueError("degenerate fit: choose non-collinear, well-spaced reference points")
    correction = np.diag([1., 1., np.sign(np.linalg.det(right_t.T @ left.T))])
    rotation = right_t.T @ correction @ left.T
    return rotation, b - rotation @ a


def run(args):
    run_dir = run_path(args.runs_dir, args.run)
    depth = run_dir / "depth"
    meta = read_json(depth / "manifest.json")
    if (meta.get("complete") is not True or meta.get("encoding") != "Z16"
            or meta.get("invalid_depth_code", 0) != 0):
        raise ValueError("expected a completed Z16 depth recording with invalid code 0")
    sample = next((s for s in read_jsonl(depth / "frames.jsonl")
                   if args.frame_number is None or s["frame_number"] == args.frame_number), None)
    if sample is None:
        raise ValueError("no matching recorded frame number")
    raw = np.load(recorded_frame_path(depth, sample), allow_pickle=False)
    intr = meta["intrinsics"]
    if raw.dtype != np.uint16 or raw.shape != (intr["height"], intr["width"]):
        raise ValueError("depth frame must be uint16 and match the recorded camera dimensions")
    number = sample["frame_number"]
    result = {"frame_number": number, "source_file": sample["file"]}
    if args.points is None:
        if args.ground_z_m is not None:
            raise ValueError("--ground-z-m applies when fitting a transform with --points")
        output = args.output or run_dir / ("pixels-%d.png" % number)
        preview = save_depth_preview(output, raw)
        return dict(result, output=preview["path"], near_raw=preview["near_raw"], far_raw=preview["far_raw"])
    scale = float(meta["depth_scale_m"])
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("depth_scale_m must be finite and positive")
    pixels, optical, surveyed, fit = _read_points(args.points, raw, camera_rays(intr), scale)
    rotation, translation = _fit_transform(optical[fit], surveyed[fit])
    predicted = optical @ rotation.T + translation
    errors = np.linalg.norm(predicted - surveyed, axis=1)
    checks = [{"pixel_uv": pixels[i], "estimated_m": predicted[i].tolist(),
               "surveyed_m": surveyed[i].tolist(), "error_m": float(errors[i])}
              for i in np.flatnonzero(~fit)]
    source = meta.get("frame_id")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("the recorded optical frame_id is missing")
    cal = {"source_frame": source, "frame_id": "stair_gravity", "rotation": rotation.tolist(),
           "translation_m": translation.tolist(), "ground_z_m": args.ground_z_m}
    Calibration.from_mapping(cal)
    result.update(fit_rmse_m=float(np.sqrt(np.mean(errors[fit] ** 2))), check_points=checks)
    cal["point_validation"] = result.copy()
    output = args.output or run_dir / "measured-calibration.json"
    data = (json.dumps(cal, indent=2, allow_nan=False) + "\n").encode()
    # Publish only the completed file, preserving any existing output on a retry.
    with tempfile.NamedTemporaryFile(dir=output.parent) as temp:
        temp.write(data)
        temp.flush()
        os.link(temp.name, output)
    return dict(result, output=str(output))
