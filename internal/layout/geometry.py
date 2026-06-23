"""Геометрия редактора: проверка пересечений со стенами и границами этажа."""

import math

CANVAS_WIDTH = 2240
CANVAS_HEIGHT = 1344
WALL_HALF_WIDTH = 8
FLOOR_INSET = WALL_HALF_WIDTH
WALL_PENETRATION = 0
PARENT_INSET = 8


def _wall_on_floor(wall, floor):
    return int(wall.get('floor', 1)) == int(floor)


def _wall_overlap_depth_vertical(wall_x, y1, y2, rx, ry, rw, rh):
    wy1, wy2 = min(y1, y2), max(y1, y2)
    if ry + rh <= wy1 or ry >= wy2:
        return 0
    wl, wr = wall_x - WALL_HALF_WIDTH, wall_x + WALL_HALF_WIDTH
    return max(0, min(rx + rw, wr) - max(rx, wl))


def _wall_overlap_depth_horizontal(wall_y, x1, x2, rx, ry, rw, rh):
    wx1, wx2 = min(x1, x2), max(x1, x2)
    if rx + rw <= wx1 or rx >= wx2:
        return 0
    wt, wb = wall_y - WALL_HALF_WIDTH, wall_y + WALL_HALF_WIDTH
    return max(0, min(ry + rh, wb) - max(ry, wt))


def _rect_overlaps_vertical_wall(wall_x, y1, y2, rx, ry, rw, rh):
    return _wall_overlap_depth_vertical(wall_x, y1, y2, rx, ry, rw, rh) > WALL_PENETRATION


def _rect_overlaps_horizontal_wall(wall_y, x1, x2, rx, ry, rw, rh):
    return _wall_overlap_depth_horizontal(wall_y, x1, x2, rx, ry, rw, rh) > WALL_PENETRATION


def rect_overlaps_walls(x, y, width, height, walls, floor=1):
    """Проверить, пересекается ли прямоугольник места со стенами."""
    rx, ry, rw, rh = float(x), float(y), float(width), float(height)
    for wall in walls:
        if not _wall_on_floor(wall, floor):
            continue
        x1, y1, x2, y2 = wall['x1'], wall['y1'], wall['x2'], wall['y2']
        if abs(x1 - x2) < 3:
            wx = (x1 + x2) / 2
            if _rect_overlaps_vertical_wall(wx, y1, y2, rx, ry, rw, rh):
                return True
        elif abs(y1 - y2) < 3:
            wy = (y1 + y2) / 2
            if _rect_overlaps_horizontal_wall(wy, x1, x2, rx, ry, rw, rh):
                return True
    return False


def clamp_rect_to_floor(x, y, width, height):
    """Удержать прямоугольник внутри границ этажа (с отступом от несущих стен)."""
    w, h = float(width), float(height)
    max_x = CANVAS_WIDTH - FLOOR_INSET - w
    max_y = CANVAS_HEIGHT - FLOOR_INSET - h
    nx = max(FLOOR_INSET, min(float(x), max_x))
    ny = max(FLOOR_INSET, min(float(y), max_y))
    return nx, ny


def adjust_rect_from_walls(x, y, width, height, walls, floor=1, max_passes=24):
    """Сдвинуть прямоугольник от стен и границ этажа."""
    rx, ry = float(x), float(y)
    w, h = float(width), float(height)
    rx, ry = clamp_rect_to_floor(rx, ry, w, h)

    for _ in range(max_passes):
        if not rect_overlaps_walls(rx, ry, w, h, walls, floor):
            break
        moved = False
        for wall in walls:
            if not _wall_on_floor(wall, floor):
                continue
            x1, y1, x2, y2 = wall['x1'], wall['y1'], wall['x2'], wall['y2']
            if abs(x1 - x2) < 3:
                wx = (x1 + x2) / 2
                if not _rect_overlaps_vertical_wall(wx, y1, y2, rx, ry, w, h):
                    continue
                wl, wr = wx - WALL_HALF_WIDTH, wx + WALL_HALF_WIDTH
                if rx + w / 2 < wx:
                    rx = wl - w
                else:
                    rx = wr
                moved = True
            elif abs(y1 - y2) < 3:
                wy = (y1 + y2) / 2
                if not _rect_overlaps_horizontal_wall(wy, x1, x2, rx, ry, w, h):
                    continue
                wt, wb = wy - WALL_HALF_WIDTH, wy + WALL_HALF_WIDTH
                if ry + h / 2 < wy:
                    ry = wt - h
                else:
                    ry = wb
                moved = True
        rx, ry = clamp_rect_to_floor(rx, ry, w, h)
        if not moved:
            break

    return round(rx), round(ry)


