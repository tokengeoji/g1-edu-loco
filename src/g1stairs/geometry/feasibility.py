# Author: Codex (IIC)
"""Screen a finite sole against the measured support of one recorded frame.

Griffin et al., IEEE Humanoids 2019, intersect the foot with planar regions:
https://arxiv.org/abs/1907.08673
https://github.com/ihmcrobotics/ihmc-open-robotics-software/blob/4ffac8d49f68425ff89324b2e7402a0e5c9b8d91/ihmc-footstep-planning/src/main/java/us/ihmc/footstepPlanning/graphSearch/footstepSnapping/FootstepNodeSnappingTools.java#L28-L48

Here the support region is a union of observed horizontal grid cells. The
entire uncertainty-expanded rectangle must be covered; no gaps are filled.
"""

import math
from dataclasses import asdict, dataclass
from pathlib import Path

from g1stairs.session import read_json, read_jsonl, run_path


def _finite(value):
    return type(value) in (float, int) and math.isfinite(value)


@dataclass(frozen=True)
class Footprint:
    length_m: float
    width_m: float
    yaw_deg: float
    edge_margin_m: float
    position_uncertainty_m: float
    yaw_uncertainty_deg: float

    def __post_init__(self):
        if (not all(_finite(v) for v in asdict(self).values()) or min(self.length_m, self.width_m) <= 0
                or min(self.edge_margin_m, self.position_uncertainty_m) < 0
                or not 0 <= self.yaw_uncertainty_deg <= 180):
            raise ValueError("supply positive sole dimensions, nonnegative margins, and yaw uncertainty in [0,180]")

    def envelope(self):
        # The greatest displacement of any point during the yaw error is the
        # chord at the farthest corner. Enclose that disk in sole coordinates.
        rotation_error = math.hypot(self.length_m, self.width_m) * math.sin(math.radians(self.yaw_uncertainty_deg)/2)
        pad = self.edge_margin_m + self.position_uncertainty_m + rotation_error
        yaw = math.radians(self.yaw_deg % 360)
        return self.length_m/2 + pad, self.width_m/2 + pad, math.cos(yaw), math.sin(yaw)


@dataclass(frozen=True)
class Reach:
    stance_pose: tuple
    max_rise_m: float
    max_drop_m: float
    max_horizontal_reach_m: float
    max_yaw_change_deg: float
    height_uncertainty_m: float

    def __post_init__(self):
        limits = (self.max_rise_m, self.max_drop_m, self.max_horizontal_reach_m,
                  self.max_yaw_change_deg, self.height_uncertainty_m)
        if (len(self.stance_pose) != 4 or not all(_finite(v) for v in self.stance_pose)
                or not all(_finite(v) and v >= 0 for v in limits) or self.max_yaw_change_deg > 180):
            raise ValueError("supply a finite stance pose and nonnegative reach limits; maximum yaw must be <=180")

    def assess(self, x, y, z, foot):
        sx, sy, sz, syaw = self.stance_pose
        dz = z - sz
        distance = math.hypot(x - sx, y - sy)
        angle = abs((foot.yaw_deg - syaw + 180) % 360 - 180)
        outside = []
        if distance + foot.position_uncertainty_m > self.max_horizontal_reach_m:
            outside.append("horizontal")
        if dz + self.height_uncertainty_m > self.max_rise_m:
            outside.append("rise")
        if -dz + self.height_uncertainty_m > self.max_drop_m:
            outside.append("drop")
        if min(180, angle + foot.yaw_uncertainty_deg) > self.max_yaw_change_deg:
            outside.append("yaw")
        return {"status": "outside_envelope" if outside else "within_envelope", "outside_limits": outside,
                "horizontal_m": distance, "signed_height_change_m": dz, "yaw_change_deg": angle}


def _offsets(fx, fy, grid, envelope):
    """Rasterize the inflated sole using the four separating axes of two rectangles.

    fx, fy specify the candidate centre in metres from its grid cell's origin.
    A positive-area intersection requires support; edge-only contact has zero area.
    """
    a, b, c, s = envelope
    hx, hy = abs(c)*a + abs(s)*b, abs(s)*a + abs(c)*b
    cell_projection = grid/2 * (abs(c) + abs(s))
    for i in range(math.floor((fx-hx)/grid), math.ceil((fx+hx)/grid)):
        dx = (i+0.5)*grid - fx
        for j in range(math.floor((fy-hy)/grid), math.ceil((fy+hy)/grid)):
            dy = (j+0.5)*grid - fy
            if abs(dx*c + dy*s) < a + cell_projection and abs(-dx*s + dy*c) < b + cell_projection:
                yield i, j


SIDES = ("front", "back", "right", "left")


