"""Детект комнат по стенам и расчёт вариантов размещения."""
from __future__ import annotations

import math
import random
from collections import Counter

TOL = 8
MIN_ROOM_SIZE = 80
SCALE = 100
CANVAS_W = 2240
CANVAS_H = 1344
MAX_FLOOR_ROOM_FRAC = 0.72


def _walls_on_floor(walls, floor):
    return [w for w in walls if int(w.get('floor', 1)) == int(floor)]


def _verticals(walls):
    out = []
    for w in walls:
        if abs(w['x1'] - w['x2']) < 3:
            out.append({
                'x': round((w['x1'] + w['x2']) / 2),
                'y1': min(w['y1'], w['y2']),
                'y2': max(w['y1'], w['y2']),
            })
    return out


def _horizontals(walls):
    out = []
    for w in walls:
        if abs(w['y1'] - w['y2']) < 3:
            out.append({
                'y': round((w['y1'] + w['y2']) / 2),
                'x1': min(w['x1'], w['x2']),
                'x2': max(w['x1'], w['x2']),
            })
    return out


def find_room_at_point(x, y, walls, floor=1, min_size=MIN_ROOM_SIZE):
    """Комната по стенам в точке (как в редакторе)."""
    fw = _walls_on_floor(walls, floor)
    verts = _verticals(fw)
    hors = _horizontals(fw)

    lefts = [v for v in verts if v['x'] < x and v['y1'] <= y <= v['y2']]
    rights = [v for v in verts if v['x'] > x and v['y1'] <= y <= v['y2']]
    tops = [h for h in hors if h['y'] < y and h['x1'] <= x <= h['x2']]
    bottoms = [h for h in hors if h['y'] > y and h['x1'] <= x <= h['x2']]
    if not lefts or not rights or not tops or not bottoms:
        return None

    left = max(lefts, key=lambda v: v['x'])
    right = min(rights, key=lambda v: v['x'])
    top = max(tops, key=lambda h: h['y'])
    bottom = min(bottoms, key=lambda h: h['y'])
    rw, rh = right['x'] - left['x'], bottom['y'] - top['y']
    if rw < min_size or rh < min_size:
        return None

    if not (top['x1'] <= left['x'] + TOL and top['x2'] >= right['x'] - TOL):
        return None
    if not (bottom['x1'] <= left['x'] + TOL and bottom['x2'] >= right['x'] - TOL):
        return None
    if not (left['y1'] <= top['y'] + TOL and left['y2'] >= bottom['y'] - TOL):
        return None
    if not (right['y1'] <= top['y'] + TOL and right['y2'] >= bottom['y'] - TOL):
        return None

    return {
        'x': left['x'],
        'y': top['y'],
        'width': rw,
        'height': rh,
        'floor': int(floor),
    }


def is_whole_floor_room(room):
    """Исключить псевдо-комнату «весь этаж» по периметру наружных стен."""
    w, h = int(room.get('width', 0)), int(room.get('height', 0))
    if w < MIN_ROOM_SIZE or h < MIN_ROOM_SIZE:
        return True
    area = w * h
    canvas_area = CANVAS_W * CANVAS_H
    if area >= canvas_area * MAX_FLOOR_ROOM_FRAC:
        return True
    if w >= CANVAS_W - 40 and h >= CANVAS_H - 40:
        return True
    return False


def detect_all_wall_rooms(walls, floor=1, min_size=MIN_ROOM_SIZE, apply_ignored=True):
    """Все прямоугольные комнаты, образованные пересечением стен."""
    fw = _walls_on_floor(walls, floor)
    verts = _verticals(fw)
    hors = _horizontals(fw)
    rooms = []
    seen = set()

    for left in verts:
        for right in verts:
            if right['x'] - left['x'] < min_size:
                continue
            for top in hors:
                for bottom in hors:
                    if bottom['y'] - top['y'] < min_size:
                        continue
                    x, y = left['x'], top['y']
                    w, h = right['x'] - left['x'], bottom['y'] - top['y']
                    if not (top['x1'] <= left['x'] + TOL and top['x2'] >= right['x'] - TOL):
                        continue
                    if not (bottom['x1'] <= left['x'] + TOL and bottom['x2'] >= right['x'] - TOL):
                        continue
                    if not (left['y1'] <= top['y'] + TOL and left['y2'] >= bottom['y'] - TOL):
                        continue
                    if not (right['y1'] <= top['y'] + TOL and right['y2'] >= bottom['y'] - TOL):
                        continue
                    key = (x, y, w, h)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidate = {
                        'room_key': f'wall-{x}-{y}-{w}-{h}',
                        'x': x, 'y': y, 'width': w, 'height': h,
                        'floor': int(floor),
                    }
                    if is_whole_floor_room(candidate):
                        continue
                    rooms.append(candidate)
    rooms = filter_nested_wall_rooms(rooms)
    if apply_ignored:
        return filter_ignored_draft_rooms(rooms, floor)
    return rooms