def clamp_rect_in_parent(x, y, width, height, parent_x, parent_y, parent_w, parent_h, inset=PARENT_INSET):
    """Удержать прямоугольник внутри родительской локации (отступ от «стен» комнаты)."""
    w, h = float(width), float(height)
    min_x = float(parent_x) + inset
    min_y = float(parent_y) + inset
    max_x = float(parent_x) + float(parent_w) - inset - w
    max_y = float(parent_y) + float(parent_h) - inset - h
    if max_x < min_x or max_y < min_y:
        return None, None
    nx = max(min_x, min(float(x), max_x))
    ny = max(min_y, min(float(y), max_y))
    return round(nx), round(ny)


def effective_rect_for_rotation(x, y, width, height, rotation=0):
    """Визуальный axis-aligned bounding box после поворота вокруг центра.

    В layout хранятся исходные x/y/width/height и rotation (градусы).
    SVG поворачивает rect вокруг центра; для проверок у стен и пересечений
    нужен фактический bounding-box (при 90°/270° ширина и высота меняются местами).
    """
    rot = int(float(rotation or 0)) % 360
    w, h = float(width), float(height)
    cx = float(x) + w / 2
    cy = float(y) + h / 2
    if rot % 180 == 90:
        eff_w, eff_h = h, w
    else:
        eff_w, eff_h = w, h
    return cx - eff_w / 2, cy - eff_h / 2, eff_w, eff_h


def apply_effective_rect_delta(x, y, eff_x, eff_y, width, height, rotation=0):
    """Сдвинуть сохранённые x/y на ту же дельту, что и у effective bbox."""
    orig_x, orig_y, _, _ = effective_rect_for_rotation(x, y, width, height, rotation)
    return float(x) + (float(eff_x) - orig_x), float(y) + (float(eff_y) - orig_y)


def clamp_rect_in_parent_rotated(
    x, y, width, height, rotation,
    parent_x, parent_y, parent_w, parent_h, inset=PARENT_INSET,
):
    """Удержать повёрнутый объект внутри родительской локации."""
    eff_x, eff_y, eff_w, eff_h = effective_rect_for_rotation(
        x, y, width, height, rotation,
    )
    clamped_x, clamped_y = clamp_rect_in_parent(
        eff_x, eff_y, eff_w, eff_h, parent_x, parent_y, parent_w, parent_h, inset,
    )
    if clamped_x is None:
        return None, None
    nx, ny = apply_effective_rect_delta(x, y, clamped_x, clamped_y, width, height, rotation)
    return round(nx), round(ny)


def adjust_rect_from_walls_rotated(x, y, width, height, rotation, walls, floor=1, max_passes=24):
    """Сдвинуть объект от стен с учётом поворота."""
    eff_x, eff_y, eff_w, eff_h = effective_rect_for_rotation(
        x, y, width, height, rotation,
    )
    adj_x, adj_y = adjust_rect_from_walls(eff_x, eff_y, eff_w, eff_h, walls, floor, max_passes)
    nx, ny = apply_effective_rect_delta(x, y, adj_x, adj_y, width, height, rotation)
    return round(nx), round(ny)


def rect_overlaps_walls_rotated(x, y, width, height, rotation, walls, floor=1):
    """Проверить пересечение повёрнутого прямоугольника со стенами."""
    eff_x, eff_y, eff_w, eff_h = effective_rect_for_rotation(
        x, y, width, height, rotation,
    )
    return rect_overlaps_walls(eff_x, eff_y, eff_w, eff_h, walls, floor)


