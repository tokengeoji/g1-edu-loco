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


def _adjacent(previous, current, options):
    end = previous["edges"]["back"]["position_m"]
    start = current["edges"]["front"]["position_m"]
    if end is None and start is None:
        return False
    a, b = previous["observed_bounds_m"], current["observed_bounds_m"]
    end = a["x_max"] if end is None else end
    start = b["x_min"] if start is None else start
    if abs(end - start) > options.grid_m:
        return False
    overlap = min(a["y_max"], b["y_max"]) - max(a["y_min"], b["y_min"])
    return overlap > options.grid_m * 2


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
        height_above_ground = None if ground_z_m is None else surface["z_m"] - ground_z_m
        vertical_change = None
        riser_status = "boundary_unconfirmed"
        if index and _adjacent(treads[index - 1], surface, options):
            vertical_change = surface["z_m"] - treads[index - 1]["z_m"]
            riser_status = "estimated_common_boundary"
        elif not index and _near_visible_ground(ground, surface, options):
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
    }