def _find_room_match(x, y, width, height, rooms, tol=20):
    for room in rooms or []:
        if _geom_match(room, {'x': x, 'y': y, 'width': width, 'height': height}, tol=tol):
            return room
    return None


def resolve_wall_room_for_geometry(geom, floor=None):
    """Найти ячейку стен, соответствующую геометрии места из layout."""
    if not geom:
        return None
    from internal.models.layout import load_walls

    fl = int(floor if floor is not None else geom.get('floor', 1))
    rooms = detect_all_wall_rooms(load_walls(), fl, apply_ignored=False)
    for room in rooms:
        if match_place_to_room(geom, room):
            return room
    return _find_room_match(
        geom.get('x'), geom.get('y'), geom.get('width'), geom.get('height'),
        rooms, tol=40,
    )


def _wall_on_room_edge(wall, room, tol=TOL):
    """Стена лежит на границе прямоугольной комнаты."""
    rx, ry = float(room['x']), float(room['y'])
    rw, rh = float(room['width']), float(room['height'])
    x1, y1, x2, y2 = float(wall['x1']), float(wall['y1']), float(wall['x2']), float(wall['y2'])

    if abs(x1 - x2) < 3:
        wx = round((x1 + x2) / 2)
        on_vertical = abs(wx - rx) <= tol or abs(wx - (rx + rw)) <= tol
        if not on_vertical:
            return False
        y_min, y_max = min(y1, y2), max(y1, y2)
        return y_max >= ry + tol and y_min <= ry + rh - tol

    if abs(y1 - y2) < 3:
        wy = round((y1 + y2) / 2)
        on_horizontal = abs(wy - ry) <= tol or abs(wy - (ry + rh)) <= tol
        if not on_horizontal:
            return False
        x_min, x_max = min(x1, x2), max(x1, x2)
        return x_max >= rx + tol and x_min <= rx + rw - tol

    return False


def filter_ignored_draft_rooms(rooms, floor=1):
    """Скрыть черновики, которые пользователь убрал вручную."""
    from internal.models.layout import load_ignored_drafts, prune_stale_ignored_drafts

    prune_stale_ignored_drafts(floor)
    ignored = load_ignored_drafts(floor)
    if not ignored:
        return rooms
    return [room for room in rooms if not _room_matches_ignored(room, ignored)]


def _room_matches_ignored(room, ignored_list, tol=36):
    for ig in ignored_list or []:
        if int(ig.get('floor', 1)) != int(room.get('floor', 1)):
            continue
        if room.get('room_key') and ig.get('room_key') and room['room_key'] == ig['room_key']:
            return True
        if _geom_match(room, ig, tol=tol):
            return True
    return False


def dismiss_draft_room(x, y, width, height, floor=1, room_key=None, code=None):
    """Убрать черновик/зону: стены ячейки, запись ignored, убрать place из layout."""
    from internal.models.layout import (
        add_ignored_draft,
        delete_wall,
        load_walls,
        remove_layout_places_in_box,
        _draft_room_key,
    )

    floor = int(floor or 1)
    walls = load_walls()
    all_rooms = detect_all_wall_rooms(walls, floor)
    target = _find_room_match(x, y, width, height, all_rooms, tol=40)
    room_box = dict(target) if target else {
        'x': int(x), 'y': int(y), 'width': int(width), 'height': int(height), 'floor': floor,
    }
    if room_key:
        room_box['room_key'] = room_key
    else:
        room_box['room_key'] = _draft_room_key(room_box, floor)

    others = [
        r for r in all_rooms
        if not _geom_match(r, room_box, tol=16)
        and r.get('room_key') != room_box.get('room_key')
    ]

    removed = []
    for w in _walls_on_floor(walls, floor):
        if w.get('protected'):
            continue
        if not _wall_on_room_edge(w, room_box):
            continue
        if any(_wall_on_room_edge(w, other) for other in others):
            continue
        delete_wall(w['id'])
        removed.append(w['id'])

    add_ignored_draft(room_box, floor)
    layout_removed = remove_layout_places_in_box(
        room_box['x'], room_box['y'], room_box['width'], room_box['height'], floor,
    )
    if code and code not in layout_removed:
        from internal.layout.repository import LayoutRepository
        if LayoutRepository.remove_place(code):
            layout_removed.append(code)

    return {
        'walls_removed': len(removed),
        'wall_ids': removed,
        'layout_removed': layout_removed,
        'room_key': room_box['room_key'],
    }


