"""Extract measured horizontal surfaces and report visible edge evidence."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MeasurementOptions:
    grid_m: float = 0.025
    height_tolerance_m: float = 0.018
    min_samples: int = 45
    max_tilt_deg: float = 12.0

    def __post_init__(self):
        if (
            not np.all(np.isfinite((self.grid_m, self.height_tolerance_m, self.max_tilt_deg)))
            or self.grid_m <= 0
            or self.height_tolerance_m <= 0
            or self.min_samples < 6
            or not 0 < self.max_tilt_deg < 45
        ):
            raise ValueError("invalid surface sampling parameters")


def _horizontal_pairs(delta, max_slope, options):
    horizontal_length = np.linalg.norm(delta[..., :2], axis=-1)
    # Missing depth is represented by NaN; comparisons should exclude those pairs.
    with np.errstate(invalid="ignore"):
        return (
            (horizontal_length > 1e-4)
            & (horizontal_length < options.grid_m * 3)
            & (np.abs(delta[..., 2]) <= max_slope * horizontal_length + options.height_tolerance_m / 5)
        )


def _horizontal_samples(points, options):
    max_slope = np.tan(np.deg2rad(options.max_tilt_deg))
    row_pairs = _horizontal_pairs(np.diff(points, axis=0), max_slope, options)
    column_pairs = _horizontal_pairs(np.diff(points, axis=1), max_slope, options)
    row_neighbors = np.zeros(points.shape[:2], dtype=bool)
    column_neighbors = np.zeros_like(row_neighbors)
    row_neighbors[:-1] |= row_pairs
    row_neighbors[1:] |= row_pairs
    column_neighbors[:, :-1] |= column_pairs
    column_neighbors[:, 1:] |= column_pairs
    return np.flatnonzero((row_neighbors & column_neighbors).ravel())


def _height_groups(points, sample_ids, options):
    tolerance = options.height_tolerance_m
    # The most populated height band is used as the seed. Median refinement
    # removes the dependence of the final plane height on fixed histogram edges.
    while len(sample_ids) >= options.min_samples:
        heights = points[sample_ids, 2]
        buckets = np.floor(heights / tolerance).astype(int)
        levels, counts = np.unique(buckets, return_counts=True)
        density = dict(zip(levels.tolist(), counts.tolist()))
        window_counts = [sum(density.get(int(k) + d, 0) for d in (-1, 0, 1)) for k in levels]
        seed = (levels[np.argmax(window_counts)] + 0.5) * tolerance
        neighbor = np.abs(heights - seed) <= 1.5 * tolerance
        center = np.median(heights[neighbor])
        matching = np.abs(heights - center) <= tolerance
        # Consume the seed band so outliers and overlapping thin bands cannot
        # keep the extraction loop on the same level.
        if not np.any(matching):
            matching = neighbor
        yield sample_ids[matching]
        sample_ids = sample_ids[~matching]


def _surface_components(points, sample_ids, options):
    height, width = points.shape[:2]
    flat = points.reshape(-1, 3)
    remaining = set(sample_ids.tolist())
    max_distance_sq = (options.grid_m * 3) ** 2
    while remaining:
        frontier = [remaining.pop()]
        component = []
        while frontier:
            index = frontier.pop()
            component.append(index)
            row, column = divmod(index, width)
            for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                if 0 <= row + dr < height and 0 <= column + dc < width:
                    neighbor = index + dr * width + dc
                    if neighbor not in remaining:
                        continue
                    delta = flat[index] - flat[neighbor]
                    if delta @ delta <= max_distance_sq:
                        remaining.remove(neighbor)
                        frontier.append(neighbor)
        if len(component) >= options.min_samples:
            ids = np.asarray(sorted(component))
            cells = np.floor(flat[ids, :2] / options.grid_m).astype(int)
            unique_cells = np.unique(cells, axis=0).tolist()
            if len(unique_cells) >= 5:
                yield ids, unique_cells


def _boundary_pairs(points, sample_ids):
    mask = np.zeros(points.shape[:2], dtype=bool)
    mask.flat[sample_ids] = True
    pairs = []
    for left, right, left_mask, right_mask in (
        (points[:, :-1], points[:, 1:], mask[:, :-1], mask[:, 1:]),
        (points[:-1], points[1:], mask[:-1], mask[1:]),
    ):
        inside_left = left_mask & ~right_mask
        inside_right = right_mask & ~left_mask
        pairs.extend(((left[inside_left], right[inside_left]), (right[inside_right], left[inside_right])))
    inside = np.concatenate([pair[0] for pair in pairs])
    outside = np.concatenate([pair[1] for pair in pairs])
    finite = np.all(np.isfinite(outside), axis=1)
    return inside[finite], outside[finite]


def _edge_evidence(inside, outside, bounds, z, camera_origin, axis, direction, options):
    other_axis = 1 - axis
    edge_bound = bounds[axis, 0 if direction < 0 else 1]
    difference = outside - inside
    distance_to_edge = np.abs(inside[:, axis] - edge_bound)
    with np.errstate(divide="ignore", invalid="ignore"):
        ray = outside - camera_origin
        fraction = (z - camera_origin[2]) / ray[:, 2]
        projected = camera_origin + fraction[:, None] * ray
        across = projected[:, :2] - inside[:, :2]
    along_edge = np.abs(across[:, other_axis])
    across_edge = across[:, axis] * direction
    directional = (across_edge > np.maximum(along_edge * 0.65, 1e-4)) & (across_edge < options.grid_m * 3)
    # If the other ray continues past this plane, its intersection is observed
    # free space. A close wall/step transition can also witness an edge.
    free_ray = (fraction > 0) & (fraction < 0.995)
    near_transition = (
        (np.abs(difference[:, other_axis]) < options.grid_m * 1.8)
        & (difference[:, axis] * direction > -options.grid_m * 0.25)
        & (difference[:, axis] * direction < options.grid_m * 2.5)
    )
    supported = (
        (distance_to_edge <= options.grid_m * 1.25)
        & (np.abs(difference[:, 2]) > options.height_tolerance_m / 2)
        & directional
        & (free_ray | near_transition)
    )
    support = inside[supported]
    cross_width = bounds[other_axis, 1] - bounds[other_axis, 0]
    if len(support) < 5 or np.ptp(support[:, other_axis]) < max(cross_width * 0.25, options.grid_m * 2):
        return {"status": "unconfirmed", "position_m": None, "witness_count": int(len(support))}
    across_boundary = np.where(free_ray, projected[:, axis], outside[:, axis])
    position = float(np.median((support[:, axis] + across_boundary[supported]) / 2))
    # An estimate on the inward side cannot bound all observed support.
    position = float(min(position, edge_bound) if direction < 0 else max(position, edge_bound))
    return {"status": "observed_transition", "position_m": position, "witness_count": int(len(support))}


def _surface(points, sample_ids, cells, camera_origin, options):
    samples = points.reshape(-1, 3)[sample_ids]
    z = float(np.median(samples[:, 2]))
    bounds = np.stack((np.min(samples[:, :2], axis=0), np.max(samples[:, :2], axis=0)), axis=1)
    inside, outside = _boundary_pairs(points, sample_ids)
    edges = {
        label: _edge_evidence(inside, outside, bounds, z, camera_origin, axis, direction, options)
        for label, axis, direction in (("front", 0, -1), ("back", 0, 1), ("right", 1, -1), ("left", 1, 1))
    }

    def confirmed_dimension(start, end):
        a, b = edges[start]["position_m"], edges[end]["position_m"]
        return b - a if a is not None and b is not None and b > a else None

    depth = confirmed_dimension("front", "back")
    width = confirmed_dimension("right", "left")
    return {
        "z_m": z,
        "height_mad_m": float(np.median(np.abs(samples[:, 2] - z))),
        "horizontal_sample_count": int(len(samples)),
        "observed_bounds_m": {
            "x_min": float(bounds[0, 0]),
            "x_max": float(bounds[0, 1]),
            "y_min": float(bounds[1, 0]),
            "y_max": float(bounds[1, 1]),
        },
        "observed_tread_depth_span_m": float(np.ptp(bounds[0])),
        "observed_width_span_m": float(np.ptp(bounds[1])),
        "tread_depth_m": depth,
        "width_m": width,
        "dimension_status": "edge_estimates" if depth is not None and width is not None else "partial_boundaries",
        "edges": edges,
        "observed_cells": cells,
    }


def _shared_boundary(previous, current, options):
    """Locate a witnessed edge between different levels with local lateral support."""
    if abs(current["z_m"] - previous["z_m"]) <= options.height_tolerance_m:
        return None
    end = previous["edges"]["back"]["position_m"]
    start = current["edges"]["front"]["position_m"]
    if end is None and start is None:
        return None
    a, b = previous["observed_bounds_m"], current["observed_bounds_m"]
    if b["x_min"] <= a["x_min"] or b["x_max"] <= a["x_max"]:
        return None
    previous_limit = a["x_max"] if end is None else end
    current_limit = b["x_min"] if start is None else start
    if abs(previous_limit - current_limit) > options.grid_m:
        return None
    if min(a["y_max"], b["y_max"]) - max(a["y_min"], b["y_min"]) <= options.grid_m * 2:
        return None
    positions = [v for v in (end, start) if v is not None]
    x_edge = sum(positions) / len(positions)
    edge_cell = int(np.floor(x_edge / options.grid_m))
    # A bounding box might span a hole or a missing corner. Require the two
    # measured patches to reach the same three neighboring lateral grid cells.
    strips = [{y for x, y in patch["observed_cells"] if abs(x - edge_cell) <= 1}
              for patch in (previous, current)]
    overlap = strips[0] & strips[1]
    if not any(y + 1 in overlap and y + 2 in overlap for y in overlap):
        return None
    source = "previous_back" if start is None else "next_front"
    if len(positions) == 2:
        source = "both"
    return {"from_surface_id": previous["surface_id"], "to_surface_id": current["surface_id"],
            "boundary_x_m": x_edge, "boundary_source": source,
            "signed_rise_m": current["z_m"] - previous["z_m"]}


def _stair_flights(incoming, outgoing):
    """Group unambiguous neighboring tread planes with monotonic heights.

    Pérez-Yus et al. (CVIU 154, 2017, sections 4.1–4.2) connect candidate
    planes and measure horizontal spacing between consecutive step edges.
    Here each link requires a witnessed boundary in the surveyed stair frame.
    """
    links = {i: edges[0] for i, edges in enumerate(outgoing)
             if len(edges) == 1 and len(incoming[edges[0]["to_surface_id"]]) == 1}
    entering = {edge["to_surface_id"]: edge for edge in links.values()}
    flights = []
    for i, first in links.items():
        sign = np.sign(first["signed_rise_m"])
        if i in entering and np.sign(entering[i]["signed_rise_m"]) == sign:
            continue
        chain = [first]
        edge = links.get(first["to_surface_id"])
        while edge is not None and np.sign(edge["signed_rise_m"]) == sign:
            chain.append(edge)
            edge = links.get(edge["to_surface_id"])
        if len(chain) < 2:
            continue
        rises = np.abs([item["signed_rise_m"] for item in chain])
        goings = np.diff([item["boundary_x_m"] for item in chain])
        if np.any(goings <= 0):
            continue
        rise, going = float(np.median(rises)), float(np.median(goings))
        flights.append({
            "surface_ids": [i] + [item["to_surface_id"] for item in chain],
            "direction": "ascending" if sign > 0 else "descending",
            "transitions": chain,
            "riser_sample_count": len(rises), "median_riser_height_m": rise,
            "riser_height_mad_m": float(np.median(np.abs(rises - rise))),
            "going_sample_count": len(goings), "median_going_m": going,
            "going_mad_m": float(np.median(np.abs(goings - going))),
        })
    return flights


def _near_visible_ground(ground, surface, options):
    edge = surface["edges"]["front"]["position_m"]
    if edge is None:
        return False
    bounds = surface["observed_bounds_m"]
    grid_m = options.grid_m
    low_y = bounds["y_min"] + (bounds["y_max"] - bounds["y_min"]) * 0.25
    high_y = bounds["y_max"] - (bounds["y_max"] - bounds["y_min"]) * 0.25
    return any(
        edge - 2.5 * grid_m <= (x + 0.5) * grid_m < edge
        and low_y <= (y + 0.5) * grid_m <= high_y
        for patch in ground
        for x, y in patch["observed_cells"]
    )


def measure_surfaces(points, camera_origin, ground_z_m, options):
    """Report observed surfaces. Extents are estimates when both sides have witnesses."""
    flat = points.reshape(-1, 3)
    sample_ids = _horizontal_samples(points, options)
    surfaces = [
        _surface(points, ids, cells, camera_origin, options)
        for group in _height_groups(flat, sample_ids, options)
        for ids, cells in _surface_components(points, group, options)
    ]
    ground = []
    treads = []
    for surface in surfaces:
        if ground_z_m is not None and abs(surface["z_m"] - ground_z_m) <= options.height_tolerance_m:
            ground.append(surface)
        else:
            treads.append(surface)
    treads.sort(key=lambda item: (item["observed_bounds_m"]["x_min"], item["z_m"]))
    for index, surface in enumerate(treads):
        surface["surface_id"] = index
    incoming = [[] for _ in treads]
    outgoing = [[] for _ in treads]
    for i, previous in enumerate(treads):
        for j in range(i + 1, len(treads)):
            edge = _shared_boundary(previous, treads[j], options)
            if edge is not None:
                incoming[j].append(edge)
                outgoing[i].append(edge)
    for index, surface in enumerate(treads):
        height_above_ground = None if ground_z_m is None else surface["z_m"] - ground_z_m
        vertical_change = None
        riser_status = "boundary_unconfirmed"
        if len(incoming[index]) == 1:
            vertical_change = incoming[index][0]["signed_rise_m"]
            riser_status = "estimated_common_boundary"
        elif incoming[index]:
            riser_status = "ambiguous_predecessor"
        elif _near_visible_ground(ground, surface, options):
            vertical_change = height_above_ground
            riser_status = "estimated_from_ground"
        surface["height_above_reference_ground_m"] = height_above_ground
        surface["signed_height_change_m"] = vertical_change
        surface["riser_height_m"] = None if vertical_change is None else abs(vertical_change)
        surface["riser_status"] = riser_status
    return {
        "status": "surfaces_observed" if surfaces else "no_horizontal_surfaces",
        "valid_depth_sample_count": int(np.count_nonzero(np.isfinite(flat[:, 2]))),
        "horizontal_sample_count": int(len(sample_ids)),
        "ground_reference_m": ground_z_m,
        "ground_observed": bool(ground),
        "grid_m": options.grid_m,
        "observed_ground_patches": ground,
        "treads": treads,
        "stair_flights": _stair_flights(incoming, outgoing),
    }
