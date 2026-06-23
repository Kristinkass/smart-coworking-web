"""API редактора: комнаты по стенам, варианты, регистрация локаций."""

import copy
import json
import time

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from internal import models
from internal.models.category import is_desk_template_category
from internal.models import PlaceCategory
from internal.layout.repository import LayoutRepository
from internal.repositories.place_repository import PlaceRepository
from internal.services.room_editor_service import apply_variant, register_wall_room
from internal.utils.errors import user_error_message
from internal.utils.room_geometry import (
    desk_grid_variants,
    dismiss_draft_room,
    link_rooms_with_places,
    meeting_fit_variants,
    detect_all_wall_rooms,
)

room_editor_bp = Blueprint('room_editor_api', __name__)

_VARIANT_CACHE = {}
_VARIANT_CACHE_TTL = 25


def _variant_cache_get(key):
    item = _VARIANT_CACHE.get(key)
    if not item:
        return None
    ts, payload = item
    if time.monotonic() - ts > _VARIANT_CACHE_TTL:
        _VARIANT_CACHE.pop(key, None)
        return None
    return copy.deepcopy(payload)


def _variant_cache_set(key, payload):
    if len(_VARIANT_CACHE) > 80:
        _VARIANT_CACHE.clear()
    _VARIANT_CACHE[key] = (time.monotonic(), copy.deepcopy(payload))


def _variant_cache_clear():
    _VARIANT_CACHE.clear()


def _resolve_zone_kind(place, zone_type_id=None):
    """Тип зоны для вариантов: из запроса, БД или layout.json."""
    from internal.models import LocationZoneType
    from internal.models.location_zone import DESK_ZONE_KIND

    if zone_type_id:
        zt = LocationZoneType.query.get(int(zone_type_id))
        if zt:
            return zt.kind, zt.name
    if place and place.location and place.location.zone_type:
        return place.location.zone_type.kind, place.location.zone_type.name
    code = place.code if place else None
    if code:
        meta = models.get_layout_place_meta(code) or {}
        ztid = meta.get('zone_type_id')
        if ztid:
            zt = LocationZoneType.query.get(int(ztid))
            if zt:
                return zt.kind, zt.name
    return DESK_ZONE_KIND, 'Зона столов'


def _build_room_variants(rw, rh, room, floor_walls, floor_doors, zone_kind, zone_name=None):
    from internal.models.location_zone import is_amenity_zone_kind, ROOM_ZONE_KIND

    cats = [c.to_dict() for c in PlaceCategory.query.filter_by(active=True).all()]
    if zone_kind and is_amenity_zone_kind(zone_kind):
        return 'amenity', [{
            'variant_type': 'amenity',
            'title': zone_name or 'Служебная зона',
            'description': 'Служебная зона – без бронирования и столов',
        }]
    if zone_kind == ROOM_ZONE_KIND:
        return 'meeting', meeting_fit_variants(
            rw, rh, [c for c in cats if c.get('kind') == 'room'],
        )
    variants = desk_grid_variants(
        rw, rh,
        [c for c in cats if is_desk_template_category(c)],
        room=room, doors=floor_doors, walls=floor_walls,
    )
    return 'desks', variants


@room_editor_bp.before_request
@login_required
def require_admin():
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403


def _format_editor_place(layout_place, db_place, floor):
    """Геометрия из layout.json, метаданные из БД (если есть)."""
    code = layout_place.get('code')
    entry = {
        'code': code,
        'name': layout_place.get('name'),
        'kind': layout_place.get('kind', 'desk'),
        'x': layout_place.get('x', 0),
        'y': layout_place.get('y', 0),
        'width': layout_place.get('width', 100),
        'height': layout_place.get('height', 100),
        'rotation': layout_place.get('rotation', 0),
        'floor': floor,
        'container_code': layout_place.get('container_code'),
        'enclosed': layout_place.get('enclosed', False),
        'bookable': layout_place.get('bookable', True),
        'visual_only': bool(layout_place.get('visual_only')),
        'source': layout_place.get('source'),
        'zone_type_id': layout_place.get('zone_type_id'),
        'in_db': db_place is not None,
    }
    if not db_place:
        return entry

    loc = db_place.location
    zt = loc.zone_type.to_dict() if loc and loc.zone_type else None
    cat = db_place.category
    entry.update({
        'id': db_place.id,
        'zone_type_id': layout_place.get('zone_type_id') or (zt['id'] if zt else None),
        'zone_type': zt,
        'category': {
            'id': cat.id, 'name': cat.name, 'kind': cat.kind, 'capacity': cat.capacity,
        } if cat else None,
        'capacity': db_place.capacity,
        'allows_desks': db_place.allows_child_desks(),
        'is_meeting_room': db_place.is_meeting_room(),
        'is_container': db_place.is_container(),
        'allows_layout_items': models.place_allows_layout_items(db_place),
    })
    if db_place.is_container() and db_place.allows_child_desks():
        entry['zone_seat_capacity'] = sum(
            (c.capacity or 1) for c in db_place.get_child_places()
        )
    return entry