def _room_strictly_contains(container, inner, tol=TOL):
    """Прямоугольник container строго больше и полностью накрывает inner."""
    if container is inner:
        return False
    ck = container.get('room_key') or (container['x'], container['y'], container['width'], container['height'])
    ik = inner.get('room_key') or (inner['x'], inner['y'], inner['width'], inner['height'])
    if ck == ik:
        return False

    cx, cy = float(container['x']), float(container['y'])
    cw, ch = float(container['width']), float(container['height'])
    ix, iy = float(inner['x']), float(inner['y'])
    iw, ih = float(inner['width']), float(inner['height'])

    fits = (
        ix >= cx - tol and iy >= cy - tol
        and ix + iw <= cx + cw + tol
        and iy + ih <= cy + ch + tol
    )
    if not fits:
        return False

    area_c = cw * ch
    area_i = iw * ih
    if area_i >= area_c - tol * tol:
        return False
    return area_c > area_i + tol


def filter_nested_wall_rooms(rooms):
    """Убрать комнаты-контейнеры: зона не может содержать другую зону."""
    if not rooms:
        return rooms
    return [
        room for room in rooms
        if not any(
            _room_strictly_contains(room, other)
            for other in rooms
            if other is not room
        )
    ]


def _geom_match(a, b, tol=20):
    return (
        abs(a['x'] - b['x']) <= tol
        and abs(a['y'] - b['y']) <= tol
        and abs(a['width'] - b['width']) <= tol * 2
        and abs(a['height'] - b['height']) <= tol * 2
    )


def _place_center(place):
    return (
        place['x'] + place['width'] / 2,
        place['y'] + place['height'] / 2,
    )


def match_place_to_room(place, room, tol=25):
    if not place or not room:
        return False
    if int(place.get('floor', 1)) != int(room.get('floor', 1)):
        return False
    if place.get('kind') not in ('space', 'room'):
        return False
    if _geom_match(place, room, tol):
        return True
    cx, cy = _place_center(place)
    inside = (
        room['x'] - tol <= cx <= room['x'] + room['width'] + tol
        and room['y'] - tol <= cy <= room['y'] + room['height'] + tol
    )
    if not inside:
        return False
    return (
        abs(place['width'] - room['width']) <= tol * 2
        and abs(place['height'] - room['height']) <= tol * 2
    )


def link_rooms_with_places(rooms, places):
    """Привязать wall-room к Place-space."""
    linked = []
    used_codes = set()
    for room in rooms:
        item = dict(room)
        item['registered'] = False
        item['place'] = None
        for p in places:
            if p.get('kind') not in ('space', 'room'):
                continue
            if p.get('code') in used_codes:
                continue
            if match_place_to_room(p, room):
                item['registered'] = True
                item['place'] = {
                    'id': p.get('id'),
                    'code': p.get('code'),
                    'name': p.get('name'),
                    'zone_type_id': p.get('zone_type_id'),
                    'zone_type': p.get('zone_type'),
                    'category': p.get('category'),
                    'allows_desks': p.get('allows_desks', True),
                    'is_meeting_room': p.get('is_meeting_room', False),
                }
                used_codes.add(p.get('code'))
                break
        linked.append(item)
    return linked


WALL_PACK_MARGIN_PX = 0  # вплотную к границе комнаты (стены = контур)
WALL_CLEARANCE_PX = WALL_PACK_MARGIN_PX
DESK_GAP_PX = 50         # 0,5 м между столами
DOOR_CLEARANCE_PX = 100
TARGET_FILL = 0.62
CLEARANCE_PX = WALL_CLEARANCE_PX
WALL_MARGIN_PX = WALL_CLEARANCE_PX


def _filter_desk_categories(desk_categories):
    out = []
    for cat in desk_categories:
        name = (cat.get('name') or '').lower()
        if 'закрытая зона' in name or 'зона рабоч' in name:
            continue
        tw = int(cat.get('width_px') or cat.get('width_m', 1) * SCALE)
        th = int(cat.get('height_px') or cat.get('height_m', 0.75) * SCALE)
        if tw < 1 or th < 1:
            continue
        out.append({**cat, 'tw': tw, 'th': th, 'area': tw * th})
    out.sort(key=lambda c: -c['area'])
    return out


def _effective_size(tw, th, rotation=0):
    if int(rotation or 0) % 180 == 90:
        return th, tw
    return tw, th


def _stored_from_effective(eff_x, eff_y, tw, th, rotation=0):
    """Координаты layout из позиции bounding-box (с учётом поворота)."""
    eff_w, eff_h = _effective_size(tw, th, rotation)
    cx = eff_x + eff_w / 2
    cy = eff_y + eff_h / 2
    return round(cx - tw / 2), round(cy - th / 2)


