"""Сервис редактора: регистрация локаций и применение вариантов."""
import json
import threading

from sqlalchemy.exc import IntegrityError

from internal import models
from internal.models import Place, PlaceCategory, db
from internal.models.geometry import location_overlap_conflicts
from internal.models.location_zone import LocationZoneType, is_amenity_zone_kind
from internal.layout.repository import LayoutRepository
from internal.repositories.place_repository import PlaceRepository
from internal.utils.paths import LAYOUT_PATH
from internal.utils.room_geometry import (
    DESK_GAP_PX,
    DOOR_CLEARANCE_PX,
    WALL_CLEARANCE_PX,
    WALL_MARGIN_PX,
    compute_desk_positions,
    pack_desks_fill,
    pack_desks_greedy,
    pack_desks_random,
)

_APPLY_VARIANT_LOCKS = {}
_APPLY_VARIANT_GUARD = threading.Lock()


def _apply_variant_lock(container_code):
    with _APPLY_VARIANT_GUARD:
        lock = _APPLY_VARIANT_LOCKS.get(container_code)
        if lock is None:
            lock = threading.Lock()
            _APPLY_VARIANT_LOCKS[container_code] = lock
    return lock


def _merge_contained_locations(new_code, x, y, width, height, floor):
    """Поглотить меньшие локации, целиком попавшие внутрь новой."""
    layout = LayoutRepository.load()
    places = layout.get('places', [])
    _, absorbed = location_overlap_conflicts(
        places, new_code, x, y, width, height, int(floor),
    )
    if not absorbed:
        return []

    new_place = PlaceRepository.get_by_code(new_code)
    if not new_place:
        return []

    merged = []
    for old in absorbed:
        old_code = old.get('code')
        if not old_code:
            continue
        for p in places:
            if p.get('container_code') == old_code:
                p['container_code'] = new_code
        old_place = PlaceRepository.get_by_code(old_code)
        if old_place:
            for child in list(old_place.get_child_places()):
                child.container_code = new_place.code
                for p in places:
                    if p.get('code') == child.code:
                        p['container_code'] = new_code
            db.session.delete(old_place)
        merged.append(old_code)

    if merged:
        layout['places'] = [p for p in places if p.get('code') not in merged]
        with open(LAYOUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        models.reload_layout()
    return merged


def _create_space_from_payload(data, source='walls'):
    """Создать space в БД + layout."""
    floor_num = int(data['floor'])
    zone_type_id = data.get('zone_type_id')
    place_kind = 'space'

    zone = LocationZoneType.query.get(int(zone_type_id)) if zone_type_id else None
    is_amenity = zone and is_amenity_zone_kind(zone.kind)

    if zone_type_id:
        location = models.ensure_location_for_zone(floor_num, int(zone_type_id))
        if not location:
            return False, 'Зона локации не найдена', None
        location_code = location.code
    else:
        location_code = data.get('location_code') or models.default_location_code_for_floor(floor_num)
        location = models.Location.query.filter_by(code=location_code).first()
        if not location:
            return False, f'Локация {location_code} не найдена', None

    layout_places = LayoutRepository.load().get('places', [])
    conflicts, _ = location_overlap_conflicts(
        layout_places, None,
        data['x'], data['y'], data['width'], data['height'], floor_num,
    )
    if conflicts:
        other = conflicts[0]
        return False, (
            f'Частичное пересечение с «{other.get("name", other.get("code", "?"))}». '
            'Уменьшите контур или зарегистрируйте как открытую зону коридора.'
        ), None

    walls = LayoutRepository.load_walls()
    enclosed = bool(data.get('enclosed', True)) and not is_amenity
    allow_wall = data.get('source') == 'walls' or enclosed
    ax, ay, err = models.validate_place_rect(
        data['x'], data['y'], data['width'], data['height'], walls, floor_num,
        allow_wall_contact=allow_wall,
    )
    if err:
        return False, err, None

    category_id = data.get('category_id')
    if is_amenity:
        category_id = None
    floor_obj = models.Floor.query.filter_by(number=floor_num).first()
    floor_id = floor_obj.id if floor_obj else location.floor_id

    if is_amenity:
        for _ in range(5):
            code = PlaceRepository.generate_code(place_kind, location_code)
            place_dict = {
                'code': code,
                'name': data['name'],
                'location': location_code,
                'kind': place_kind,
                'x': int(ax),
                'y': int(ay),
                'width': int(data['width']),
                'height': int(data['height']),
                'rotation': 0,
                'floor': floor_num,
                'enclosed': enclosed,
                'bookable': False,
                'source': source,
            }
            if zone_type_id:
                place_dict['zone_type_id'] = int(zone_type_id)
            try:
                LayoutRepository.add_place(place_dict)
                if enclosed and source != 'walls':
                    models.create_walls_around_rect(
                        int(ax), int(ay), int(data['width']), int(data['height']), floor_num,
                    )
                merged = _merge_contained_locations(
                    code, int(ax), int(ay), int(data['width']), int(data['height']), floor_num,
                )
                result = {
                    'code': code,
                    'name': data['name'],
                    'kind': place_kind,
                    'location_code': location_code,
                    'floor': floor_num,
                    'is_amenity': True,
                    'in_db': False,
                    'bookable': False,
                }
                if merged:
                    result['merged_locations'] = merged
                return True, None, result
            except Exception as e:
                return False, str(e), None
        return False, 'Не удалось создать служебную зону', None

    for _ in range(5):
        code = None
        layout_written = False
        try:
            code = PlaceRepository.generate_code(place_kind, location_code)
            place = Place(
                code=code,
                name=data['name'],
                kind=place_kind,
                location_id=location.id,
                floor_id=floor_id,
                status='free',
                active=True,
                category_id=int(category_id) if category_id else None,
                enclosed=enclosed,
            )
            db.session.add(place)
            db.session.flush()

            place_dict = {
                'code': code,
                'name': data['name'],
                'location': location_code,
                'kind': place_kind,
                'x': int(ax),
                'y': int(ay),
                'width': int(data['width']),
                'height': int(data['height']),
                'rotation': 0,
                'floor': floor_num,
                'enclosed': enclosed,
                'bookable': not is_amenity,
                'source': source,
            }
            if zone_type_id:
                place_dict['zone_type_id'] = int(zone_type_id)
            if category_id:
                place_dict['category_id'] = int(category_id)
            LayoutRepository.add_place(place_dict)
            layout_written = True
            if enclosed and source != 'walls':
                models.create_walls_around_rect(
                    int(ax), int(ay), int(data['width']), int(data['height']), floor_num,
                )
            merged = _merge_contained_locations(
                code, int(ax), int(ay), int(data['width']), int(data['height']), floor_num,
            )
            db.session.commit()
            models.ensure_place_parent_links()
            result = place.to_dict()
            if merged:
                result['merged_locations'] = merged
            return True, None, result
        except IntegrityError:
            db.session.rollback()
            if layout_written and code:
                models.remove_place_from_layout(code)
            continue
        except Exception as e:
            db.session.rollback()
            if layout_written and code:
                models.remove_place_from_layout(code)
            return False, str(e), None
    return False, 'Не удалось создать локацию', None


def register_wall_room(data):
    required = ('name', 'x', 'y', 'width', 'height', 'floor', 'zone_type_id')
    for f in required:
        if f not in data:
            return False, f'Отсутствует поле: {f}', None
    return _create_space_from_payload(data, source='walls')


def _delete_child_desks(container_code):
    layout = models.load_layout()
    child_codes = [
        p['code'] for p in layout.get('places', [])
        if p.get('container_code') == container_code and p.get('kind') == 'desk'
    ]
    for code in child_codes:
        place = PlaceRepository.get_by_code(code)
        if place:
            PlaceRepository.deactivate_from_map(place)
        LayoutRepository.remove_place(code)
    db.session.commit()


def apply_variant(place_code, variant_data):
    place = PlaceRepository.sync_by_code(place_code)
    if not place or not place.is_container():
        return False, 'Локация не найдена', None

    geom = models.get_place_geometry(place.code)
    room = {
        'x': geom['x'], 'y': geom['y'],
        'width': geom['width'], 'height': geom['height'],
        'floor': geom.get('floor', 1),
    }
    vtype = variant_data.get('variant_type')

    zone_kind = None
    if place.location and place.location.zone_type:
        zone_kind = place.location.zone_type.kind
    if zone_kind and is_amenity_zone_kind(zone_kind):
        return False, 'Служебная зона – переговорные и столы недоступны', None

    if vtype == 'meeting':
        cat_id = variant_data.get('category_id')
        cat = PlaceCategory.query.get(cat_id) if cat_id else None
        if not cat or cat.kind != 'room':
            return False, 'Нужна категория переговорной', None
        if zone_kind and zone_kind != 'room_zone':
            from internal.models import LocationZoneType
            from internal.models.location_zone import ROOM_ZONE_KIND
            from internal.models.sync import apply_place_location_zone

            room_zone = LocationZoneType.query.filter_by(
                kind=ROOM_ZONE_KIND, active=True,
            ).order_by(LocationZoneType.letter).first()
            if not room_zone:
                return False, 'Не настроена зона переговорных', None
            floor_num = int(place.floor.number if place.floor else geom.get('floor', 1))
            ok, err, _ = apply_place_location_zone(place, floor_num, room_zone.id)
            if not ok:
                return False, err or 'Не удалось переключить зону на переговорную', None
            db.session.refresh(place)
            if place.location and place.location.zone_type:
                zone_kind = place.location.zone_type.kind
        if zone_kind and zone_kind != 'room_zone' and not place.is_meeting_room():
            return False, 'Переговорную можно назначить только в зоне переговорных', None
        if variant_data.get('clear_existing', True):
            _delete_child_desks(place.code)
        place.category_id = cat.id
        # Для переговорной имя всегда синхронизируем с выбранным типом
        place.name = cat.name
        LayoutRepository.save_place_category(place.code, cat.id)
        layout = models.load_layout()
        for p in layout.get('places', []):
            if p.get('code') == place.code:
                p['name'] = place.name
                break
        with open(LAYOUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        models.reload_layout()
        db.session.commit()
        models.ensure_place_parent_links()
        return True, None, {'place': place.to_dict(), 'furniture_desks': 0}

    if vtype == 'desks':
        if not models.place_allows_child_desks(place):
            zone_name = place.location.zone_type.name if place.location and place.location.zone_type else None
            if zone_name:
                return False, f'В «{zone_name}» нельзя добавлять столы', None
            return False, 'В этой локации нельзя добавлять столы', None

        cols = int(variant_data.get('cols', 0))
        rows = int(variant_data.get('rows', 0))
        is_mixed = bool(variant_data.get('mixed'))
        cat_id = variant_data.get('category_id')
        default_cat = PlaceCategory.query.get(cat_id) if cat_id else None
        raw_positions = variant_data.get('positions')
        if not is_mixed and not default_cat:
            return False, 'Некорректный вариант столов', None
        if is_mixed and not raw_positions:
            return False, 'Некорректный вариант столов', None

        tw = default_cat.get_width_px() if default_cat else 0
        th = default_cat.get_height_px() if default_cat else 0
        margin = int(variant_data.get('margin', WALL_CLEARANCE_PX))
        gap = int(variant_data.get('gap', DESK_GAP_PX))
        door_margin = int(variant_data.get('door_margin', DOOR_CLEARANCE_PX))
        rotation = int(variant_data.get('desk_rotation', 0))

        if raw_positions:
            positions = []
            for p in raw_positions:
                pos_cat_id = p.get('category_id', cat_id)
                pos_cat = PlaceCategory.query.get(pos_cat_id) if pos_cat_id else default_cat
                if not pos_cat:
                    continue
                pw = int(p.get('width', pos_cat.get_width_px()))
                ph = int(p.get('height', pos_cat.get_height_px()))
                positions.append({
                    'x': room['x'] + int(p['x']),
                    'y': room['y'] + int(p['y']),
                    'width': pw,
                    'height': ph,
                    'rotation': int(p.get('rotation', rotation)),
                    'category_id': pos_cat_id,
                })
        elif default_cat and cols >= 1 and rows >= 1:
            packed = pack_desks_fill(
                room['width'], room['height'], tw, th, default_cat.id,
                gap=gap, margin=margin,
            )
            positions = [{
                **p,
                'x': room['x'] + p['x'],
                'y': room['y'] + p['y'],
                'category_id': default_cat.id,
            } for p in packed]
        elif default_cat:
            packed = pack_desks_fill(
                room['width'], room['height'], tw, th, default_cat.id,
                gap=gap, margin=margin,
            )
            positions = [{
                **p,
                'x': room['x'] + p['x'],
                'y': room['y'] + p['y'],
                'category_id': default_cat.id,
            } for p in packed]
        else:
            return False, 'Некорректный вариант столов', None

        if not positions:
            return False, 'В помещении нет места для столов', None

        lock = _apply_variant_lock(place.code)
        if not lock.acquire(blocking=False):
            return False, 'Размещение уже выполняется — подождите пару секунд', None
        try:
            if variant_data.get('clear_existing', True):
                _delete_child_desks(place.code)
            return _apply_desk_variant(place, room, variant_data, positions, cat_id, rotation)
        finally:
            lock.release()

    return False, 'Неизвестный тип варианта', None


def _apply_desk_variant(place, room, variant_data, positions, cat_id, rotation):
    layout_places = LayoutRepository.load().get('places', [])
    parent_meta = models.get_layout_place_meta(place.code) or {}
    wall_bound_parent = (
        parent_meta.get('source') == 'walls'
        and parent_meta.get('enclosed', True) is not False
    )
    floor_num = int(room['floor'])
    layout_batch = []
    desk_rows = []
    reserved_codes = set()

    for pos in positions:
        pos_cat = PlaceCategory.query.get(pos.get('category_id') or cat_id)
        if not pos_cat:
            continue
        pw = int(pos.get('width', pos_cat.get_width_px()))
        ph = int(pos.get('height', pos_cat.get_height_px()))
        pos_rot = int(pos.get('rotation', rotation))
        from internal.layout.geometry import (
            clamp_rect_in_parent_rotated,
            find_place_overlap,
        )
        ax, ay = float(pos['x']), float(pos['y'])
        is_enclosed = parent_meta.get('enclosed', True) is not False
        if is_enclosed or wall_bound_parent:
            clamped = clamp_rect_in_parent_rotated(
                ax, ay, pw, ph, pos_rot,
                room['x'], room['y'], room['width'], room['height'],
            )
            if clamped[0] is None:
                continue
            ax, ay = clamped
        else:
            walls = LayoutRepository.load_walls()
            ax, ay, err = models.validate_place_rect(
                ax, ay, pw, ph, walls, floor_num,
            )
            if err:
                continue
        overlap_err = find_place_overlap(
            layout_places, None, ax, ay, pw, ph,
            floor_num, 'desk', place.code, rotation=pos_rot,
        )
        if overlap_err:
            continue

        code = None
        for _ in range(8):
            candidate = models.generate_place_code('desk', place.location.code)
            if candidate in reserved_codes:
                continue
            reserved_codes.add(candidate)
            code = candidate
            break
        if not code:
            continue

        layout_row = {
            'code': code,
            'name': pos_cat.name,
            'location': place.location.code,
            'kind': 'desk',
            'x': ax, 'y': ay,
            'width': pw, 'height': ph,
            'rotation': int(pos.get('rotation', 0)),
            'floor': floor_num,
            'container_code': place.code,
            'category_id': pos_cat.id,
        }
        layout_batch.append(layout_row)
        layout_places.append({
            'code': code, 'x': ax, 'y': ay,
            'width': pw, 'height': ph,
            'floor': floor_num, 'kind': 'desk',
            'rotation': pos_rot,
        })
        desk_rows.append(Place(
            code=code,
            name=pos_cat.name,
            kind='desk',
            location_id=place.location_id,
            floor_id=place.floor_id,
            category_id=pos_cat.id,
            container_code=place.code,
            status='free',
            active=True,
        ))

    if not layout_batch:
        return False, 'Не удалось разместить столы в помещении', None

    try:
        for desk in desk_rows:
            db.session.add(desk)
        db.session.flush()
        LayoutRepository.replace_container_desks(place.code, layout_batch)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return False, 'Конфликт кодов столов — попробуйте ещё раз', None
    except Exception:
        db.session.rollback()
        raise

    models.ensure_place_parent_links()
    return True, None, {
        'created': len(layout_batch),
        'place': place.to_dict(),
    }