def rects_overlap(ax, ay, aw, ah, bx, by, bw, bh, gap=0):
    """Прямоугольники пересекаются (gap — минимальный зазор)."""
    return (
        ax < bx + bw - gap
        and ax + aw > bx + gap
        and ay < by + bh - gap
        and ay + ah > by + gap
    )


def rects_meaningful_overlap(ax, ay, aw, ah, bx, by, bw, bh, min_depth=4, edge_touch_max=16):
    """Пересечение с «глубиной» с обеих сторон — не просто общая грань соседних комнат.

    Тонкая полоска по одной оси (≤ edge_touch_max) — соседство по стене, не конфликт.
    """
    ix = max(float(ax), float(bx))
    iy = max(float(ay), float(by))
    iw = min(float(ax) + float(aw), float(bx) + float(bw)) - ix
    ih = min(float(ay) + float(ah), float(by) + float(bh)) - iy
    if iw <= 0 or ih <= 0:
        return False
    if min(iw, ih) <= float(edge_touch_max):
        return False
    return iw >= min_depth and ih >= min_depth


def _wall_segment_orientation(wall):
    dx = abs(int(wall['x1']) - int(wall['x2']))
    dy = abs(int(wall['y1']) - int(wall['y2']))
    if dx <= 4 < dy:
        return 'v'
    if dy <= 4 < dx:
        return 'h'
    return None


def repair_wall_gaps(walls, floor=1, tol=16):
    """Подтянуть концы стен к перпендикулярным — убрать зазоры в углах."""
    floor_walls = [w for w in walls if int(w.get('floor', 1)) == int(floor)]
    changed = False

    for w in floor_walls:
        ori = _wall_segment_orientation(w)
        if not ori:
            continue
        for end in (1, 2):
            ex = float(w[f'x{end}'])
            ey = float(w[f'y{end}'])
            for w2 in floor_walls:
                if w2.get('id') == w.get('id'):
                    continue
                ori2 = _wall_segment_orientation(w2)
                if not ori2 or ori == ori2:
                    continue
                if ori == 'v' and ori2 == 'h':
                    hy = (int(w2['y1']) + int(w2['y2'])) / 2
                    hx1, hx2 = min(w2['x1'], w2['x2']), max(w2['x1'], w2['x2'])
                    vx = (int(w['x1']) + int(w['x2'])) / 2
                    if abs(ey - hy) <= tol and hx1 - tol <= vx <= hx2 + tol:
                        ny = int(round(hy))
                        if int(w[f'y{end}']) != ny:
                            w[f'y{end}'] = ny
                            changed = True
                elif ori == 'h' and ori2 == 'v':
                    vx = (int(w2['x1']) + int(w2['x2'])) / 2
                    vy1, vy2 = min(w2['y1'], w2['y2']), max(w2['y1'], w2['y2'])
                    hy = (int(w['y1']) + int(w['y2'])) / 2
                    if abs(ex - vx) <= tol and vy1 - tol <= hy <= vy2 + tol:
                        nx = int(round(vx))
                        if int(w[f'x{end}']) != nx:
                            w[f'x{end}'] = nx
                            changed = True
    return changed


def rect_contains(outer_x, outer_y, outer_w, outer_h, inner_x, inner_y, inner_w, inner_h, padding=0):
    """Внутренний прямоугольник целиком внутри внешнего."""
    pad = float(padding)
    return (
        float(inner_x) >= float(outer_x) + pad
        and float(inner_y) >= float(outer_y) + pad
        and float(inner_x) + float(inner_w) <= float(outer_x) + float(outer_w) - pad
        and float(inner_y) + float(inner_h) <= float(outer_y) + float(outer_h) - pad
    )


def location_overlap_conflicts(layout_places, code, x, y, width, height, floor):
    """Частичные пересечения локаций (space/room). Вложенность допустима."""
    conflicts = []
    absorbed = []
    ax, ay, aw, ah = float(x), float(y), float(width), float(height)
    for item in layout_places or []:
        if item.get('code') == code:
            continue
        if int(item.get('floor', 1)) != int(floor):
            continue
        if item.get('kind') not in ('space', 'room') or item.get('container_code'):
            continue
        if item.get('enclosed') is False:
            continue
        ix, iy = item.get('x'), item.get('y')
        iw, ih = item.get('width'), item.get('height')
        if ix is None or iy is None or not iw or not ih:
            continue
        if not rects_meaningful_overlap(ax, ay, aw, ah, float(ix), float(iy), float(iw), float(ih)):
            continue
        if rect_contains(ax, ay, aw, ah, ix, iy, iw, ih):
            absorbed.append(item)
            continue
        if rect_contains(float(ix), float(iy), float(iw), float(ih), ax, ay, aw, ah):
            continue
        conflicts.append(item)
    return conflicts, absorbed