def _effective_rect(sx, sy, tw, th, rotation=0):
    eff_w, eff_h = _effective_size(tw, th, rotation)
    cx = sx + tw / 2
    cy = sy + th / 2
    return cx - eff_w / 2, cy - eff_h / 2, eff_w, eff_h


def _rects_overlap_gap(ax, ay, aw, ah, bx, by, bw, bh, gap):
    return not (
        ax + aw + gap <= bx or bx + bw + gap <= ax
        or ay + ah + gap <= by or by + bh + gap <= ay
    )


def _fits_at(eff_x, eff_y, eff_w, eff_h, margin, inner_w, inner_h, placed, gap):
    right = margin + inner_w
    bottom = margin + inner_h
    if eff_x < margin - 0.5 or eff_y < margin - 0.5:
        return False
    if eff_x + eff_w > right + 0.5 or eff_y + eff_h > bottom + 0.5:
        return False
    for p in placed:
        pex, pey, pw, ph = _effective_rect(p['x'], p['y'], p['width'], p['height'], p.get('rotation', 0))
        if _rects_overlap_gap(eff_x, eff_y, eff_w, eff_h, pex, pey, pw, ph, gap):
            return False
    return True


def pack_desks_fill(room_w, room_h, tw, th, category_id=None, gap=DESK_GAP_PX, margin=WALL_CLEARANCE_PX):
    """Максимум столов одного типа — жадное заполнение."""
    cat = {'tw': tw, 'th': th, 'id': category_id}
    return pack_room_greedy_random(
        room_w, room_h, [cat], gap=gap, margin=margin, seed=0,
    )


def _desk_item_at(cat, rotation, eff_x, eff_y):
    tw, th = cat['tw'], cat['th']
    sx, sy = _stored_from_effective(eff_x, eff_y, tw, th, rotation)
    return {
        'x': sx, 'y': sy,
        'width': tw, 'height': th,
        'rotation': int(rotation) % 360,
        'category_id': cat.get('id'),
    }


def _candidate_values(start, end, step):
    if end < start:
        return []
    values = {round(start), round(end)}
    mid = (start + end) / 2
    values.add(round(mid))
    values.add(round((start + mid) / 2))
    values.add(round((mid + end) / 2))
    pos = start
    guard = 0
    while pos <= end + 0.5 and guard < 80:
        values.add(round(pos))
        pos += max(18, step)
        guard += 1
    return sorted(v for v in values if start - 0.5 <= v <= end + 0.5)


def _candidate_spots(room_w, room_h, cat, placed, gap, margin, rotation, strategy, rng):
    """Ограниченный пул позиций: углы, стены, центр и немного random."""
    inner_w = room_w - margin * 2
    inner_h = room_h - margin * 2
    if inner_w < 1 or inner_h < 1:
        return []
    tw, th = cat['tw'], cat['th']
    eff_w, eff_h = _effective_size(tw, th, rotation)
    if eff_w > inner_w or eff_h > inner_h:
        return []

    x_min, y_min = margin, margin
    x_max = margin + inner_w - eff_w
    y_max = margin + inner_h - eff_h
    step_x = eff_w + gap
    step_y = eff_h + gap
    xs = _candidate_values(x_min, x_max, step_x)
    ys = _candidate_values(y_min, y_max, step_y)
    spots = set()

    corners = [
        (x_min, y_min), (x_max, y_min), (x_min, y_max), (x_max, y_max),
    ]
    for spot in corners:
        spots.add((round(spot[0]), round(spot[1])))

    if strategy in ('corner_first', 'wall_ring', 'max_capacity', 'mixed_compact', 'sparse_comfort'):
        for x in xs:
            spots.add((x, round(y_min)))
            spots.add((x, round(y_max)))
        for y in ys:
            spots.add((round(x_min), y))
            spots.add((round(x_max), y))

    if strategy in ('center_island', 'mixed_compact', 'max_capacity', 'sparse_comfort'):
        cx = (x_min + x_max) / 2
        cy = (y_min + y_max) / 2
        for dx in (0, -(eff_w + gap), eff_w + gap, -(eff_w + gap) / 2, (eff_w + gap) / 2):
            for dy in (0, -(eff_h + gap), eff_h + gap, -(eff_h + gap) / 2, (eff_h + gap) / 2):
                spots.add((round(cx + dx), round(cy + dy)))

    if strategy == 'max_capacity':
        for x in xs:
            for y in ys:
                spots.add((x, y))

    random_count = 18 if strategy in ('mixed_compact', 'sparse_comfort') else 10
    for _ in range(random_count):
        spots.add((round(rng.uniform(x_min, x_max)), round(rng.uniform(y_min, y_max))))

    valid = []
    for x, y in spots:
        x = max(round(x_min), min(round(x), round(x_max)))
        y = max(round(y_min), min(round(y), round(y_max)))
        if _fits_at(x, y, eff_w, eff_h, margin, inner_w, inner_h, placed, gap):
            valid.append((x, y))
    return valid