def _edge_limits(tread):
    edges = tread.get("edges", {})
    if not isinstance(edges, dict):
        raise ValueError("invalid recorded edge map")
    limits = []
    for side in SIDES:
        edge = edges.get(side)
        if edge is None:
            limits.append(None)
        elif not isinstance(edge, dict):
            raise ValueError(f"invalid {side} edge record")
        elif edge.get("status") == "unconfirmed" and edge.get("position_m") is None:
            limits.append(None)
        elif edge.get("status") == "observed_transition" and _finite(edge.get("position_m")):
            limits.append(edge["position_m"])
        else:
            raise ValueError(f"inconsistent {side} edge status or position")
    for lower, upper in (limits[:2], limits[2:]):
        if lower is not None and upper is not None and lower >= upper:
            raise ValueError("recorded edge interval must have positive extent")
    return limits


def assess_tread(tread, grid, foot, candidate_xy=None, reach=None):
    if not _finite(grid) or grid <= 0:
        raise ValueError("recorded grid spacing must be positive and finite")
    if candidate_xy is not None and (len(candidate_xy) != 2 or not all(_finite(v) for v in candidate_xy)):
        raise ValueError("candidate must be two finite coordinates in the recorded gravity frame")
    result = {"surface_id": tread.get("surface_id"), "status": "unknown", "reason": None,
              "candidate_center_m": None, "support": "unknown", "reach": {"status": "not_assessed"}}
    limits = _edge_limits(tread)
    unknown_sides = [side for side, pos in zip(SIDES, limits) if pos is None]
    result.update(unconfirmed_edges=unknown_sides, support_evidence_ring_cells=int(bool(unknown_sides)))
    if tread.get("z_m") is None:
        return dict(result, reason="unmeasured_height")
    if not _finite(tread["z_m"]):
        raise ValueError("invalid recorded tread height")
    supplied_cells = tread.get("observed_cells")
    if supplied_cells is None or supplied_cells == []:
        return dict(result, reason="no_observed_support_cells")
    if not isinstance(supplied_cells, list) or any(
            not isinstance(p, (list, tuple)) or len(p) != 2 or not all(type(i) is int for i in p)
            for p in supplied_cells):
        raise ValueError("invalid observed cell indices")
    cells = set(map(tuple, supplied_cells))
    # No transition was seen on an unknown side. It creates no outer physical
    # bound. A one-cell observed collar around the footprint keeps such
    # candidates strictly in the sampled interior, including near internal gaps.
    support = cells
    if unknown_sides:
        support = {(i, j) for i, j in cells if all((i+dx, j+dy) in cells
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1))}
    x0, x1, y0, y1 = [v if v is not None else missing for v, missing
                      in zip(limits, (-math.inf, math.inf, -math.inf, math.inf))]
    envelope = foot.envelope()
    a, b, c, s = envelope
    hx, hy = abs(c)*a + abs(s)*b, abs(s)*a + abs(c)*b
    if 2*hx > x1-x0 or 2*hy > y1-y0:
        return dict(result, status="unknown" if unknown_sides else "outside_measured_envelope",
                    reason="padded_sole_exceeds_measured_extent")
    if not support or 4*a*b > len(support)*grid*grid:
        return dict(result, reason="insufficient_observed_cell_area")
    xs, ys = zip(*support)
    if (2*hx > (max(xs)-min(xs)+1)*grid or 2*hy > (max(ys)-min(ys)+1)*grid):
        return dict(result, reason="insufficient_observed_cell_extent")

    if candidate_xy is not None:
        x, y = candidate_xy
        i, j = math.floor(x/grid), math.floor(y/grid)
        candidates = [(i, j, x, y)]
        fx, fy = x - i*grid, y - j*grid
    else:
        # Test near the measured centre first. Order is independent of input ordering.
        cx, cy = ((min(axis) + max(axis) + 1)*grid/2 for axis in (xs, ys))
        candidates = sorted(((i, j, (i+0.5)*grid, (j+0.5)*grid) for i, j in support),
                            key=lambda p: ((p[2]-cx)**2 + (p[3]-cy)**2, p[0], p[1]))
        fx = fy = grid/2

    offsets = None
    first_outside = None
    for i, j, x, y in candidates:
        if x-hx < x0 or x+hx > x1 or y-hy < y0 or y+hy > y1:
            if candidate_xy is not None:
                return dict(result, status="outside_measured_envelope", reason="candidate_crosses_measured_edge")
            continue
        if offsets is None:
            offsets = tuple(_offsets(fx, fy, grid, envelope))
        if any((i+dx, j+dy) not in support for dx, dy in offsets):
            continue
        checked = dict(result, candidate_center_m=[x, y, tread["z_m"]], support="covered_at_grid_resolution",
                       intersected_cell_count=len(offsets), status="support_observed")
        if reach is None:
            return checked
        checked["reach"] = reach.assess(x, y, tread["z_m"], foot)
        if checked["reach"]["status"] == "within_envelope":
            return dict(checked, status="support_and_reach_within_envelope")
        if first_outside is None:
            status = "unknown" if unknown_sides and candidate_xy is None else "outside_reach_envelope"
            first_outside = dict(checked, status=status,
                                 reason="no_support_candidate_checked_within_reach")
    if first_outside is not None:
        return first_outside
    return dict(result, reason="no_fully_observed_candidate_at_tested_centres")