def project_layout_positions(layout_places, position_updates):
    """Скопировать layout с подстановкой новых координат (code -> {x, y})."""
    projected = []
    for item in layout_places or []:
        row = dict(item)
        code = row.get('code')
        if code and code in position_updates:
            upd = position_updates[code]
            row['x'] = upd['x']
            row['y'] = upd['y']
        projected.append(row)
    return projected


def find_place_overlap(
    layout_places, code, x, y, width, height, floor, kind,
    container_code=None, rotation=0,
):
    """Проверка пересечения с другими объектами на карте."""
    if kind in ('space', 'room'):
        conflicts, _ = location_overlap_conflicts(
            layout_places, code, x, y, width, height, floor,
        )
        if conflicts:
            other = conflicts[0]
            return (
                f'Частичное пересечение с «{other.get("name", other.get("code", "?"))}». '
                'Уменьшите помещение или измените границы.'
            )
        return None

    eff_x, eff_y, eff_w, eff_h = effective_rect_for_rotation(
        x, y, width, height, rotation,
    )
    for item in layout_places or []:
        if item.get('code') == code:
            continue
        if int(item.get('floor', 1)) != int(floor):
            continue
        item_kind = item.get('kind', 'desk')
        if kind == 'desk':
            if item_kind != 'desk':
                continue
        else:
            continue
        ix, iy = item.get('x'), item.get('y')
        iw, ih = item.get('width'), item.get('height')
        if ix is None or iy is None or not iw or not ih:
            continue
        irot = int(float(item.get('rotation') or 0))
        iex, iey, iew, ieh = effective_rect_for_rotation(ix, iy, iw, ih, irot)
        if rects_overlap(eff_x, eff_y, eff_w, eff_h, iex, iey, iew, ieh, gap=0):
            return f'Пересечение с «{item.get("code", "?")}»'
    return None


def validate_place_rect(x, y, width, height, walls, floor=1, allow_wall_contact=False):
    """Вернуть скорректированные координаты или ошибку, если убрать со стены нельзя.

    allow_wall_contact=True — для локаций по контуру стен (комната ограничена стенами).
    """
    if allow_wall_contact:
        w, h = float(width), float(height)
        max_x = CANVAS_WIDTH - w
        max_y = CANVAS_HEIGHT - h
        ax = max(0, min(float(x), max_x))
        ay = max(0, min(float(y), max_y))
        return round(ax), round(ay), None
    ax, ay = adjust_rect_from_walls(x, y, width, height, walls, floor)
    if rect_overlaps_walls(ax, ay, width, height, walls, floor):
        return None, None, 'Объект нельзя разместить на стене. Отодвиньте от границ.'
    return ax, ay, None


def _point_on_wall_segment(px, py, wall, tol=14):
    """Точка лежит на отрезке стены (в пределах tol px)."""
    x1, y1, x2, y2 = wall['x1'], wall['y1'], wall['x2'], wall['y2']
    dx, dy = x2 - x1, y2 - y1
    len2 = dx * dx + dy * dy
    if len2 < 1:
        return None
    t = ((px - x1) * dx + (py - y1) * dy) / len2
    if t < 0.02 or t > 0.98:
        return None
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    if math.hypot(px - proj_x, py - proj_y) > tol:
        return None
    return t


def _door_junction_positions(wall, all_walls):
    """Доли вдоль стены, где к ней примыкают другие стены."""
    junctions = []
    for ow in all_walls or []:
        if ow.get('id') == wall.get('id'):
            continue
        for px, py in ((ow['x1'], ow['y1']), (ow['x2'], ow['y2'])):
            t = _point_on_wall_segment(px, py, wall)
            if t is not None:
                junctions.append(t)
    return junctions