def _estimate_free_area(room_w, room_h, placed, margin):
    """Грубая оценка оставшейся площади внутри комнаты."""
    inner_w = max(0, room_w - margin * 2)
    inner_h = max(0, room_h - margin * 2)
    used = 0
    for p in placed:
        ex, ey, ew, eh = _effective_rect(
            p['x'], p['y'], p['width'], p['height'], p.get('rotation', 0),
        )
        used += ew * eh
    return max(0, inner_w * inner_h - used)


def _layout_valid(room_w, room_h, placed, gap, margin):
    """Все столы внутри комнаты и без пересечений."""
    inner_w = room_w - margin * 2
    inner_h = room_h - margin * 2
    for p in placed:
        ex, ey, ew, eh = _effective_rect(
            p['x'], p['y'], p['width'], p['height'], p.get('rotation', 0),
        )
        if not _fits_at(ex, ey, ew, eh, margin, inner_w, inner_h, [], gap):
            return False
    for i, a in enumerate(placed):
        aex, aey, aw, ah = _effective_rect(
            a['x'], a['y'], a['width'], a['height'], a.get('rotation', 0),
        )
        for b in placed[i + 1:]:
            bex, bey, bw, bh = _effective_rect(
                b['x'], b['y'], b['width'], b['height'], b.get('rotation', 0),
            )
            if _rects_overlap_gap(aex, aey, aw, ah, bex, bey, bw, bh, gap):
                return False
    return True


def _wall_proximity_score(x, y, eff_w, eff_h, margin, inner_w, inner_h):
    """Бонус за близость к стенам (вплотную к границе комнаты)."""
    score = 0
    if x <= margin + 3:
        score += 2
    if y <= margin + 3:
        score += 2
    if x + eff_w >= margin + inner_w - 3:
        score += 2
    if y + eff_h >= margin + inner_h - 3:
        score += 2
    return score


def _corner_score(x, y, eff_w, eff_h, margin, inner_w, inner_h):
    corners = [
        (margin, margin),
        (margin + inner_w - eff_w, margin),
        (margin, margin + inner_h - eff_h),
        (margin + inner_w - eff_w, margin + inner_h - eff_h),
    ]
    dist = min(abs(x - cx) + abs(y - cy) for cx, cy in corners)
    return max(0, 8 - dist / 55)


def _center_score(x, y, eff_w, eff_h, margin, inner_w, inner_h):
    cx = margin + inner_w / 2
    cy = margin + inner_h / 2
    px = x + eff_w / 2
    py = y + eff_h / 2
    return max(0, 8 - (abs(px - cx) + abs(py - cy)) / 70)


def _strategy_score(strategy, x, y, eff_w, eff_h, margin, inner_w, inner_h,
                    cat, last_cat_id, rng):
    wall = _wall_proximity_score(x, y, eff_w, eff_h, margin, inner_w, inner_h)
    corner = _corner_score(x, y, eff_w, eff_h, margin, inner_w, inner_h)
    center = _center_score(x, y, eff_w, eff_h, margin, inner_w, inner_h)
    mix = 3 if last_cat_id and cat.get('id') != last_cat_id else 0
    jitter = rng.random() * 0.75
    if strategy == 'corner_first':
        return corner * 2.8 + wall + mix + jitter
    if strategy == 'wall_ring':
        return wall * 2.4 + corner * 0.8 + mix + jitter
    if strategy == 'center_island':
        return center * 2.6 + mix + jitter
    if strategy == 'mixed_compact':
        return mix * 2.0 + wall + center * 0.6 + jitter
    if strategy == 'sparse_comfort':
        return wall + center + mix + jitter
    return wall + corner * 0.5 + center * 0.5 + mix + jitter


def _strategy_categories(cats, strategy, placed_count):
    if strategy == 'mixed_compact':
        # Цикл по размерам: крупный → средний → малый, чтобы не получить стену одинаковых столов.
        return cats[placed_count % len(cats):] + cats[:placed_count % len(cats)]
    if strategy == 'sparse_comfort':
        return sorted(cats, key=lambda c: (-int(c.get('capacity', 1)), c['area']))
    return cats


