"""Синхронизация layout.json ↔ БД и генерация кодов мест."""
import json
import math
import os

from internal.models.db import db
from internal.layout.store import (
    get_layout_place_meta,
    load_layout,
    migrate_rooms_to_spaces_in_layout,
    reload_layout,
)
from internal.utils import paths


def _is_open_zone(place):
    return (
        place.get('kind') in ('space', 'room')
        and place.get('enclosed') is False
        and place.get('bookable') is not False
    )


def _desk_fits_parent(desk, container):
    """Стол в открытой зоне — целиком внутри; в закрытой — по центру."""
    from internal.layout.geometry import rect_contains

    if _is_open_zone(container):
        return rect_contains(
            container['x'], container['y'], container['width'], container['height'],
            desk['x'], desk['y'], desk.get('width', 0), desk.get('height', 0), 0,
        )
    cx = desk['x'] + desk['width'] / 2
    cy = desk['y'] + desk['height'] / 2
    rx, ry, rw, rh = container['x'], container['y'], container['width'], container['height']
    return rx <= cx <= rx + rw and ry <= cy <= ry + rh


def _desk_partial_open_zone_overlap(desk, containers):
    """Стол на границе открытой зоны — недопустимо."""
    from internal.layout.geometry import rect_contains, rects_meaningful_overlap

    dx, dy = float(desk['x']), float(desk['y'])
    dw, dh = float(desk.get('width', 0)), float(desk.get('height', 0))
    for room in containers or []:
        if not _is_open_zone(room):
            continue
        ix, iy, iw, ih = float(room['x']), float(room['y']), float(room['width']), float(room['height'])
        if not rects_meaningful_overlap(dx, dy, dw, dh, ix, iy, iw, ih):
            continue
        if not rect_contains(ix, iy, iw, ih, dx, dy, dw, dh, 0):
            return room
    return None


def _find_parent_container_for_desk(desk, containers):
    desk_floor = int(desk.get('floor', 1))
    matches = []
    for room in containers:
        if int(room.get('floor', 1)) != desk_floor:
            continue
        if not _desk_fits_parent(desk, room):
            continue
        matches.append((room['width'] * room['height'], room))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    return matches[0][1]


def _container_auto_parents_desks(room):
    """Автопривязка столов только к закрытым помещениям (не коридор)."""
    if not room:
        return False
    if room.get('bookable') is False:
        return False
    return room.get('enclosed', True) is not False


def desk_partial_open_zone_overlap(desk, containers):
    return _desk_partial_open_zone_overlap(desk, containers)