def door_position_range(wall, door_width, all_walls=None):
    """Допустимый диапазон position (0..1) для центра двери вдоль стены."""
    dx = wall['x2'] - wall['x1']
    dy = wall['y2'] - wall['y1']
    length = math.hypot(dx, dy)
    if length < door_width + 16:
        return 0.5, 0.5
    hw = float(door_width) / 2
    margin = 12
    min_pos = (hw + margin) / length
    max_pos = 1.0 - (hw + margin) / length
    buf = (hw + margin) / length
    for t in _door_junction_positions(wall, all_walls):
        min_pos = max(min_pos, t + buf)
        max_pos = min(max_pos, t - buf)
    if min_pos > max_pos:
        return 0.5, 0.5
    return min_pos, max_pos


def _door_endpoints(wall, position, door_width):
    dx = wall['x2'] - wall['x1']
    dy = wall['y2'] - wall['y1']
    length = math.hypot(dx, dy)
    if length < 1:
        return (0, 0), (0, 0)
    ux, uy = dx / length, dy / length
    mx = wall['x1'] + dx * position
    my = wall['y1'] + dy * position
    hw = door_width / 2
    return (mx - ux * hw, my - uy * hw), (mx + ux * hw, my + uy * hw)


def _door_within_floor(wall, position, door_width):
    (x1, y1), (x2, y2) = _door_endpoints(wall, position, door_width)
    for x, y in ((x1, y1), (x2, y2)):
        if x < FLOOR_INSET or x > CANVAS_WIDTH - FLOOR_INSET:
            return False
        if y < FLOOR_INSET or y > CANVAS_HEIGHT - FLOOR_INSET:
            return False
    return True


def clamp_door_position(wall, position, door_width, all_walls=None):
    """Ограничить дверь: не за край стены, не на стыке стен, не за границу этажа."""
    min_p, max_p = door_position_range(wall, door_width, all_walls)
    pos = max(min_p, min(max_p, float(position)))
    if _door_within_floor(wall, pos, door_width):
        return round(pos, 4)
    for delta in (0.02, 0.04, 0.06, 0.08, -0.02, -0.04, -0.06, -0.08):
        trial = max(min_p, min(max_p, pos + delta))
        if _door_within_floor(wall, trial, door_width):
            return round(trial, 4)
    return round(pos, 4)


OPEN_ZONE_PAD = 8
ZONE_WALL_SNAP_DIST = 28


def desks_overlap_each_other(desks, gap=0):
    """Пересекаются ли столы в списке (с учётом поворота)."""
    items = list(desks or [])
    for i, a in enumerate(items):
        ax, ay = float(a['x']), float(a['y'])
        aw = float(a.get('width', 100))
        ah = float(a.get('height', 100))
        arot = int(float(a.get('rotation') or 0))
        aex, aey, aew, aeh = effective_rect_for_rotation(ax, ay, aw, ah, arot)
        for b in items[i + 1:]:
            bx, by = float(b['x']), float(b['y'])
            bw = float(b.get('width', 100))
            bh = float(b.get('height', 100))
            brot = int(float(b.get('rotation') or 0))
            bex, bey, bew, beh = effective_rect_for_rotation(bx, by, bw, bh, brot)
            if rects_overlap(aex, aey, aew, aeh, bex, bey, bew, beh, gap=gap):
                return True
    return False


def _desk_spans_wall(desk, wall):
    """Стол перекрывает стену по вертикали/горизонтали (для привязки зоны)."""
    dx, dy = float(desk['x']), float(desk['y'])
    dw = float(desk.get('width', 100))
    dh = float(desk.get('height', 100))
    x1, y1, x2, y2 = wall['x1'], wall['y1'], wall['x2'], wall['y2']
    if abs(x1 - x2) < 3:
        wy1, wy2 = min(y1, y2), max(y1, y2)
        return not (dy + dh <= wy1 or dy >= wy2)
    if abs(y1 - y2) < 3:
        wx1, wx2 = min(x1, x2), max(x1, x2)
        return not (dx + dw <= wx1 or dx >= wx2)
    return False