def pack_room_greedy_random(room_w, room_h, desk_categories, gap=DESK_GAP_PX,
                            margin=WALL_CLEARANCE_PX, seed=0, strategy='max_capacity'):
    """Быстрое жадное заполнение по стратегии, без полного перебора всей сетки."""
    rng = random.Random(int(seed))
    cats = _filter_desk_categories(desk_categories)
    if not cats:
        return []

    work_cats = list(cats)
    if strategy == 'mixed_compact':
        rng.shuffle(work_cats)

    inner_w = room_w - margin * 2
    inner_h = room_h - margin * 2
    if inner_w < 1 or inner_h < 1:
        return []

    placed = []
    min_area = min(c['area'] for c in work_cats)
    last_cat_id = None
    target_limit = 999
    if strategy == 'sparse_comfort':
        target_limit = max(1, int((inner_w * inner_h) / (min_area * 2.2)))

    for _ in range(18):
        if len(placed) >= target_limit:
            break
        free_area = _estimate_free_area(room_w, room_h, placed, margin)
        if free_area < min_area * 0.45:
            break

        options = []
        for cat in _strategy_categories(work_cats, strategy, len(placed)):
            if cat['area'] > free_area * 1.08:
                continue
            for rotation in (0, 90):
                eff_w, eff_h = _effective_size(cat['tw'], cat['th'], rotation)
                if eff_w > inner_w or eff_h > inner_h:
                    continue
                spots = _candidate_spots(
                    room_w, room_h, cat, placed, gap, margin, rotation, strategy, rng,
                )
                if not spots:
                    continue
                for x, y in spots:
                    score = _strategy_score(
                        strategy, x, y, eff_w, eff_h, margin, inner_w, inner_h,
                        cat, last_cat_id, rng,
                    )
                    options.append((cat['area'], score, cat, rotation, x, y))

        if not options:
            break

        if strategy in ('mixed_compact', 'sparse_comfort'):
            options.sort(key=lambda o: (o[1], o[0]), reverse=True)
            tier = options[:min(10, len(options))]
        else:
            max_area = max(o[0] for o in options)
            tier = [o for o in options if o[0] >= max_area * 0.88]
            tier.sort(key=lambda o: (o[1], rng.random()), reverse=True)
        pick_n = min(len(tier), max(1, min(6, len(tier))))
        _, _, cat, rotation, x, y = rng.choice(tier[:pick_n])
        placed.append(_desk_item_at(cat, rotation, x, y))
        last_cat_id = cat.get('id')

    if not _layout_valid(room_w, room_h, placed, gap, margin):
        return []
    return placed


def pack_room_varied(room_w, room_h, desk_categories, gap=DESK_GAP_PX, margin=WALL_CLEARANCE_PX,
                     mode='scatter', seed=0):
    """Алиас стратегического заполнения (mode влияет на стратегию и seed)."""
    mode_seed = {
        'max_capacity': 0, 'balanced': 17, 'corner_first': 41,
        'mirror': 73, 'scatter': 101, 'wall_ring': 149,
        'center_island': 211, 'mixed_compact': 307, 'sparse_comfort': 401,
    }.get(mode, 0)
    strategy = mode if mode in {
        'max_capacity', 'corner_first', 'wall_ring', 'center_island',
        'mixed_compact', 'sparse_comfort',
    } else 'mixed_compact'
    return pack_room_greedy_random(
        room_w, room_h, desk_categories, gap, margin, seed=seed + mode_seed,
        strategy=strategy,
    )


def pack_room_mixed(room_w, room_h, desk_categories, gap=DESK_GAP_PX, margin=WALL_CLEARANCE_PX,
                    mode='scatter', seed=0):
    return pack_room_varied(room_w, room_h, desk_categories, gap, margin, mode, seed)


def pack_room_greedy(room_w, room_h, desk_categories, gap=DESK_GAP_PX, margin=WALL_CLEARANCE_PX):
    return pack_room_varied(room_w, room_h, desk_categories, gap, margin, 'max_capacity', 0)


def pack_desks_random(room, tw, th, category_id=None, doors=None, walls=None,
                      gap=DESK_GAP_PX, target_fill=TARGET_FILL, clearance=WALL_CLEARANCE_PX):
    """Алиас — заполнение рядами (doors/walls пока не используются)."""
    return pack_desks_fill(room['width'], room['height'], tw, th, category_id, gap, clearance)


def pack_desks_greedy(room, tw, th, category_id=None, gap=DESK_GAP_PX,
                      wall_margin=WALL_CLEARANCE_PX, door_margin=DOOR_CLEARANCE_PX,
                      doors=None, walls=None):
    return pack_desks_random(room, tw, th, category_id, doors, walls, gap, clearance=wall_margin)


