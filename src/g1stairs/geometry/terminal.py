# Author: Codex (IIC)
"""Display a measured depth frame using the geometry values saved in stairs.jsonl."""


def _cm(metres):
    return "--" if metres is None else f"{metres * 100:.1f}"


def format_stairs(frame):
    """Return a Korean terminal report for one live or previously measured frame."""
    ground = "관측" if frame["ground_observed"] else "미관측"
    treads = frame["treads"]
    lines = [f"프레임 {frame['frame_number']} · 기준 바닥 {ground} · 디딤면 후보 {len(treads)}개"]
    if treads:
        lines.append("치수 단위 cm   (-- 미확인)")
        lines.append("면 ID  단높이  바닥 기준 높이  디딤면 깊이  좌우 폭  단높이 근거")
        evidence = {
            "estimated_from_ground": "앞쪽 바닥",
            "estimated_common_boundary": "인접한 두 면의 경계",
            "ambiguous_predecessor": "앞 단을 특정할 수 없음",
            "boundary_unconfirmed": "인접 경계 미확인",
        }
        for tread in treads:
            lines.append(
                f"{tread['surface_id']:>5}  {_cm(tread['riser_height_m']):>6}  "
                f"{_cm(tread['height_above_reference_ground_m']):>14}  {_cm(tread['tread_depth_m']):>11}  "
                f"{_cm(tread['width_m']):>7}  {evidence.get(tread['riser_status'], '미확인')}"
            )
    elif frame.get("valid_depth_sample_count") == 0:
        lines.append("유효한 깊이 픽셀이 없습니다.")

    # Recordings made before flight grouping have only per-surface estimates.
    if "stair_flights" in frame:
        if not frame["stair_flights"]:
            lines.append("연속 계단 구간 미확인")
        for flight in frame["stair_flights"]:
            direction = {"ascending": "오름", "descending": "내림"}[flight["direction"]]
            surfaces = " → ".join(map(str, flight["surface_ids"]))
            lines.append(f"{direction} 구간 · 면 {surfaces} · 단높이 중앙값 {_cm(flight['median_riser_height_m'])} cm")
    lines.append("G1 연속 등반 가능 여부 미확인")
    return "\n".join(lines)
