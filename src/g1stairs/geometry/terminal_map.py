# Author: Codex (IIC)
"""Render measured horizontal grid cells in a bounded terminal plan view."""


def format_stair_map(frame: dict) -> str:
    """Draw only observed cells. In each tile the second character marks partial coverage."""
    ground, mixed = -1, -2
    title = "관측 수평면 평면도   ↑ 진행 방향 (+x)   ← 왼쪽 (+y)"
    cells = {}
    for surfaces, is_ground in ((frame["observed_ground_patches"], True), (frame["treads"], False)):
        for surface in surfaces:
            surface_id = ground if is_ground else surface["surface_id"]
            for x, y in surface["observed_cells"]:
                key = (x, y)
                cells[key] = surface_id if cells.get(key, surface_id) == surface_id else mixed
    if not cells:
        return title + "\n표시할 관측 셀이 없습니다."

    x_min = min(x for x, _ in cells)
    y_min = min(y for _, y in cells)
    nx = max(x for x, _ in cells) - x_min + 1
    ny = max(y for _, y in cells) - y_min + 1
    # Keep equal metric scales on both axes and never allocate the full bounding rectangle.
    stride = max((nx + 15) // 16, (ny + 23) // 24)
    tiles = {}
    for (x, y), surface_id in cells.items():
        tile = ((x - x_min) // stride, (y - y_min) // stride)
        label, count = tiles.get(tile, (surface_id, 0))
        tiles[tile] = (label if label == surface_id else mixed, count + 1)

    symbols = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    tile_cm = frame["grid_m"] * stride * 100
    lines = [title, f"표시 한 칸 = {tile_cm:g} × {tile_cm:g} cm"]
    for row in range((nx - 1) // stride, -1, -1):
        line = []
        for column in range((ny - 1) // stride, -1, -1):
            if (row, column) not in tiles:
                line.append("· ")
                continue
            label, count = tiles[row, column]
            if label == ground:
                symbol = "="
            elif label == mixed:
                symbol = "*"
            else:
                symbol = symbols[label] if label < len(symbols) else "+"
            line.append(symbol + (":" if count < stride * stride else " "))
        lines.append("".join(line).rstrip())
    lines.append("= 바닥   · 수평면 관측 없음   * 여러 면   : 칸 일부만 관측")
    lines.append("0–9는 면 ID, A–Z는 ID 10–35, +는 ID 36 이상")
    return "\n".join(lines)
