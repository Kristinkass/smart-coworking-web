"""Детект комнат по стенам и расчёт вариантов размещения."""
from __future__ import annotations

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


def desk_grid_variants(room_w, room_h, desk_categories, margin=40, gap=30):
    """Варианты сетки столов для desk_zone."""
    variants = []
    seen = set()
    usable_w = max(0, room_w - margin * 2)
    usable_h = max(0, room_h - margin * 2)

    for cat in desk_categories:
        name = (cat.get('name') or '').lower()
        if 'закрытая зона' in name or 'зона рабоч' in name:
            continue
        tw = int(cat.get('width_px') or cat.get('width_m', 1) * SCALE)
        th = int(cat.get('height_px') or cat.get('height_m', 0.75) * SCALE)
        cap = int(cat.get('capacity', 1))
        cols = int((usable_w + gap) // (tw + gap))
        rows = int((usable_h + gap) // (th + gap))
        count = cols * rows
        if count < 1:
            continue
        key = f"{cat.get('id')}:{count}"
        if key in seen:
            continue
        seen.add(key)
        fp_w = cols * tw + max(0, cols - 1) * gap
        fp_h = rows * th + max(0, rows - 1) * gap
        fp_w_m = round(fp_w / SCALE, 2)
        fp_h_m = round(fp_h / SCALE, 2)
        variants.append({
            'variant_type': 'desks',
            'category_id': cat.get('id'),
            'title': f"{cat.get('name')} · {count} шт.",
            'description': (
                f'{cols}×{rows} · {count * cap} рабочих мест · '
                f'занимает {fp_w_m}×{fp_h_m} м'
            ),
            'cols': cols, 'rows': rows, 'count': count,
            'margin': margin, 'gap': gap,
            'template_width': tw, 'template_height': th,
            'footprint_w_px': fp_w, 'footprint_h_px': fp_h,
            'footprint_w_m': fp_w_m, 'footprint_h_m': fp_h_m,
            'capacity_total': count * cap,
        })
    variants.sort(key=lambda v: v['capacity_total'], reverse=True)
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


def compute_desk_positions(room, cols, rows, tw, th, margin=40, gap=30):
    """Координаты столов внутри комнаты."""
    positions = []
    for r in range(rows):
        for c in range(cols):
            x = room['x'] + margin + c * (tw + gap)
            y = room['y'] + margin + r * (th + gap)
            positions.append({'x': x, 'y': y, 'width': tw, 'height': th})
    return positions