def fit_open_zone_bounds(desks, walls, floor=1, pad=OPEN_ZONE_PAD):
    """Плотная зона вокруг столов: малый отступ, край у стены — вплотную (+ PARENT_INSET)."""
    if not desks:
        return 0, 0, 120, 120

    min_x = min(float(d['x']) for d in desks) - pad
    min_y = min(float(d['y']) for d in desks) - pad
    max_x = max(float(d['x']) + float(d.get('width', 100)) for d in desks) + pad
    max_y = max(float(d['y']) + float(d.get('height', 100)) for d in desks) + pad

    for wall in walls or []:
        if not _wall_on_floor(wall, floor):
            continue
        x1, y1, x2, y2 = wall['x1'], wall['y1'], wall['x2'], wall['y2']
        relevant = [d for d in desks if _desk_spans_wall(d, wall)]
        if not relevant:
            continue
        if abs(x1 - x2) < 3:
            wx = (x1 + x2) / 2
            wl = wx - WALL_HALF_WIDTH
            wr = wx + WALL_HALF_WIDTH
            desk_min_x = min(float(d['x']) for d in relevant)
            desk_max_x = max(float(d['x']) + float(d.get('width', 100)) for d in relevant)
            if desk_min_x >= wr - ZONE_WALL_SNAP_DIST:
                min_x = max(min_x, wr + PARENT_INSET)
            if desk_max_x <= wl + ZONE_WALL_SNAP_DIST:
                max_x = min(max_x, wl - PARENT_INSET)
        elif abs(y1 - y2) < 3:
            wy = (y1 + y2) / 2
            wt = wy - WALL_HALF_WIDTH
            wb = wy + WALL_HALF_WIDTH
            desk_min_y = min(float(d['y']) for d in relevant)
            desk_max_y = max(float(d['y']) + float(d.get('height', 100)) for d in relevant)
            if desk_min_y >= wb - ZONE_WALL_SNAP_DIST:
                min_y = max(min_y, wb + PARENT_INSET)
            if desk_max_y <= wt + ZONE_WALL_SNAP_DIST:
                max_y = min(max_y, wt - PARENT_INSET)

    for d in desks:
        dx, dy = float(d['x']), float(d['y'])
        dw = float(d.get('width', 100))
        dh = float(d.get('height', 100))
        min_x = min(min_x, dx - PARENT_INSET)
        min_y = min(min_y, dy - PARENT_INSET)
        max_x = max(max_x, dx + dw + PARENT_INSET)
        max_y = max(max_y, dy + dh + PARENT_INSET)

    zone_w = max(60, max_x - min_x)
    zone_h = max(60, max_y - min_y)
    return int(min_x), int(min_y), int(zone_w), int(zone_h)


def zone_overlaps_other_desks(layout_places, zone_x, zone_y, zone_w, zone_h, floor, exclude_codes):
    """Зона пересекает чужие столы (не из выделения)."""
    exclude = set(exclude_codes or [])
    for item in layout_places or []:
        code = item.get('code')
        if code in exclude or item.get('kind') != 'desk':
            continue
        if int(item.get('floor', 1)) != int(floor):
            continue
        ix, iy = item.get('x'), item.get('y')
        iw, ih = item.get('width'), item.get('height')
        if ix is None or iy is None or not iw or not ih:
            continue
        if rects_overlap(
            float(zone_x), float(zone_y), float(zone_w), float(zone_h),
            float(ix), float(iy), float(iw), float(ih), gap=2,
        ):
            return item
    return None


def nudge_desks_from_walls(desks, walls, floor=1):
    """Сдвинуть столы от стен; вернуть {code: {x, y}} для изменённых."""
    moved = {}
    for desk in desks:
        code = desk.get('code')
        w = float(desk.get('width', 100))
        h = float(desk.get('height', 100))
        nx, ny = adjust_rect_from_walls(float(desk['x']), float(desk['y']), w, h, walls, floor)
        if int(nx) != int(desk['x']) or int(ny) != int(desk['y']):
            moved[code] = {'x': nx, 'y': ny}
            desk['x'] = nx
            desk['y'] = ny
    return moved
