"""API редактора: комнаты по стенам, варианты, регистрация локаций."""

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from internal import models
from internal.models.category import is_desk_template_category
from internal.models import PlaceCategory
from internal.layout.repository import LayoutRepository
from internal.repositories.place_repository import PlaceRepository
from internal.services.room_editor_service import apply_variant, register_wall_room
from internal.utils.room_geometry import (
    desk_grid_variants,
    dismiss_draft_room,
    link_rooms_with_places,
    meeting_fit_variants,
    detect_all_wall_rooms,
)

room_editor_bp = Blueprint('room_editor_api', __name__)


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
    return jsonify({'success': True, 'place': place, 'message': 'Локация зарегистрирована'}), 201


@room_editor_bp.route('/api/admin/room/<path:code>/variants', methods=['GET'])
def api_room_variants(code):
    place = PlaceRepository.sync_by_code(code)
    if not place:
        return jsonify({'success': False, 'error': 'Локация не найдена'}), 404

    geom = models.get_place_geometry(place.code)
    rw, rh = geom['width'], geom['height']
    cats = [c.to_dict() for c in PlaceCategory.query.filter_by(active=True).all()]

    from internal.models.location_zone import is_amenity_zone_kind

    zone_kind = None
    if place.location and place.location.zone_type:
        zone_kind = place.location.zone_type.kind

    if zone_kind and is_amenity_zone_kind(zone_kind):
        return jsonify({
            'success': True,
            'mode': 'amenity',
            'variants': [{
                'variant_type': 'amenity',
                'title': place.location.zone_type.name,
                'description': 'Служебная зона – без бронирования и столов',
            }],
        })

    is_meeting = place.is_meeting_room() or zone_kind == 'room_zone'
    if is_meeting:
        room_cats = [c for c in cats if c.get('kind') == 'room']
        variants = meeting_fit_variants(rw, rh, room_cats)
        mode = 'meeting'
    else:
        desk_cats = [c for c in cats if is_desk_template_category(c)]
        variants = desk_grid_variants(rw, rh, desk_cats)
        mode = 'desks'

    return jsonify({
        'success': True,
        'mode': mode,
        'variants': variants,
        'room': {'code': place.code, 'width': rw, 'height': rh},
    })


@room_editor_bp.route('/api/admin/room/<path:code>/variants', methods=['POST'])
def api_apply_room_variant(code):
    data = request.get_json(silent=True) or {}
    ok, err, result = apply_variant(code, data)
    if not ok:
        return jsonify({'success': False, 'error': err}), 400
    return jsonify({'success': True, 'result': result})


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
    from internal.models.location_zone import is_amenity_zone_kind

    zone = LocationZoneType.query.get(zone_type_id) if zone_type_id else None
    is_desk = zone and zone.kind == 'desk_zone'
    is_amenity = zone and is_amenity_zone_kind(zone.kind)

    if is_amenity:
        return jsonify({
            'success': True,
            'mode': 'amenity',
            'variants': [{
                'variant_type': 'amenity',
                'title': zone.name,
                'description': 'Служебная зона – без бронирования и столов',
            }],
        })
    if is_desk:
        variants = desk_grid_variants(
            rw, rh, [c for c in cats if is_desk_template_category(c)],
        )
        mode = 'desks'
    else:
        variants = meeting_fit_variants(rw, rh, [c for c in cats if c.get('kind') == 'room'])
        mode = 'meeting'

    return jsonify({'success': True, 'mode': mode, 'variants': variants})


@room_editor_bp.route('/api/admin/room/dismiss-draft', methods=['POST'])
def api_dismiss_draft_room():
    """Убрать черновик комнаты: стены только этой ячейки + скрытие с карты."""
    data = request.get_json(silent=True) or {}
    x, y = data.get('x'), data.get('y')
    width, height = data.get('width'), data.get('height')
    floor = int(data.get('floor', 1))
    if x is None or y is None or not width or not height:
        return jsonify({'success': False, 'error': 'Укажите x, y, width, height'}), 400
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
        return jsonify({'success': True, 'message': msg, **result})
    except PermissionError as e:
        return jsonify({'success': False, 'error': str(e)}), 403
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


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
    return jsonify({'success': True, 'message': 'Зона снова отображается на карте'})
