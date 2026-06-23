"""Layout.json I/O, геометрия мест, стены и двери."""
import json
import os
import tempfile
import threading

from internal.utils.paths import LAYOUT_PATH

_LAYOUT_CACHE = None
_LAYOUT_LOCK = threading.RLock()


def _read_layout_file():
    with open(LAYOUT_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_layout_unlocked(layout):
    """Записать layout на диск атомарно (вызывать под _LAYOUT_LOCK)."""
    global _LAYOUT_CACHE
    dir_name = os.path.dirname(os.path.abspath(LAYOUT_PATH)) or '.'
    fd, tmp_path = tempfile.mkstemp(suffix='.json', dir=dir_name, prefix='.layout_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, LAYOUT_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    _LAYOUT_CACHE = layout
    from internal.layout.sync import reset_sync_cache
    reset_sync_cache()


def _save_layout(layout):
    with _LAYOUT_LOCK:
        _save_layout_unlocked(layout)


def _mutate_layout(mutator):
    """Потокобезопасное изменение layout.json."""
    with _LAYOUT_LOCK:
        layout = json.loads(json.dumps(load_layout()))
        result = mutator(layout)
        if result is False:
            return False
        _save_layout_unlocked(layout)
        return result if result is not None else True


def load_layout():
    global _LAYOUT_CACHE
    with _LAYOUT_LOCK:
        if _LAYOUT_CACHE is None:
            _LAYOUT_CACHE = _read_layout_file()
        return _LAYOUT_CACHE


def reload_layout():
    """Сбросить кеш layout.json (после записи)."""
    global _LAYOUT_CACHE
    with _LAYOUT_LOCK:
        _LAYOUT_CACHE = None
    from internal.layout.sync import reset_sync_cache
    reset_sync_cache()


def get_place_geometry(code):
    """Вернёт {x, y, width, height} для места по его коду."""
    for p in load_layout().get('places', []):
        if p['code'] == code:
            return {
                'x': p['x'], 'y': p['y'],
                'width': p['width'], 'height': p['height'],
                'rotation': p.get('rotation', 0),
                'floor': p.get('floor', 1),
            }
    return {'x': 0, 'y': 0, 'width': 100, 'height': 100, 'rotation': 0, 'floor': 1}


def get_layout_place_meta(code):
    """Метаданные места из layout.json (container_code, enclosed и т.д.)."""
    for p in load_layout().get('places', []):
        if p.get('code') == code:
            return p
    return {}


def migrate_rooms_to_spaces_in_layout():
    """room → space (единый тип «помещение»)."""
    layout = load_layout()
    changed = False
    for p in layout.get('places', []):
        if p.get('kind') == 'room':
            p['kind'] = 'space'
            if 'enclosed' not in p:
                p['enclosed'] = True
            changed = True
    if changed:
        _save_layout(layout)
    return changed


def save_place_geometry(code, x, y, floor=None):
    def mutate(layout):
        for p in layout.get('places', []):
            if p['code'] == code:
                p['x'] = float(x)
                p['y'] = float(y)
                if floor is not None:
                    p['floor'] = int(floor)
                return True
        return False
    return bool(_mutate_layout(mutate))


def add_place_to_layout(place_dict):
    def mutate(layout):
        layout.setdefault('places', []).append(place_dict)
    _mutate_layout(mutate)
    return True


def add_places_to_layout(place_dicts):
    """Пакетное добавление мест — одна запись в файл."""
    if not place_dicts:
        return True

    def mutate(layout):
        layout.setdefault('places', []).extend(place_dicts)

    _mutate_layout(mutate)
    return True


def replace_container_desks_in_layout(container_code, place_dicts):
    """Заменить все столы зоны одной атомарной записью (без дублей по code)."""
    def mutate(layout):
        places = layout.get('places', [])
        kept = [
            p for p in places
            if not (p.get('kind') == 'desk' and p.get('container_code') == container_code)
        ]
        seen = {p.get('code') for p in kept if p.get('code')}
        for row in place_dicts or []:
            code = row.get('code')
            if not code or code in seen:
                continue
            seen.add(code)
            kept.append(dict(row))
        layout['places'] = kept

    _mutate_layout(mutate)
    return True


def dedupe_layout_places():
    """Убрать повторяющиеся code в places (оставить запись побогаче)."""
    def richness(p):
        return sum(1 for k in ('name', 'location', 'category_id') if p.get(k))

    def mutate(layout):
        out = []
        best_by_code = {}
        for p in layout.get('places', []):
            code = p.get('code')
            if not code:
                out.append(p)
                continue
            prev = best_by_code.get(code)
            if prev is None:
                best_by_code[code] = p
            elif richness(p) > richness(prev):
                best_by_code[code] = p
        out.extend(best_by_code[c] for c in sorted(best_by_code))
        layout['places'] = out

    return _mutate_layout(mutate)


def rename_place_in_layout(old_code, new_code):
    """Переименовать место и обновить container_code у дочерних."""
    layout = load_layout()
    found = False
    for p in layout.get('places', []):
        if p.get('code') == old_code:
            p['code'] = new_code
            found = True
        if p.get('container_code') == old_code:
            p['container_code'] = new_code
    if not found:
        return False
    _save_layout(layout)
    return True


def remove_place_from_layout(code):
    layout = load_layout()
    places = layout.get('places', [])
    for p in places:
        if p.get('container_code') == code:
            del p['container_code']
    new_places = [p for p in places if p.get('code') != code]
    if len(new_places) == len(places):
        return False
    layout['places'] = new_places
    _save_layout(layout)
    return True


def save_place_category_in_layout(code, category_id):
    try:
        layout = load_layout()
        place_found = False
        for p in layout.get('places', []):
            if p['code'] == code:
                place_found = True
                if category_id:
                    p['category_id'] = int(category_id)
                elif 'category_id' in p:
                    del p['category_id']
                break
        if not place_found:
            return False
        _save_layout(layout)
        return True
    except Exception:
        return False


def save_place_zone_in_layout(code, location_code, zone_type_id=None):
    layout = load_layout()
    for p in layout.get('places', []):
        if p.get('code') == code:
            p['location'] = location_code
            if zone_type_id:
                p['zone_type_id'] = int(zone_type_id)
            elif 'zone_type_id' in p:
                del p['zone_type_id']
            break
    else:
        return False
    _save_layout(layout)
    return True


def resize_place(code, width, height):
    layout = load_layout()
    for p in layout.get('places', []):
        if p['code'] == code:
            p['width'] = float(width)
            p['height'] = float(height)
            break
    else:
        return False
    _save_layout(layout)
    return True


def rotate_place(code, rotation):
    layout = load_layout()
    for p in layout.get('places', []):
        if p['code'] == code:
            p['rotation'] = float(rotation) % 360
            break
    else:
        return False
    _save_layout(layout)
    return True


def load_walls():
    return load_layout().get('walls', [])


def save_walls(walls):
    layout = load_layout()
    layout['walls'] = walls
    _save_layout(layout)


def load_ignored_drafts(floor=None):
    """Черновики комнат, убранные с карты вручную."""
    items = load_layout().get('ignored_drafts', []) or []
    if floor is None:
        return items
    return [ig for ig in items if int(ig.get('floor', 1)) == int(floor)]


def _draft_room_key(room, floor=1):
    x = int(room['x'])
    y = int(room['y'])
    w = int(room['width'])
    h = int(room['height'])
    f = int(floor or room.get('floor', 1))
    return f"wall-{x}-{y}-{w}-{h}-f{f}"


def add_ignored_draft(room, floor=1):
    layout = load_layout()
    ignored = layout.setdefault('ignored_drafts', [])
    entry = {
        'x': int(room['x']),
        'y': int(room['y']),
        'width': int(room['width']),
        'height': int(room['height']),
        'floor': int(floor or room.get('floor', 1)),
        'room_key': room.get('room_key') or _draft_room_key(room, floor),
    }
    for ig in ignored:
        if _ignored_entry_matches(ig, entry):
            return ig
    ignored.append(entry)
    _save_layout(layout)
    return entry


def _ignored_entry_matches(a, b, tol=40):
    if a.get('room_key') and b.get('room_key') and a['room_key'] == b['room_key']:
        return True
    if int(a.get('floor', 1)) != int(b.get('floor', 1)):
        return False
    return (
        abs(int(a['x']) - int(b['x'])) <= tol
        and abs(int(a['y']) - int(b['y'])) <= tol
        and abs(int(a['width']) - int(b['width'])) <= tol
        and abs(int(a['height']) - int(b['height'])) <= tol
    )


def remove_ignored_draft(room_key=None, x=None, y=None, width=None, height=None, floor=1):
    """Снять ручное скрытие черновика (вернуть детект зоны)."""
    layout = load_layout()
    ignored = layout.get('ignored_drafts', []) or []
    if not ignored:
        return False
    entry = {
        'x': int(x) if x is not None else None,
        'y': int(y) if y is not None else None,
        'width': int(width) if width is not None else None,
        'height': int(height) if height is not None else None,
        'floor': int(floor or 1),
        'room_key': room_key,
    }
    kept = []
    removed = False
    for ig in ignored:
        if room_key and ig.get('room_key') == room_key:
            removed = True
            continue
        if entry['x'] is not None and _ignored_entry_matches(ig, entry, tol=24):
            removed = True
            continue
        kept.append(ig)
    if not removed:
        return False
    layout['ignored_drafts'] = kept
    _save_layout(layout)
    return True


def purge_ignored_drafts_touching_wall(wall, floor=1):
    """Убрать скрытие зон, граница которых затронута удаляемой стеной."""
    from internal.utils.room_geometry import _wall_on_room_edge

    layout = load_layout()
    ignored = layout.get('ignored_drafts', []) or []
    if not ignored:
        return []
    floor = int(floor or wall.get('floor', 1))
    kept = []
    removed_keys = []
    for ig in ignored:
        if int(ig.get('floor', 1)) != floor:
            kept.append(ig)
            continue
        room_box = {
            'x': int(ig['x']), 'y': int(ig['y']),
            'width': int(ig['width']), 'height': int(ig['height']),
        }
        if _wall_on_room_edge(wall, room_box):
            removed_keys.append(ig.get('room_key'))
            continue
        kept.append(ig)
    if len(kept) == len(ignored):
        return []
    layout['ignored_drafts'] = kept
    _save_layout(layout)
    return removed_keys


def prune_stale_ignored_drafts(floor=1):
    """Удалить скрытие, если ячейка стен больше не существует (геометрия изменилась)."""
    from internal.utils.room_geometry import detect_all_wall_rooms, _find_room_match

    floor = int(floor or 1)
    layout = load_layout()
    ignored = layout.get('ignored_drafts', []) or []
    if not ignored:
        return []
    raw_rooms = detect_all_wall_rooms(load_walls(), floor, apply_ignored=False)
    kept = []
    removed_keys = []
    for ig in ignored:
        if int(ig.get('floor', 1)) != floor:
            kept.append(ig)
            continue
        match = _find_room_match(
            ig['x'], ig['y'], ig['width'], ig['height'], raw_rooms, tol=20,
        )
        if match:
            kept.append(ig)
        else:
            removed_keys.append(ig.get('room_key'))
    if len(kept) == len(ignored):
        return []
    layout['ignored_drafts'] = kept
    _save_layout(layout)
    return removed_keys


def remove_layout_places_in_box(x, y, width, height, floor=1):
    """Убрать space/room из layout внутри указанного контура."""
    layout = load_layout()
    removed = []
    box = {'x': int(x), 'y': int(y), 'width': int(width), 'height': int(height), 'floor': int(floor)}
    kept = []
    for p in layout.get('places', []):
        if p.get('kind') not in ('space', 'room'):
            kept.append(p)
            continue
        if int(p.get('floor', 1)) != int(floor):
            kept.append(p)
            continue
        from internal.utils.room_geometry import _geom_match
        if _geom_match(p, box, tol=36):
            removed.append(p.get('code'))
            continue
        kept.append(p)
    if not removed:
        return removed
    layout['places'] = kept
    _save_layout(layout)
    return removed


def _default_floor_size(layout=None):
    """Размеры этажа по умолчанию (из существующего этажа или сетки)."""
    from internal.layout.geometry import CANVAS_HEIGHT, CANVAS_WIDTH

    layout = layout or load_layout()
    floors = layout.get('floors', [])
    if floors:
        ref = floors[0]
        return int(ref.get('width', CANVAS_WIDTH)), int(ref.get('height', CANVAS_HEIGHT))
    grid = layout.get('grid', {})
    cell = int(grid.get('cell', 28))
    cols = int(grid.get('cols', 80))
    rows = int(grid.get('rows', 48))
    return cols * cell, rows * cell


def _floor_size(floor_num):
    from internal.layout.geometry import CANVAS_HEIGHT, CANVAS_WIDTH

    for fl in load_layout().get('floors', []):
        if int(fl.get('number', 0)) == int(floor_num):
            return int(fl.get('width', CANVAS_WIDTH)), int(fl.get('height', CANVAS_HEIGHT))
    return _default_floor_size()


def provision_new_floor_layout(floor_number, name=None):
    """Добавить этаж в layout.json: метаданные, несущие стены по периметру, входная дверь."""
    layout = load_layout()
    floors = layout.setdefault('floors', [])
    floor_num = int(floor_number)

    existing_meta = next((f for f in floors if int(f.get('number', 0)) == floor_num), None)
    if not existing_meta:
        ref_w, ref_h = _default_floor_size(layout)
        new_id = max([int(f.get('id', 0)) for f in floors], default=0) + 1
        display_name = (name or '').strip() or f'{floor_num}-й этаж'
        floors.append({
            'id': new_id,
            'number': floor_num,
            'name': display_name,
            'width': ref_w,
            'height': ref_h,
        })
        floors.sort(key=lambda f: int(f.get('number', 0)))
        _save_layout(layout)

    w, h = _floor_size(floor_num)
    floor_walls = [
        wl for wl in load_walls() if int(wl.get('floor', 1)) == floor_num
    ]
    if not any(wl.get('protected') for wl in floor_walls):
        add_wall(0, 0, w, 0, protected=True, floor=floor_num)
        add_wall(w, 0, w, h, protected=True, floor=floor_num)
        add_wall(w, h, 0, h, protected=True, floor=floor_num)
        left_wall_id = add_wall(0, h, 0, 0, protected=True, floor=floor_num)
        add_door(left_wall_id, 0.5, floor=floor_num, width=180)

    return True


def remove_floor_layout(floor_number):
    """Удалить этаж из layout.json: метаданные, стены, двери, места."""
    layout = load_layout()
    floor_num = int(floor_number)
    changed = False

    floors = layout.get('floors', [])
    new_floors = [f for f in floors if int(f.get('number', 0)) != floor_num]
    if len(new_floors) != len(floors):
        layout['floors'] = new_floors
        changed = True

    for key in ('places', 'walls', 'doors'):
        items = layout.get(key, [])
        new_items = [item for item in items if int(item.get('floor', 1)) != floor_num]
        if len(new_items) != len(items):
            layout[key] = new_items
            changed = True

    if changed:
        _save_layout(layout)
    return changed


def create_walls_around_rect(x, y, width, height, floor=1, skip_if_exists=True):
    """Четыре стены по периметру прямоугольника (закрытая зона)."""
    x, y, w, h = int(x), int(y), int(width), int(height)
    edges = [
        (x, y, x + w, y),
        (x, y + h, x + w, y + h),
        (x, y, x, y + h),
        (x + w, y, x + w, y + h),
    ]
    walls = load_walls()
    floor_walls = [wl for wl in walls if int(wl.get('floor', 1)) == int(floor)]
    created = []
    tol = 12
    for x1, y1, x2, y2 in edges:
        if skip_if_exists:
            found = False
            for wl in floor_walls:
                if abs(wl['x1'] - x1) <= tol and abs(wl['y1'] - y1) <= tol \
                        and abs(wl['x2'] - x2) <= tol and abs(wl['y2'] - y2) <= tol:
                    found = True
                    break
                if abs(wl['x1'] - x2) <= tol and abs(wl['y1'] - y2) <= tol \
                        and abs(wl['x2'] - x1) <= tol and abs(wl['y2'] - y1) <= tol:
                    found = True
                    break
            if found:
                continue
        created.append(add_wall(x1, y1, x2, y2, floor=floor))
    return created


def move_container_with_children(code, new_x, new_y):
    """Сдвинуть контейнер (space) и все дочерние столы."""
    layout = load_layout()
    container = None
    for p in layout.get('places', []):
        if p.get('code') == code:
            container = p
            break
    if not container:
        return None
    dx = float(new_x) - float(container['x'])
    dy = float(new_y) - float(container['y'])
    container['x'] = float(new_x)
    container['y'] = float(new_y)
    moved = [code]
    for p in layout.get('places', []):
        if p.get('container_code') == code:
            p['x'] = float(p['x']) + dx
            p['y'] = float(p['y']) + dy
            moved.append(p['code'])
    _save_layout(layout)
    return {'dx': dx, 'dy': dy, 'moved': moved}


def add_wall(x1, y1, x2, y2, protected=False, floor=1):
    from internal.layout.geometry import repair_wall_gaps

    walls = load_walls()
    wall_id = max([w.get('id', 0) for w in walls], default=0) + 1
    walls.append({
        'id': wall_id,
        'x1': int(x1), 'y1': int(y1), 'x2': int(x2), 'y2': int(y2),
        'protected': bool(protected),
        'floor': int(floor or 1),
    })
    repair_wall_gaps(walls, floor=int(floor or 1))
    save_walls(walls)
    return wall_id


def delete_wall(wall_id):
    walls = load_walls()
    target = next((w for w in walls if w.get('id') == wall_id), None)
    if target is None:
        raise ValueError('Стена не найдена')
    if target.get('protected'):
        raise PermissionError('Эту стену нельзя удалить (несущая)')
    floor = int(target.get('floor', 1))
    purge_ignored_drafts_touching_wall(target, floor)
    walls = [w for w in walls if w.get('id') != wall_id]
    save_walls(walls)
    doors = [d for d in load_doors() if d.get('wall_id') != wall_id]
    save_doors(doors)
    prune_stale_ignored_drafts(floor)


def load_doors():
    return load_layout().get('doors', [])


def save_doors(doors):
    layout = load_layout()
    layout['doors'] = doors
    _save_layout(layout)


def add_door(wall_id, position, floor=1, width=100):
    from internal.layout.geometry import clamp_door_position

    walls = load_walls()
    wall = next((w for w in walls if w.get('id') == int(wall_id)), None)
    if not wall:
        raise ValueError('Стена не найдена')
    floor_walls = [w for w in walls if int(w.get('floor', 1)) == int(floor or 1)]
    pos = clamp_door_position(wall, position, int(width), floor_walls)
    doors = load_doors()
    door_id = max([d.get('id', 0) for d in doors], default=0) + 1
    doors.append({
        'id': door_id,
        'wall_id': int(wall_id),
        'position': float(pos),
        'width': int(width),
        'floor': int(floor or 1),
    })
    save_doors(doors)
    return door_id


def move_door(door_id, wall_id=None, position=None, width=None):
    from internal.layout.geometry import clamp_door_position

    doors = load_doors()
    walls = load_walls()
    for d in doors:
        if d.get('id') == int(door_id):
            w_id = int(wall_id if wall_id is not None else d['wall_id'])
            wall = next((w for w in walls if w.get('id') == w_id), None)
            if wall_id is not None:
                d['wall_id'] = w_id
            if position is not None or width is not None:
                dw = int(width if width is not None else d.get('width', 100))
                floor_walls = [w for w in walls if int(w.get('floor', 1)) == int(d.get('floor', 1))]
                raw = float(position if position is not None else d.get('position', 0.5))
                d['position'] = clamp_door_position(wall, raw, dw, floor_walls) if wall else max(0.0, min(1.0, raw))
            if width is not None:
                d['width'] = int(width)
                if wall:
                    floor_walls = [w for w in walls if int(w.get('floor', 1)) == int(d.get('floor', 1))]
                    d['position'] = clamp_door_position(wall, d['position'], int(width), floor_walls)
            break
    else:
        return False
    save_doors(doors)
    return True


def sync_wall_bound_places(floor=None):
    """Подтянуть геометрию локаций source=walls к актуальному контуру стен."""
    from internal.utils.room_geometry import detect_all_wall_rooms, match_place_to_room

    layout = load_layout()
    walls = layout.get('walls', [])
    floors = {int(floor)} if floor is not None else {
        int(w.get('floor', 1)) for w in walls
    }
    updated = []

    for fl in sorted(floors):
        floor_walls = [w for w in walls if int(w.get('floor', 1)) == fl]
        rooms = detect_all_wall_rooms(floor_walls, fl)
        for p in layout.get('places', []):
            if int(p.get('floor', 1)) != fl:
                continue
            if p.get('source') != 'walls':
                continue
            if p.get('kind') not in ('space', 'room'):
                continue
            for room in rooms:
                if not match_place_to_room(p, room):
                    continue
                dx = int(room['x']) - int(p['x'])
                dy = int(room['y']) - int(p['y'])
                p['x'] = int(room['x'])
                p['y'] = int(room['y'])
                p['width'] = int(room['width'])
                p['height'] = int(room['height'])
                pcode = p.get('code')
                if pcode and (dx or dy):
                    for child in layout.get('places', []):
                        if child.get('container_code') == pcode:
                            child['x'] = int(float(child['x']) + dx)
                            child['y'] = int(float(child['y']) + dy)
                updated.append(pcode)
                break

    if updated:
        _save_layout(layout)
    return updated


def _propagate_wall_junctions(walls, wall_id, old_x1, old_y1, old_x2, old_y2, new_x1, new_y1, new_x2, new_y2, tol=4):
    """При сдвиге стены подтянуть концы примыкающих стен — углы остаются соединёнными."""
    is_vert = abs(old_x1 - old_x2) < 3
    is_horz = abs(old_y1 - old_y2) < 3
    if not is_vert and not is_horz:
        return
    floor = next(
        (int(w.get('floor', 1)) for w in walls if w.get('id') == int(wall_id)),
        1,
    )
    if is_vert:
        old_x, new_x = int(old_x1), int(new_x1)
        for w in walls:
            if w.get('id') == wall_id or int(w.get('floor', 1)) != floor:
                continue
            for key in ('x1', 'x2'):
                if abs(int(w[key]) - old_x) <= tol:
                    w[key] = new_x
    elif is_horz:
        old_y, new_y = int(old_y1), int(new_y1)
        for w in walls:
            if w.get('id') == wall_id or int(w.get('floor', 1)) != floor:
                continue
            for key in ('y1', 'y2'):
                if abs(int(w[key]) - old_y) <= tol:
                    w[key] = new_y


def move_wall(wall_id, x1, y1, x2, y2):
    walls = load_walls()
    found = False
    wall_floor = 1
    old_coords = None
    for w in walls:
        if w.get('id') == int(wall_id):
            if w.get('protected'):
                raise PermissionError('Несущую стену нельзя перемещать')
            wall_floor = int(w.get('floor', 1))
            old_coords = (w['x1'], w['y1'], w['x2'], w['y2'])
            w['x1'] = int(x1)
            w['y1'] = int(y1)
            w['x2'] = int(x2)
            w['y2'] = int(y2)
            found = True
            break
    if not found:
        return None
    if old_coords:
        _propagate_wall_junctions(
            walls, wall_id,
            old_coords[0], old_coords[1], old_coords[2], old_coords[3],
            int(x1), int(y1), int(x2), int(y2),
        )
    save_walls(walls)
    return sync_wall_bound_places(floor=wall_floor)


def delete_door(door_id):
    doors = [d for d in load_doors() if d.get('id') != door_id]
    save_doors(doors)