def configure_parser(parser):
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--frame-number", type=int, help="default: first measured frame")
    parser.add_argument("--foot-length-m", type=float, required=True, help="measured enclosing sole rectangle length")
    parser.add_argument("--foot-width-m", type=float, required=True, help="measured enclosing sole rectangle width")
    parser.add_argument("--yaw-deg", type=float, required=True, help="sole heading from gravity-frame +x toward +y")
    parser.add_argument("--edge-margin-m", type=float, required=True, help="edge-location uncertainty plus desired clearance")
    parser.add_argument("--position-uncertainty-m", type=float, required=True, help="bound on relative horizontal placement error")
    parser.add_argument("--yaw-uncertainty-deg", type=float, required=True, help="bound on relative heading error")
    parser.add_argument("--candidate-xy", nargs=2, type=float, metavar=("X", "Y"), help="fixed sole centre in the measured frame (m)")
    parser.add_argument("--stance-pose", nargs=4, type=float, metavar=("X", "Y", "Z", "YAW_DEG"), help="measured stance sole centre and heading")
    for option in ("max-rise-m", "max-drop-m", "max-horizontal-reach-m", "max-yaw-change-deg", "height-uncertainty-m"):
        parser.add_argument("--" + option, type=float, help="operator-validated relative bound; required with --stance-pose")


def run(args):
    foot = Footprint(args.foot_length_m, args.foot_width_m, args.yaw_deg, args.edge_margin_m,
                     args.position_uncertainty_m, args.yaw_uncertainty_deg)
    reach = None
    reach_values = (args.stance_pose, args.max_rise_m, args.max_drop_m, args.max_horizontal_reach_m,
                    args.max_yaw_change_deg, args.height_uncertainty_m)
    if any(x is not None for x in reach_values):
        if any(x is None for x in reach_values):
            raise ValueError("reach assessment requires stance pose, rise/drop, horizontal reach, yaw and height uncertainty")
        reach = Reach(*reach_values)
    part = run_path(args.runs_dir, args.run) / "geometry"
    manifest = read_json(part / "manifest.json")
    if manifest.get("complete") is not True:
        raise ValueError("finish the geometry recording before assessing support")
    if (manifest.get("grid_origin_xy_m") != [0, 0] or not manifest.get("frame_id")
            or manifest.get("coordinate_axes") != {"x": "forward", "y": "left", "z": "up"}):
        raise ValueError("expected a recorded forward/left/up gravity frame and grid origin [0,0]")
    frame = next((f for f in read_jsonl(part / "stairs.jsonl") if args.frame_number is None
                  or f["frame_number"] == args.frame_number), None)
    if frame is None or frame.get("frame_id") != manifest["frame_id"]:
        raise ValueError("no matching measured frame in the recorded gravity frame")
    treads = [assess_tread(t, frame["grid_m"], foot, args.candidate_xy, reach) for t in frame["treads"]]
    flights = frame.get("stair_flights")
    if flights is not None and (not isinstance(flights, list) or any(
            not isinstance(f, dict) or not isinstance(f.get("surface_ids"), list)
            or not all(type(i) is int for i in f["surface_ids"]) for f in flights)):
        raise ValueError("invalid recorded stair flight membership")
    for t in treads:
        t["flight_indices"] = [i for i, f in enumerate(flights or []) if t["surface_id"] in f["surface_ids"]]
        if flights is None or t["surface_id"] is None:
            t["flight_membership"] = "unknown"
        else:
            t["flight_membership"] = "detected" if t["flight_indices"] else "not_in_detected_flight"
    return {"scope": "single_frame_geometry_only", "robot_climbability": "unknown", "run": args.run,
            "frame_number": frame["frame_number"], "frame_id": frame["frame_id"], "grid_m": frame["grid_m"],
            "source": manifest.get("source"), "footprint": asdict(foot), "reach_limits": asdict(reach) if reach else None,
            "candidate_search": "fixed_xy" if args.candidate_xy is not None else "observed_cell_centres",
            "requested_candidate_xy_m": args.candidate_xy, "treads": treads}