@room_editor_bp.route('/api/admin/editor/map', methods=['GET'])
def api_editor_map():
    """Быстрая загрузка редактора: геометрия из layout.json, мета из БД одним запросом."""
    floor = int(request.args.get('floor', 1))
    layout = LayoutRepository.load()
    layout_places = layout.get('places', [])
    walls = layout.get('walls', [])
    doors = layout.get('doors', [])

    floor_places = [p for p in layout_places if int(p.get('floor', 1)) == floor]
    db_map = PlaceRepository.get_by_codes([p.get('code') for p in floor_places])

    formatted = [
        _format_editor_place(p, db_map.get(p.get('code')), floor)
        for p in floor_places
    ]
    containers = [f for f in formatted if f.get('kind') in ('space', 'room')]
    floor_walls = [w for w in walls if int(w.get('floor', 1)) == floor]
    floor_doors = [d for d in doors if int(d.get('floor', 1)) == floor]
    from internal.layout.geometry import repair_wall_gaps
    from internal.layout.store import save_walls
    if repair_wall_gaps(walls, floor=floor):
        save_walls(walls)
        floor_walls = [w for w in walls if int(w.get('floor', 1)) == floor]
    rooms = link_rooms_with_places(detect_all_wall_rooms(floor_walls, floor), containers)

    return jsonify({
        'success': True,
        'places': formatted,
        'walls': floor_walls,
        'doors': floor_doors,
        'rooms': rooms,
    })


@room_editor_bp.route('/api/admin/rooms', methods=['GET'])
def api_get_rooms():
    """Обратная совместимость."""
    floor = int(request.args.get('floor', 1))
    layout = LayoutRepository.load()
    floor_places = [p for p in layout.get('places', []) if int(p.get('floor', 1)) == floor]
    db_map = PlaceRepository.get_by_codes([p.get('code') for p in floor_places])
    formatted = [_format_editor_place(p, db_map.get(p.get('code')), floor) for p in floor_places]
    containers = [f for f in formatted if f.get('kind') in ('space', 'room')]
    floor_walls = [w for w in layout.get('walls', []) if int(w.get('floor', 1)) == floor]
    rooms = link_rooms_with_places(detect_all_wall_rooms(floor_walls, floor), containers)
    return jsonify({'success': True, 'rooms': rooms, 'places': containers})


@room_editor_bp.route('/api/admin/room/register', methods=['POST'])
def api_register_room():
    data = request.get_json(silent=True) or {}
    ok, err, place = register_wall_room(data)
    if not ok:
        return jsonify({'success': False, 'error': err}), 400
    _variant_cache_clear()
    return jsonify({'success': True, 'place': place, 'message': 'Локация зарегистрирована'}), 201


@room_editor_bp.route('/api/admin/room/<path:code>/variants', methods=['GET'])
def api_room_variants(code):
    try:
        zone_type_id = request.args.get('zone_type_id', type=int)
        place = PlaceRepository.sync_by_code(code)
        layout_meta = models.get_layout_place_meta(code)
        if not place and not layout_meta:
            return jsonify({'success': False, 'error': 'Локация не найдена на карте'}), 404

        geom = models.get_place_geometry(code)
        rw, rh = geom['width'], geom['height']
        floor_num = int(geom.get('floor', 1))
        layout = LayoutRepository.load()
        floor_walls = [w for w in layout.get('walls', []) if int(w.get('floor', 1)) == floor_num]
        floor_doors = [d for d in layout.get('doors', []) if int(d.get('floor', 1)) == floor_num]
        room = {
            'x': geom['x'], 'y': geom['y'],
            'width': rw, 'height': rh, 'floor': floor_num,
        }

        zone_kind, zone_name = _resolve_zone_kind(place, zone_type_id)
        cache_key = ('room', code, rw, rh, zone_type_id or 0, zone_kind)
        cached = _variant_cache_get(cache_key)
        if cached:
            return jsonify(cached)
        mode, variants = _build_room_variants(
            rw, rh, room, floor_walls, floor_doors, zone_kind, zone_name,
        )

        payload = {
            'success': True,
            'mode': mode,
            'variants': variants,
            'room': {'code': code, 'width': rw, 'height': rh},
        }
        _variant_cache_set(cache_key, payload)
        return jsonify(payload)
    except json.JSONDecodeError:
        return jsonify({
            'success': False,
            'error': 'Файл планировки повреждён. Обратитесь к администратору или перезапустите сервер после восстановления layout.json',
        }), 500
    except Exception as e:
        return jsonify({'success': False, 'error': user_error_message(e)}), 500