def auto_detect_place_parents_in_layout():
    layout = load_layout()
    places = layout.get('places', [])
    containers = [p for p in places if p.get('kind') in ('room', 'space')]
    changed = False
    for p in places:
        if p.get('kind') != 'desk':
            continue
        old_parent = p.get('container_code')

        if old_parent:
            old_container = next((c for c in containers if c.get('code') == old_parent), None)
            if old_container and not _container_auto_parents_desks(old_container):
                still_inside = _find_parent_container_for_desk(p, [old_container]) is not None
                if still_inside:
                    continue
                del p['container_code']
                changed = True
                continue

        room = _find_parent_container_for_desk(p, containers)
        if room and not _container_auto_parents_desks(room):
            if old_parent == room['code']:
                continue
            room = None
        new_parent = room['code'] if room else None
        if new_parent != old_parent:
            if new_parent:
                p['container_code'] = new_parent
                if room.get('kind') == 'room' and 'enclosed' not in room:
                    room['enclosed'] = True
            elif 'container_code' in p:
                del p['container_code']
            changed = True
    if changed:
        with open(paths.LAYOUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        reload_layout()
    return changed


def sync_place_meta_from_layout():
    """Синхронизировать container_code и enclosed из layout.json в БД."""
    from internal.models.place import Place

    for lp in load_layout().get('places', []):
        code = lp.get('code')
        if not code:
            continue
        place = Place.query.filter_by(code=code).first()
        if not place:
            continue
        container_code = lp.get('container_code')
        if place.kind == 'desk':
            place.container_code = container_code or None
        else:
            place.container_code = None
        kind = lp.get('kind')
        if kind == 'room':
            place.kind = 'space'
            kind = 'space'
        if kind in ('room', 'space'):
            place.enclosed = bool(lp.get('enclosed', True))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def sync_parent_ids_from_layout():
    """Обратная совместимость — раньше синхронизировали parent_id."""
    sync_place_meta_from_layout()


def infer_floor_from_location_code(code):
    """Этаж из маркировки: 1A-1 → 1, 1Б → 1."""
    if not code:
        return 1
    base = str(code).split('-')[0]
    if base and base[0].isdigit():
        return int(base[0])
    return 1


FLOOR_DEFAULT_LOCATION = {1: '1A', 2: '2A', 3: '2A'}


def default_location_code_for_floor(floor_num, zone_letter=None):
    from internal.models.location_zone import LocationZoneType, build_location_prefix

    floor_num = int(floor_num or 1)
    if zone_letter:
        return build_location_prefix(floor_num, zone_letter)
    if floor_num in FLOOR_DEFAULT_LOCATION:
        return FLOOR_DEFAULT_LOCATION[floor_num]
    zone = LocationZoneType.query.filter_by(active=True).order_by(
        LocationZoneType.letter
    ).first()
    letter = zone.letter if zone else 'A'
    return build_location_prefix(floor_num, letter)


def sync_place_locations_from_layout():
    """Синхронизировать location_id/floor_id в БД из поля location в layout.json."""
    from internal.models.coworking import Floor, Location
    from internal.models.place import Place

    for lp in load_layout().get('places', []):
        code = lp.get('code')
        if not code:
            continue
        place = Place.query.filter_by(code=code).first()
        if not place:
            continue
        loc = Location.query.filter_by(code=lp.get('location')).first()
        floor = Floor.query.filter_by(number=int(lp.get('floor', 1))).first()
        if loc:
            place.location_id = loc.id
        if floor:
            place.floor_id = floor.id
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def sync_location_floors_from_layout():
    from internal.models.coworking import Floor, Location

    changed = False
    for loc_data in load_layout().get('locations', []):
        code = loc_data.get('code')
        if not code:
            continue
        loc = Location.query.filter_by(code=code).first()
        if not loc:
            continue
        floor_num = int(loc_data.get('floor') or infer_floor_from_location_code(code))
        floor = Floor.query.filter_by(number=floor_num).first()
        if floor and loc.floor_id != floor.id:
            loc.floor_id = floor.id
            changed = True
    if changed:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return changed


OPEN_ZONE_PAD = 8
OPEN_ZONE_CLUSTER_GAP = 200


_last_sync_mtime: float | None = None


def reset_sync_cache() -> None:
    global _last_sync_mtime
    _last_sync_mtime = None


def ensure_place_parent_links() -> None:
    """Синхронизирует родительские связи мест с layout.json.

    Пропускает всю работу, если layout.json не изменялся с прошлого вызова.
    """
    global _last_sync_mtime
    from internal.utils import paths

    try:
        mtime = os.path.getmtime(paths.LAYOUT_PATH)
    except OSError:
        mtime = None

    if _last_sync_mtime is not None and _last_sync_mtime == mtime:
        return

    auto_detect_place_parents_in_layout()
    sync_place_meta_from_layout()
    sync_place_locations_from_layout()
    sync_zone_categories_in_layout()
    _last_sync_mtime = mtime


def _zone_seat_count(space_code, layout_places):
    from internal.models.category import PlaceCategory

    total = 0
    for lp in layout_places:
        if lp.get('container_code') != space_code or lp.get('kind') != 'desk':
            continue
        if lp.get('visual_only'):
            continue
        cat_id = lp.get('category_id')
        if cat_id:
            cat = PlaceCategory.query.get(cat_id)
            total += cat.capacity if cat else 1
        else:
            total += int(lp.get('capacity', 1) or 1)
    return total


def _layout_size_m(layout_place):
    """Размер помещения из layout.json (пиксели → метры, SCALE=100)."""
    from internal.models.category import PlaceCategory
    scale = PlaceCategory.SCALE_FACTOR
    w_px = float(layout_place.get('width') or 0)
    h_px = float(layout_place.get('height') or 0)
    if w_px <= 0 or h_px <= 0:
        return 0.0, 0.0
    return round(w_px / scale, 2), round(h_px / scale, 2)


def _zone_desk_tariff_sum(space_code, layout_places, tariff_type='hourly'):
    """Сумма тарифов всех столов в закрытой зоне."""
    from internal.models.category import PlaceCategory

    total = 0.0
    for lp in layout_places:
        if lp.get('container_code') != space_code or lp.get('kind') != 'desk':
            continue
        if lp.get('visual_only'):
            continue
        cat_id = lp.get('category_id')
        price = None
        if cat_id:
            cat = PlaceCategory.query.get(cat_id)
            if cat:
                t = cat.get_tariff(tariff_type)
                if t:
                    price = t.price
        if price is None:
            base = PlaceCategory.query.filter_by(kind='desk', capacity=1).first()
            if base:
                t = base.get_tariff(tariff_type)
                price = t.price if t else 250.0
            else:
                price = 250.0
        total += float(price)
    return round(total, 2)


def get_or_create_zone_category(seat_count, space_code, width_m, height_m):
    """Категория для закрытой зоны столов (бронь целиком, capacity=1 для биллинга)."""
    from internal.models.category import CategoryTariff, PlaceCategory

    seat_count = max(1, int(seat_count))
    space_code = str(space_code or '').strip()
    name = f'Закрытая зона {space_code} · {seat_count} мест'
    cat = PlaceCategory.query.filter_by(name=name, kind='desk').first()
    if cat:
        updated = False
        desc = f'Зона на {seat_count} рабочих мест'
        if cat.description != desc:
            cat.description = desc
            updated = True
        if width_m > 0 and height_m > 0:
            if cat.width_m != width_m or cat.height_m != height_m:
                cat.width_m = width_m
                cat.height_m = height_m
                updated = True
        layout = load_layout()
        for tariff_type in ('hourly', 'weekly', 'monthly'):
            price = _zone_desk_tariff_sum(space_code, layout.get('places', []), tariff_type)
            if price <= 0:
                continue
            t = cat.get_tariff(tariff_type)
            if t and t.price != price:
                t.price = price
                updated = True
            elif not t:
                db.session.add(CategoryTariff(
                    category_id=cat.id, tariff_type=tariff_type, price=price, active=True,
                ))
                updated = True
        if updated:
            db.session.flush()
        return cat

    base = PlaceCategory.query.filter_by(kind='desk', capacity=1).first()
    cat = PlaceCategory(
        name=name,
        kind='desk',
        capacity=1,
        description=f'Зона на {seat_count} рабочих мест',
        width_m=width_m if width_m > 0 else 1.0,
        height_m=height_m if height_m > 0 else 0.75,
        active=True,
    )
    db.session.add(cat)
    db.session.flush()

    default_prices = {}
    layout = load_layout()
    summed_hourly = _zone_desk_tariff_sum(space_code, layout.get('places', []), 'hourly')
    summed_weekly = _zone_desk_tariff_sum(space_code, layout.get('places', []), 'weekly')
    summed_monthly = _zone_desk_tariff_sum(space_code, layout.get('places', []), 'monthly')
    if summed_hourly > 0:
        default_prices = {
            'hourly': summed_hourly,
            'weekly': summed_weekly or round(summed_hourly * 14, 2),
            'monthly': summed_monthly or round(summed_hourly * 48, 2),
        }
    elif base:
        for bt in base.tariffs:
            if not bt.active:
                continue
            if bt.tariff_type == 'hourly':
                default_prices['hourly'] = round(bt.price * seat_count * 0.9, 2)
            elif bt.tariff_type == 'weekly':
                default_prices['weekly'] = round(bt.price * seat_count * 0.85, 2)
            elif bt.tariff_type == 'monthly':
                default_prices['monthly'] = round(bt.price * seat_count * 0.85, 2)
    if not default_prices:
        default_prices = {
            'hourly': round(250 * seat_count * 0.9, 2),
            'weekly': round(3500 * seat_count * 0.85, 2),
            'monthly': round(12000 * seat_count * 0.85, 2),
        }

    for tariff_type, price in default_prices.items():
        db.session.add(CategoryTariff(
            category_id=cat.id,
            tariff_type=tariff_type,
            price=price,
            active=True,
        ))
    db.session.flush()
    return cat


def assign_zone_category_for_space(space_code):
    """Привязать категорию зоны к закрытому помещению со столами."""
    from internal.models.location_zone import ROOM_ZONE_KIND
    from internal.models.place import Place

    layout = load_layout()
    places = layout.get('places', [])
    space = next((p for p in places if p.get('code') == space_code), None)
    if not space or space.get('kind') not in ('space', 'room'):
        return False

    if not space.get('enclosed', True):
        return False
    if space.get('bookable') is False:
        return False

    zone_tid = space.get('zone_type_id')
    if zone_tid:
        from internal.models.location_zone import LocationZoneType
        zt = LocationZoneType.query.get(zone_tid)
        if zt and zt.kind == ROOM_ZONE_KIND:
            return False

    seats = _zone_seat_count(space_code, places)
    if seats < 1:
        return False

    w_m, h_m = _layout_size_m(space)
    cat = get_or_create_zone_category(seats, space_code, w_m, h_m)
    changed = False
    if space.get('category_id') != cat.id:
        space['category_id'] = cat.id
        changed = True

    db_place = Place.query.filter_by(code=space_code).first()
    if db_place and db_place.category_id != cat.id:
        db_place.category_id = cat.id
        changed = True

    if changed:
        with open(paths.LAYOUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        reload_layout()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return changed


def sync_zone_categories_in_layout():
    """Создать/обновить категории и тарифы для закрытых зон рабочих столов."""
    _fix_legacy_zone_category_descriptions()
    layout = load_layout()
    places = layout.get('places', [])
    changed_any = False
    for sp in places:
        if sp.get('kind') not in ('space', 'room'):
            continue
        if assign_zone_category_for_space(sp['code']):
            changed_any = True
    return changed_any


def _fix_legacy_zone_category_descriptions():
    """Убрать англ. zone_seats:N из старых категорий."""
    import re
    from internal.models.category import PlaceCategory

    for cat in PlaceCategory.query.filter(
        PlaceCategory.description.like('zone_seats:%'),
    ).all():
        m = re.search(r'zone_seats:(\d+)', cat.description or '')
        if m:
            cat.description = f'Зона на {m.group(1)} рабочих мест'
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def merge_overlapping_open_zones():
    """Слить пересекающиеся открытые зоны одного этажа в одну."""
    layout = load_layout()
    places = layout.get('places', [])
    open_zones = [p for p in places if _is_open_zone(p)]
    if len(open_zones) < 2:
        return False

    changed = False
    removed_codes = set()

    def zone_key(z):
        return (int(z.get('floor', 1)), z.get('location') or '')

    from internal.layout.geometry import rects_overlap, rect_contains

    i = 0
    while i < len(open_zones):
        if open_zones[i].get('code') in removed_codes:
            i += 1
            continue
        a = open_zones[i]
        j = i + 1
        while j < len(open_zones):
            if open_zones[j].get('code') in removed_codes:
                j += 1
                continue
            b = open_zones[j]
            if zone_key(a) != zone_key(b):
                j += 1
                continue
            ax, ay, aw, ah = a['x'], a['y'], a['width'], a['height']
            bx, by, bw, bh = b['x'], b['y'], b['width'], b['height']
            if not rects_overlap(ax, ay, aw, ah, bx, by, bw, bh, gap=0):
                j += 1
                continue
            # Поглощаем меньшую зоной большую
            big, small = (a, b) if aw * ah >= bw * bh else (b, a)
            if big.get('code') in removed_codes or small.get('code') in removed_codes:
                j += 1
                continue
            min_x = min(big['x'], small['x'])
            min_y = min(big['y'], small['y'])
            max_x = max(big['x'] + big['width'], small['x'] + small['width'])
            max_y = max(big['y'] + big['height'], small['y'] + small['height'])
            big['x'] = int(min_x)
            big['y'] = int(min_y)
            big['width'] = int(max_x - min_x)
            big['height'] = int(max_y - min_y)
            sc = small['code']
            for p in places:
                if p.get('container_code') == sc:
                    p['container_code'] = big['code']
            removed_codes.add(sc)
            changed = True
            j += 1
        i += 1

    if not changed:
        return False

    from internal.models.place import Place
    from internal.repositories.place_repository import PlaceRepository

    layout['places'] = [p for p in places if p.get('code') not in removed_codes]
    with open(paths.LAYOUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(layout, f, ensure_ascii=False, indent=2)
    reload_layout()
    for code in removed_codes:
        pl = PlaceRepository.get_by_code(code)
        if pl:
            db.session.delete(pl)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return True


def _desk_center(desk):
    return (
        desk['x'] + desk.get('width', 100) / 2,
        desk['y'] + desk.get('height', 100) / 2,
    )


def _cluster_orphan_desks(desks):
    """Группируем «сирот» по близости — отдельные коридоры = отдельные зоны."""
    clusters = []
    for desk in desks:
        cx, cy = _desk_center(desk)
        matched = None
        for cluster in clusters:
            for other in cluster:
                ox, oy = _desk_center(other)
                if math.hypot(cx - ox, cy - oy) <= OPEN_ZONE_CLUSTER_GAP:
                    matched = cluster
                    break
            if matched:
                break
        if matched:
            matched.append(desk)
        else:
            clusters.append([desk])
    return clusters


def _bounds_for_desks(desks, pad=OPEN_ZONE_PAD):
    min_x = min(d['x'] for d in desks) - pad
    min_y = min(d['y'] for d in desks) - pad
    max_x = max(d['x'] + d.get('width', 100) for d in desks) + pad
    max_y = max(d['y'] + d.get('height', 100) for d in desks) + pad
    return min_x, min_y, max_x, max_y


def _is_open_zone(place):
    return (
        place.get('kind') in ('space', 'room')
        and not place.get('container_code')
        and place.get('enclosed') is False
    )


def _find_open_zone_for_cluster(places, floor, loc, desks):
    min_x, min_y, max_x, max_y = _bounds_for_desks(desks)
    best = None
    best_area = None
    for zone in places:
        if not _is_open_zone(zone):
            continue
        if int(zone.get('floor', 1)) != int(floor):
            continue
        if (zone.get('location') or '') != loc:
            continue
        zx, zy = zone['x'], zone['y']
        zw, zh = zone['width'], zone['height']
        overlaps = not (
            max_x < zx or min_x > zx + zw or max_y < zy or min_y > zy + zh
        )
        if not overlaps:
            cx = (min_x + max_x) / 2
            cy = (min_y + max_y) / 2
            if not (zx <= cx <= zx + zw and zy <= cy <= zy + zh):
                continue
        area = zw * zh
        if best is None or area < best_area:
            best = zone
            best_area = area
    return best


def _expand_open_zone(zone, desks):
    min_x, min_y, max_x, max_y = _bounds_for_desks(desks)
    zx, zy = zone['x'], zone['y']
    zw, zh = zone['width'], zone['height']
    new_min_x = min(zx, min_x)
    new_min_y = min(zy, min_y)
    new_max_x = max(zx + zw, max_x)
    new_max_y = max(zy + zh, max_y)
    zone['x'] = int(new_min_x)
    zone['y'] = int(new_min_y)
    zone['width'] = int(max(120, new_max_x - new_min_x))
    zone['height'] = int(max(120, new_max_y - new_min_y))


def sync_open_zones_to_db():
    """Создать в БД открытые зоны из layout (коридоры)."""
    for lp in load_layout().get('places', []):
        if _is_open_zone(lp):
            sync_place_by_code(lp['code'])


def wrap_orphan_desks_in_open_spaces():
    layout = load_layout()
    places = layout.get('places', [])
    orphans = [p for p in places if p.get('kind') == 'desk' and not p.get('container_code')]
    if not orphans:
        return False

    floor_loc_groups = {}
    for d in orphans:
        key = (
            int(d.get('floor', 1)),
            d.get('location') or default_location_code_for_floor(d.get('floor', 1)),
        )
        floor_loc_groups.setdefault(key, []).append(d)

    changed = False
    open_zone_counter = {}
    for (floor, loc), group_desks in floor_loc_groups.items():
        for cluster in _cluster_orphan_desks(group_desks):
            existing = _find_open_zone_for_cluster(places, floor, loc, cluster)
            if existing:
                _expand_open_zone(existing, cluster)
                zone_code = existing['code']
                if not existing.get('name') or existing['name'].startswith('Открытая зона'):
                    n = sum(1 for p in places if _is_open_zone(p) and int(p.get('floor', 1)) == floor)
                    existing['name'] = f'Коридор {loc}' + (f' ({n})' if n > 1 else '')
            else:
                min_x, min_y, max_x, max_y = _bounds_for_desks(cluster)
                open_zone_counter[(floor, loc)] = open_zone_counter.get((floor, loc), 0) + 1
                idx = open_zone_counter[(floor, loc)]
                code = generate_place_code('space', loc)
                label = f'Коридор {loc}' + (f' ({idx})' if idx > 1 else '')
                space = {
                    'code': code,
                    'name': label,
                    'location': loc,
                    'kind': 'space',
                    'enclosed': False,
                    'bookable': True,
                    'x': int(min_x),
                    'y': int(min_y),
                    'width': int(max(120, max_x - min_x)),
                    'height': int(max(120, max_y - min_y)),
                    'floor': floor,
                }
                places.append(space)
                zone_code = code
            for d in cluster:
                d['container_code'] = zone_code
            changed = True

    if changed:
        layout['places'] = places
        with open(paths.LAYOUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        reload_layout()
    return changed


def create_open_zone_from_desks(desk_codes, name=None, location_code=None):
    """Создать открытую зону вокруг выбранных столов (без автопривязки в коридоре)."""
    from internal.layout.geometry import (
        desks_overlap_each_other,
        find_place_overlap,
        fit_open_zone_bounds,
        nudge_desks_from_walls,
        rect_overlaps_walls,
        zone_overlaps_other_desks,
    )
    from internal.layout.store import load_walls
    from internal.repositories.place_repository import PlaceRepository

    codes = [str(c).strip() for c in (desk_codes or []) if str(c).strip()]
    if not codes:
        return False, 'Выберите хотя бы один стол', None

    layout = load_layout()
    places = layout.get('places', [])
    by_code = {p['code']: p for p in places if p.get('code')}

    desks = []
    for code in codes:
        desk = by_code.get(code)
        if not desk or desk.get('kind') != 'desk':
            return False, f'Стол «{code}» не найден', None
        if desk.get('container_code'):
            return False, f'«{code}» уже в зоне «{desk["container_code"]}»', None
        desks.append(desk)

    floor = int(desks[0].get('floor', 1))
    if any(int(d.get('floor', 1)) != floor for d in desks):
        return False, 'Все столы должны быть на одном этаже', None

    clusters = _cluster_orphan_desks(desks)
    if len(clusters) > 1:
        return False, 'Столы должны стоять рядом — выберите одну группу', None

    walls = load_walls()
    moved = nudge_desks_from_walls(desks, walls, floor)

    if desks_overlap_each_other(desks):
        return False, 'Столы пересекаются — раздвиньте их перед созданием зоны', None

    loc = location_code or desks[0].get('location') or default_location_code_for_floor(floor)
    zone_x, zone_y, zone_w, zone_h = fit_open_zone_bounds(desks, walls, floor)

    foreign = zone_overlaps_other_desks(
        places, zone_x, zone_y, zone_w, zone_h, floor, codes,
    )
    if foreign:
        return False, (
            f'Зона накладывается на стол «{foreign.get("code", "?")}» — '
            'уберите его из области или сдвиньте столы'
        ), None

    if rect_overlaps_walls(zone_x, zone_y, zone_w, zone_h, walls, floor):
        return False, 'Зона заходит на стену — сдвиньте столы от границы', None

    overlap_err = find_place_overlap(
        places, None, zone_x, zone_y, zone_w, zone_h, floor, 'space', None,
    )
    if overlap_err:
        return False, overlap_err, None

    code = generate_place_code('space', loc)
    n = sum(1 for p in places if _is_open_zone(p) and int(p.get('floor', 1)) == floor)
    label = (name or '').strip() or (f'Открытая зона {loc}' + (f' ({n + 1})' if n else ''))
    space = {
        'code': code,
        'name': label,
        'location': loc,
        'kind': 'space',
        'enclosed': False,
        'bookable': True,
        'x': zone_x,
        'y': zone_y,
        'width': zone_w,
        'height': zone_h,
        'floor': floor,
    }
    places.append(space)
    for desk in desks:
        desk['container_code'] = code

    layout['places'] = places
    with open(paths.LAYOUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(layout, f, ensure_ascii=False, indent=2)
    reload_layout()

    sync_place_by_code(code)
    for desk in desks:
        sync_place_by_code(desk['code'])
    sync_parent_ids_from_layout()

    place = PlaceRepository.sync_by_code(code)
    return True, None, {
        'code': code,
        'name': label,
        'desk_codes': [d['code'] for d in desks],
        'moved_desks': moved,
        'place': place.to_dict() if place else None,
    }


def sync_place_parents_from_layout():
    from internal.models.place import Place

    migrate_rooms_to_spaces_in_layout()
    auto_detect_place_parents_in_layout()

    for lp in load_layout().get('places', []):
        code = lp.get('code')
        if code:
            sync_place_by_code(code)

    for lp in load_layout().get('places', []):
        code = lp.get('code')
        if not code:
            continue
        place = Place.query.filter_by(code=code).first()
        if not place:
            continue
        container_code = lp.get('container_code')
        if place.kind == 'desk':
            place.container_code = container_code or None
        else:
            place.container_code = None
        kind = lp.get('kind')
        if kind == 'room':
            place.kind = 'space'
            kind = 'space'
        if kind in ('room', 'space'):
            place.enclosed = bool(lp.get('enclosed', True))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    for p in Place.query.filter_by(kind='room').all():
        p.kind = 'space'
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def sync_place_by_code(code):
    from internal.models.category import PlaceCategory
    from internal.models.coworking import Location
    from internal.models.place import Place

    if not code:
        return None
    code = str(code).strip()
    if code.startswith('temp_'):
        code = code[5:]

    place = Place.query.filter_by(code=code).first()
    if place:
        return place

    layout_place = next(
        (p for p in load_layout().get('places', []) if p.get('code') == code),
        None,
    )
    if not layout_place:
        return None

    location = Location.query.filter_by(code=layout_place.get('location')).first()
    if not location:
        return None

    category_id = layout_place.get('category_id')
    if category_id and not PlaceCategory.query.get(category_id):
        category_id = None
    is_open_container = (
        layout_place.get('kind') in ('space', 'room')
        and not layout_place.get('enclosed', True)
    )
    if not category_id:
        if layout_place.get('kind') == 'room':
            cat = PlaceCategory.query.filter_by(kind='room').first()
            category_id = cat.id if cat else None
        elif is_open_container:
            category_id = None
        elif layout_place.get('kind') == 'desk':
            cat = PlaceCategory.query.filter_by(
                kind='desk', capacity=layout_place.get('capacity', 1)
            ).first()
            category_id = cat.id if cat else None
        else:
            cat = PlaceCategory.query.filter_by(
                kind='desk', capacity=layout_place.get('capacity', 1)
            ).first()
            category_id = cat.id if cat else None

    place = Place(
        code=code,
        name=layout_place.get('name', code),
        location_id=location.id,
        floor_id=location.floor_id,
        kind=layout_place.get('kind', 'desk'),
        category_id=category_id,
    )
    if layout_place.get('kind') == 'room':
        place.kind = 'space'
    container_code = layout_place.get('container_code')
    if container_code and place.kind == 'desk':
        place.container_code = container_code
    if layout_place.get('kind') in ('room', 'space'):
        place.enclosed = bool(layout_place.get('enclosed', layout_place.get('kind') == 'room'))
    db.session.add(place)
    db.session.commit()
    return place


def resolve_place_id(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if s.isdigit():
        return int(s)
    place = sync_place_by_code(s)
    return place.id if place else None


def _code_tag_for_kind(kind):
    return 'L' if kind in ('space', 'room') else 'T'


def _max_place_code_index(location_code, tag, existing_codes):
    """Максимальный номер для {location}-{tag}N, с учётом старых кодов 1A-3."""
    prefix = f'{location_code}-{tag}'
    legacy_prefix = f'{location_code}-'
    max_n = 0
    for c in existing_codes:
        if not c or not c.startswith(legacy_prefix):
            continue
        if c.startswith(prefix):
            suffix = c[len(prefix):]
            if suffix.isdigit():
                max_n = max(max_n, int(suffix))
            continue
        if tag == 'T':
            suffix = c[len(legacy_prefix):]
            if suffix.isdigit():
                max_n = max(max_n, int(suffix))
    return max_n


def _place_code_index(code, location_code, tag):
    """Номер из {location}-{tag}N; для столов учитываем старый формат {location}-N."""
    if not code:
        return None
    prefix = f'{location_code}-{tag}'
    legacy_prefix = f'{location_code}-'
    if code.startswith(prefix):
        suffix = code[len(prefix):]
        return int(suffix) if suffix.isdigit() else None
    if tag == 'T' and code.startswith(legacy_prefix):
        suffix = code[len(legacy_prefix):]
        return int(suffix) if suffix.isdigit() else None
    return None


def _occupied_place_codes(location_code):
    """Коды, занятые сейчас: на карте (layout) или активные в БД.

    Неактивные записи (удалённые столы) не раздувают следующий номер.
    """
    from internal.models.place import Place

    prefix = f'{location_code}-'
    codes = {
        p['code'] for p in load_layout().get('places', [])
        if p.get('code') and str(p['code']).startswith(prefix)
    }
    for (code,) in (
        Place.query.filter(
            Place.code.like(prefix + '%'),
            Place.active.is_(True),
        ).with_entities(Place.code)
    ):
        codes.add(code)
    return codes


def _reserved_place_codes(location_code):
    """Все коды, которые нельзя вернуть из-за unique constraint в БД."""
    from internal.models.place import Place

    prefix = f'{location_code}-'
    codes = {
        p['code'] for p in load_layout().get('places', [])
        if p.get('code') and str(p['code']).startswith(prefix)
    }
    for (code,) in (
        Place.query.filter(Place.code.like(prefix + '%')).with_entities(Place.code)
    ):
        codes.add(code)
    return codes


def generate_place_code(kind, location_code):
    """Уникальный код: локация 1A-L1, стол 1A-T1 (этаж+зона+тип+номер)."""
    tag = _code_tag_for_kind(kind)
    occupied = _occupied_place_codes(location_code)
    reserved = _reserved_place_codes(location_code)
    occupied_indexes = {
        idx for idx in (
            _place_code_index(code, location_code, tag) for code in occupied
        )
        if idx is not None and idx > 0
    }
    n = 1
    while True:
        candidate = f'{location_code}-{tag}{n}'
        if n not in occupied_indexes and candidate not in reserved:
            return candidate
        n += 1


def place_allows_child_desks(place):
    """Можно ли размещать рабочие столы (бронь по местам) внутри помещения."""
    if not place or not place.is_container():
        return False
    from internal.models.location_zone import is_amenity_zone_kind, zone_kind_allows_desks
    if place.location and place.location.zone_type:
        zkind = place.location.zone_type.kind
        if is_amenity_zone_kind(zkind):
            return False
        return zone_kind_allows_desks(zkind)
    layout_meta = get_layout_place_meta(place.code)
    if layout_meta.get('bookable') is False:
        return False
    if place.category and place.category.kind == 'room':
        return False
    return True


def place_allows_layout_items(place):
    """Можно ли размещать объекты планировки в редакторе (столы / мебель переговорной)."""
    if not place or not place.is_container():
        return False
    from internal.models.location_zone import is_amenity_zone_kind
    if place.location and place.location.zone_type:
        if is_amenity_zone_kind(place.location.zone_type.kind):
            return False
    layout_meta = get_layout_place_meta(place.code)
    if layout_meta.get('bookable') is False:
        return False
    return True


def rename_place_code(place, new_location_code):
    """Переименовать код места под новую зону: 1Б-10 → 1B-3."""
    from internal.layout.store import rename_place_in_layout
    from internal.models.place import Place

    old_code = place.code
    if old_code.startswith(new_location_code + '-'):
        return old_code, False

    new_code = generate_place_code(place.kind, new_location_code)
    if Place.query.filter_by(code=new_code).first() and new_code != old_code:
        layout = load_layout()
        existing = {p['code'] for p in layout.get('places', []) if p.get('code')}
        existing.add(old_code)
        tag = _code_tag_for_kind(place.kind)
        max_n = _max_place_code_index(new_location_code, tag, existing)
        new_code = f'{new_location_code}-{tag}{max_n + 1}'

    if not rename_place_in_layout(old_code, new_code):
        return old_code, False

    place.code = new_code
    db.session.commit()
    return new_code, True


def apply_place_location_zone(place, floor_num, zone_type_id, rename_code=True):
    """Назначить категорию зоны месту; при смене префикса — переименовать код."""
    from internal.models.location_zone import LocationZoneType, ensure_location_for_zone, is_amenity_zone_kind
    from internal.layout.repository import LayoutRepository

    location = ensure_location_for_zone(floor_num, zone_type_id)
    if not location:
        return False, 'Зона локации не найдена', None

    renamed = False
    old_code = place.code
    if rename_code and not place.code.startswith(location.code + '-'):
        _, renamed = rename_place_code(place, location.code)

    place.location_id = location.id
    layout = load_layout()
    zone = LocationZoneType.query.get(int(zone_type_id))
    for p in layout.get('places', []):
        if p.get('code') == place.code:
            p['location'] = location.code
            p['zone_type_id'] = int(zone_type_id)
            if zone and is_amenity_zone_kind(zone.kind):
                p['bookable'] = False
                p.pop('category_id', None)
            break

    if zone and is_amenity_zone_kind(zone.kind):
        child_codes = [
            lp['code'] for lp in layout.get('places', [])
            if lp.get('container_code') == place.code and lp.get('kind') == 'desk'
        ]
        from internal.models.place import Place as PlaceModel
        from internal.models.booking import Booking
        for cc in child_codes:
            cp = PlaceModel.query.filter_by(code=cc).first()
            if cp:
                db.session.delete(cp)
            LayoutRepository.remove_place(cc)
        Booking.query.filter_by(place_id=place.id).delete()
        amenity_code = place.code
        db.session.delete(place)
        db.session.flush()
        with open(paths.LAYOUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        reload_layout()
        db.session.commit()
        return True, None, {'code': amenity_code, 'renamed': renamed, 'old_code': old_code if renamed else None, 'in_db': False}

    with open(paths.LAYOUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(layout, f, ensure_ascii=False, indent=2)
    reload_layout()
    db.session.commit()
    return True, None, {'code': place.code, 'renamed': renamed, 'old_code': old_code if renamed else None}


LEGACY_LETTER_MAP = {
    'Б': 'B', 'б': 'B', 'А': 'A', 'а': 'A', 'В': 'C', 'в': 'C',
    'К': 'K', 'к': 'K',
}


def _normalize_zone_letter(letter):
    return LEGACY_LETTER_MAP.get(letter, str(letter)).upper()


def _has_modern_place_code(code, location_code):
    import re
    if not code or not location_code:
        return False
    if re.match(rf'^{re.escape(location_code)}-[LT]\d+$', code):
        return True
    # Стабильные коды 1Б-04, 1Б-62 — не переименовывать при старте
    return bool(re.match(rf'^{re.escape(location_code)}-\d+$', code))


def _legacy_place_suffix_number(code, location_code):
    if not code or not code.startswith(location_code + '-'):
        return None
    suffix = code[len(location_code) + 1:]
    if len(suffix) > 1 and suffix[0] in ('L', 'T') and suffix[1:].isdigit():
        return int(suffix[1:])
    if suffix.isdigit():
        return int(suffix)
    return None


def migrate_legacy_place_codes():
    """Переименовать legacy-коды в формат {зона}-L{n} / {зона}-T{n} и почистить служебные зоны."""
    from sqlalchemy import case

    from internal.models.coworking import Location
    from internal.layout.store import rename_place_in_layout
    from internal.models.location_zone import (
        build_location_prefix,
        is_amenity_zone_kind,
        parse_location_prefix,
    )
    from internal.models.place import Place
    from internal.layout.repository import LayoutRepository

    renamed = 0

    for loc in Location.query.all():
        floor_num, letter = parse_location_prefix(loc.code)
        norm = build_location_prefix(floor_num, _normalize_zone_letter(letter))
        if norm != loc.code and not Location.query.filter_by(code=norm).first():
            loc.code = norm
            renamed += 1

    layout = load_layout()
    layout_changed = False
    code_remap = {}
    for p in layout.get('places', []):
        loc = p.get('location')
        if loc:
            floor_num, letter = parse_location_prefix(loc)
            norm_loc = build_location_prefix(floor_num, _normalize_zone_letter(letter))
            if norm_loc != loc:
                p['location'] = norm_loc
                layout_changed = True
        code = p.get('code')
        if not code:
            continue
        floor_num, letter = parse_location_prefix(code)
        norm_prefix = build_location_prefix(floor_num, _normalize_zone_letter(letter))
        if code.startswith(norm_prefix + '-'):
            continue
        suffix = code.split('-', 1)[1] if '-' in code else ''
        new_code = f'{norm_prefix}-{suffix}' if suffix else norm_prefix
        if new_code != code:
            code_remap[code] = new_code
            p['code'] = new_code
            layout_changed = True
    if code_remap:
        for p in layout.get('places', []):
            pc = p.get('container_code')
            if pc in code_remap:
                p['container_code'] = code_remap[pc]
                layout_changed = True
        for old_code, new_code in code_remap.items():
            place = Place.query.filter_by(code=old_code).first()
            if place and not Place.query.filter_by(code=new_code).first():
                place.code = new_code
                renamed += 1

    places = Place.query.order_by(
        case((Place.kind.in_(('space', 'room')), 0), else_=1),
        Place.code,
    ).all()
    for place in places:
        loc_code = place.location.code if place.location else None
        if not loc_code:
            floor_num, letter = parse_location_prefix(place.code)
            loc_code = build_location_prefix(floor_num, _normalize_zone_letter(letter))
        if _has_modern_place_code(place.code, loc_code):
            continue
        tag = _code_tag_for_kind(place.kind)
        num = _legacy_place_suffix_number(place.code, loc_code)
        if num is None:
            existing = {p.code for p in Place.query.filter(Place.code.like(f'{loc_code}-%')).all()}
            layout_codes = {lp['code'] for lp in layout.get('places', []) if lp.get('code', '').startswith(loc_code + '-')}
            existing |= layout_codes
            num = _max_place_code_index(loc_code, tag, existing) + 1
        new_code = f'{loc_code}-{tag}{num}'
        if new_code == place.code:
            continue
        if Place.query.filter_by(code=new_code).first():
            new_code = generate_place_code(place.kind, loc_code)
        if rename_place_in_layout(place.code, new_code):
            place.code = new_code
            db.session.commit()
            renamed += 1
            layout = load_layout()

    layout = load_layout()
    for place in list(Place.query.filter(Place.kind.in_(('space', 'room'))).all()):
        zone_kind = place.location.zone_type.kind if place.location and place.location.zone_type else None
        if zone_kind and is_amenity_zone_kind(zone_kind):
            from internal.models.booking import Booking
            Booking.query.filter_by(place_id=place.id).delete()
            db.session.delete(place)
            renamed += 1
            for p in layout.get('places', []):
                if p.get('code') == place.code:
                    p['bookable'] = False
                    p.pop('category_id', None)
                    layout_changed = True
            continue
        is_meeting = (
            zone_kind == 'room_zone'
            or (place.category and place.category.kind == 'room')
        )
        if is_meeting:
            for p in list(layout.get('places', [])):
                if p.get('container_code') == place.code and p.get('kind') == 'desk':
                    cc = p['code']
                    cp = Place.query.filter_by(code=cc).first()
                    if cp:
                        db.session.delete(cp)
                    layout['places'] = [lp for lp in layout['places'] if lp.get('code') != cc]
                    renamed += 1
                    layout_changed = True

    if layout_changed:
        with open(paths.LAYOUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        reload_layout()
    db.session.commit()
    return renamed