def _variant_from_positions(room, positions, title, description, extra=None):
    if not positions:
        return None
    xs = [p['x'] for p in positions]
    ys = [p['y'] for p in positions]
    x2 = [p['x'] + p['width'] for p in positions]
    y2 = [p['y'] + p['height'] for p in positions]
    fp_w = max(x2) - min(xs)
    fp_h = max(y2) - min(ys)
    cap = sum(int(p.get('capacity', 1)) for p in positions)
    # capacity per position from category not stored — computed in desk_grid_variants

    v = {
        'variant_type': 'desks',
        'title': title,
        'description': description,
        'count': len(positions),
        'cols': 0,
        'rows': 0,
        'gap': DESK_GAP_PX,
        'margin': WALL_CLEARANCE_PX,
        'door_margin': DOOR_CLEARANCE_PX,
        'positions': positions,
        'footprint_w_px': fp_w,
        'footprint_h_px': fp_h,
        'footprint_w_m': round(fp_w / SCALE, 2),
        'footprint_h_m': round(fp_h / SCALE, 2),
        'capacity_total': cap,
    }
    if extra:
        v.update(extra)
    return v


def _layout_signature(placed, grid=22):
    return tuple(sorted(
        (p['category_id'], round(p['x'] / grid), round(p['y'] / grid), p.get('rotation', 0))
        for p in placed
    ))


def _layout_distance(a, b):
    aset = set(_layout_signature(a, grid=18))
    bset = set(_layout_signature(b, grid=18))
    if not aset and not bset:
        return 0
    return 1 - (len(aset & bset) / max(len(aset | bset), 1))


def _mix_description(placed, cats):
    names = {c['id']: c.get('name', 'Стол') for c in cats}
    caps = {c['id']: int(c.get('capacity', 1)) for c in cats}
    parts = []
    for cid, cnt in Counter(p['category_id'] for p in placed).most_common():
        nm = names.get(cid, 'Стол')
        parts.append(f'{nm} ×{cnt}')
    total_cap = sum(caps.get(p['category_id'], 1) for p in placed)
    return ' · '.join(parts), total_cap


def _count_mix_types(placed):
    return len({p['category_id'] for p in placed})


def _variant_quality(placed, room_w, room_h, margin):
    if not placed:
        return 0
    inner_w = max(1, room_w - margin * 2)
    inner_h = max(1, room_h - margin * 2)
    wall_score = 0
    corner_score = 0
    for p in placed:
        ex, ey, ew, eh = _effective_rect(
            p['x'], p['y'], p['width'], p['height'], p.get('rotation', 0),
        )
        wall_score += _wall_proximity_score(ex, ey, ew, eh, margin, inner_w, inner_h)
        corner_score += _corner_score(ex, ey, ew, eh, margin, inner_w, inner_h)
    return wall_score + corner_score + _count_mix_types(placed) * 4


def desk_grid_variants(room_w, room_h, desk_categories, margin=40, gap=30,
                       room=None, doors=None, walls=None):
    """Быстрые разные варианты: углы, стены, центр, плотный и смешанный сценарии."""
    abs_room = room if room else {
        'x': 0, 'y': 0, 'width': room_w, 'height': room_h, 'floor': 1,
    }
    cats = _filter_desk_categories(desk_categories)
    if not cats:
        return []

    w, h = abs_room['width'], abs_room['height']
    variants = []
    placed_variants = []
    seen = set()
    cap_map = {c['id']: int(c.get('capacity', 1)) for c in cats}
    base_seed = int(w * 997 + h * 13 + len(cats) * 31)
    strategy_runs = [
        ('corner_first', 0, 45),
        ('wall_ring', 0, 50),
        ('center_island', 12, 45),
        ('mixed_compact', 8, 45),
        ('max_capacity', 8, 40),
        ('sparse_comfort', 18, 60),
        ('corner_first', 8, 55),
        ('mixed_compact', 0, 50),
        ('center_island', 0, 55),
        ('max_capacity', 0, 45),
    ]

    for attempt, (strategy, wall_margin, desk_gap) in enumerate(strategy_runs):
        seed = base_seed + attempt * 1009
        trial = pack_room_greedy_random(
            w, h, cats, desk_gap, wall_margin, seed, strategy=strategy,
        )
        if not trial:
            continue
        sig = _layout_signature(trial, grid=12)
        if sig in seen:
            continue
        if any(_layout_distance(trial, other) < 0.35 for other in placed_variants):
            continue
        seen.add(sig)
        placed_variants.append([dict(p) for p in trial])

        mix_desc, total_cap = _mix_description(trial, cats)
        for p in trial:
            p['capacity'] = cap_map.get(p['category_id'], 1)

        n = len(variants) + 1
        variants.append(_variant_from_positions(
            abs_room, trial,
            title=f'Вариант {n} · {len(trial)} столов',
            description=f'{total_cap} мест · {mix_desc}',
            extra={
                'mixed': _count_mix_types(trial) >= 2,
                'strategy': strategy,
                'gap': desk_gap,
                'margin': wall_margin,
                'category_id': trial[0].get('category_id'),
                'capacity_total': total_cap,
                'quality_score': _variant_quality(trial, w, h, wall_margin),
                'mix_breakdown': [
                    {'category_id': cid, 'count': cnt}
                    for cid, cnt in Counter(p['category_id'] for p in trial).most_common()
                ],
            },
        ))

    variants.sort(key=lambda v: (
        -v.get('capacity_total', 0),
        -v.get('quality_score', 0),
        -v.get('count', 0),
    ))
    for i, v in enumerate(variants[:8], 1):
        v['title'] = f'Вариант {i} · {v.get("count", 0)} столов'
    return variants[:8]