@room_editor_bp.route('/api/admin/room/<path:code>/variants', methods=['POST'])
def api_apply_room_variant(code):
    try:
        data = request.get_json(silent=True) or {}
        ok, err, result = apply_variant(code, data)
        if not ok:
            return jsonify({'success': False, 'error': err}), 400
        _variant_cache_clear()
        return jsonify({'success': True, 'result': result})
    except json.JSONDecodeError:
        return jsonify({
            'success': False,
            'error': 'Файл планировки повреждён — не удалось сохранить столы',
        }), 500
    except Exception as e:
        return jsonify({'success': False, 'error': user_error_message(e)}), 500


@room_editor_bp.route('/api/admin/room/draft-variants', methods=['POST'])
def api_draft_variants():
    """Варианты для ещё не зарегистрированной комнаты."""
    data = request.get_json(silent=True) or {}
    rw = int(data.get('width', 0))
    rh = int(data.get('height', 0))
    zone_type_id = data.get('zone_type_id')
    if rw < 80 or rh < 80:
        return jsonify({'success': False, 'error': 'Комната слишком мала'}), 400

    cats = [c.to_dict() for c in PlaceCategory.query.filter_by(active=True).all()]
    from internal.models import LocationZoneType

    zone = LocationZoneType.query.get(zone_type_id) if zone_type_id else None
    zone_kind, zone_name = (zone.kind, zone.name) if zone else (None, None)
    if zone_kind:
        cache_key = ('draft', rw, rh, int(zone_type_id), zone_kind)
        cached = _variant_cache_get(cache_key)
        if cached:
            return jsonify(cached)
        mode, variants = _build_room_variants(rw, rh, None, [], [], zone_kind, zone_name)
        payload = {'success': True, 'mode': mode, 'variants': variants}
        _variant_cache_set(cache_key, payload)
        return jsonify(payload)

    return jsonify({'success': False, 'error': 'Укажите тип зоны'}), 400


@room_editor_bp.route('/api/admin/room/dismiss-draft', methods=['POST'])
def api_dismiss_draft_room():
    """Убрать черновик комнаты: стены только этой ячейки + скрытие с карты."""
    data = request.get_json(silent=True) or {}
    x, y = data.get('x'), data.get('y')
    width, height = data.get('width'), data.get('height')
    floor = int(data.get('floor', 1))
    if x is None or y is None or not width or not height:
        return jsonify({'success': False, 'error': 'Укажите координаты и размеры'}), 400
    try:
        result = dismiss_draft_room(
            x, y, width, height,
            floor=floor,
            room_key=data.get('room_key'),
            code=data.get('code'),
        )
        msg = 'Зона убрана с карты'
        if result.get('walls_removed'):
            msg += f' (стен: {result["walls_removed"]})'
        if result.get('layout_removed'):
            msg += f' · мест: {", ".join(result["layout_removed"])}'
        _variant_cache_clear()
        return jsonify({'success': True, 'message': msg, **result})
    except PermissionError as e:
        return jsonify({'success': False, 'error': user_error_message(e)}), 403
    except Exception as e:
        return jsonify({'success': False, 'error': user_error_message(e)}), 500


@room_editor_bp.route('/api/admin/room/restore-draft', methods=['POST'])
def api_restore_draft_room():
    """Вернуть детект зоны, скрытой через «Убрать зону»."""
    from internal.models.layout import remove_ignored_draft

    data = request.get_json(silent=True) or {}
    floor = int(data.get('floor', 1))
    removed = remove_ignored_draft(
        room_key=data.get('room_key'),
        x=data.get('x'),
        y=data.get('y'),
        width=data.get('width'),
        height=data.get('height'),
        floor=floor,
    )
    if not removed:
        return jsonify({'success': False, 'error': 'Скрытая зона не найдена'}), 404
    _variant_cache_clear()
    return jsonify({'success': True, 'message': 'Зона снова отображается на карте'})
