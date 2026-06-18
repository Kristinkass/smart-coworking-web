"""Сервис редактора: регистрация локаций и применение вариантов."""
import json

from sqlalchemy.exc import IntegrityError

from internal import models
from internal.models import Place, PlaceCategory, db
from internal.models.geometry import location_overlap_conflicts
from internal.models.location_zone import LocationZoneType, is_amenity_zone_kind
from internal.layout.repository import LayoutRepository
from internal.repositories.place_repository import PlaceRepository
from internal.utils.paths import LAYOUT_PATH
from internal.utils.room_geometry import compute_desk_positions


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
            return False, 'В переговорную нельзя добавлять столы', None
        if variant_data.get('clear_existing', True):
            _delete_child_desks(place.code)

        cols = int(variant_data.get('cols', 0))
        rows = int(variant_data.get('rows', 0))
        cat_id = int(variant_data.get('category_id'))
        cat = PlaceCategory.query.get(cat_id)
        if not cat or cols < 1 or rows < 1:
            return False, 'Некорректный вариант столов', None

        tw, th = cat.get_width_px(), cat.get_height_px()
        margin = int(variant_data.get('margin', 40))
        gap = int(variant_data.get('gap', 30))
        positions = compute_desk_positions(room, cols, rows, tw, th, margin, gap)
        walls = LayoutRepository.load_walls()
        created = 0
        floor_num = int(room['floor'])

        for pos in positions:
            ax, ay, err = models.validate_place_rect(
                pos['x'], pos['y'], tw, th, walls, floor_num,
            )
            if err:
                continue
            for _ in range(3):
                try:
                    code = models.generate_place_code('desk', place.location.code)
                    desk = Place(
                        code=code,
                        name=cat.name,
                        kind='desk',
                        location_id=place.location_id,
                        floor_id=place.floor_id,
                        category_id=cat.id,
                        container_code=place.code,
                        status='free',
                        active=True,
                    )
                    db.session.add(desk)
                    db.session.flush()
                    LayoutRepository.add_place({
                        'code': code,
                        'name': cat.name,
                        'location': place.location.code,
                        'kind': 'desk',
                        'x': ax, 'y': ay,
                        'width': tw, 'height': th,
                        'floor': floor_num,
                        'container_code': place.code,
                        'category_id': cat.id,
                    })
                    created += 1
                    break
                except IntegrityError:
                    db.session.rollback()
                    continue
        db.session.commit()
        models.ensure_place_parent_links()
        return True, None, {'created': created, 'place': place.to_dict()}

    return False, 'Неизвестный тип варианта', None