def meeting_fit_variants(room_w, room_h, room_categories):
    """Какие переговорные помещаются в комнату."""
    variants = []
    room_w_m = room_w / SCALE
    room_h_m = room_h / SCALE

    for cat in room_categories:
        cw = float(cat.get('width_m', 1))
        ch = float(cat.get('height_m', 0.75))
        cap = int(cat.get('capacity', 1))
        name = (cat.get('name') or '').lower()
        # Только реальные переговорные, не столы/зоны
        if cap < 2 or max(cw, ch) < 1.8:
            continue
        if 'стол' in name or 'зона рабоч' in name:
            continue
        # 1м отступ под проход/дверной проём (от выступа стены)
        DOOR_CLEARANCE_M = 1.0
        effective_w = room_w_m - DOOR_CLEARANCE_M
        effective_h = room_h_m - DOOR_CLEARANCE_M
        fits = (effective_w >= cw and room_h_m >= ch) or (room_w_m >= cw and effective_h >= ch)
        hourly = None
        for t in cat.get('tariffs') or []:
            if t.get('tariff_type') == 'hourly' and t.get('active', True):
                hourly = t.get('price')
        variants.append({
            'variant_type': 'meeting',
            'category_id': cat.get('id'),
            'title': cat.get('name'),
            'description': (
                f'Помещается · {cw}×{ch} м · {cap} мест'
                if fits else f'Не помещается (нужно {cw}×{ch} м)'
            ),
            'fits': fits,
            'capacity': cat.get('capacity', 1),
            'price_per_hour': hourly,
            'width_m': cw,
            'height_m': ch,
            'footprint_w_m': cw,
            'footprint_h_m': ch,
        })
    variants.sort(key=lambda v: (not v['fits'], -v.get('capacity', 0)))
    return variants


def meeting_actual_variant(place, category, room_w, room_h, scale=SCALE):
    """Вариант для уже созданной переговорной — по фактическим размерам и категории места."""
    room_w_m = round(room_w / scale, 2)
    room_h_m = round(room_h / scale, 2)
    cap = int(getattr(category, 'capacity', None) or category.get('capacity', 1))
    cat_id = getattr(category, 'id', None) or category.get('id')
    name = (getattr(place, 'name', None) or place.get('name') or
            getattr(category, 'name', None) or category.get('name') or 'Переговорная')
    hourly = None
    if isinstance(category, dict):
        tariffs = category.get('tariffs') or []
    else:
        tariffs = getattr(category, 'tariffs', None) or []
    for t in tariffs:
        tt = t.tariff_type if hasattr(t, 'tariff_type') else t.get('tariff_type')
        active = t.active if hasattr(t, 'active') else t.get('active', True)
        if tt == 'hourly' and active:
            hourly = t.price if hasattr(t, 'price') else t.get('price')
            break
    return {
        'variant_type': 'meeting',
        'is_current': True,
        'category_id': cat_id,
        'title': name,
        'description': f'{room_w_m}×{room_h_m} м · {cap} мест · текущее помещение',
        'fits': True,
        'capacity': cap,
        'price_per_hour': hourly,
        'width_m': room_w_m,
        'height_m': room_h_m,
        'footprint_w_m': room_w_m,
        'footprint_h_m': room_h_m,
    }


def compute_desk_positions(room, cols, rows, tw, th, margin=40, gap=30,
                           align='center', rotation=0, door_margin=DOOR_CLEARANCE_PX):
    return pack_desks_fill(
        room['width'], room['height'], tw, th,
        gap=gap or DESK_GAP_PX, margin=margin or WALL_CLEARANCE_PX,
    )
