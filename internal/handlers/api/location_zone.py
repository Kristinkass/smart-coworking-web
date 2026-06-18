"""API категорий зон локаций (А – столы, B – переговорные)."""

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from internal.models import LocationZoneType, db, get_layout_place_meta
from internal.models.sync import apply_place_location_zone
from internal.repositories.place_repository import PlaceRepository

location_zone_bp = Blueprint('location_zone_api', __name__)


@location_zone_bp.before_request
@login_required
def require_admin_api():
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403


@location_zone_bp.route('/api/admin/location-zones', methods=['GET'])
def api_get_location_zones():
    """Список зон. ?all=1 – включая архивные (для страницы управления)."""
    include_archived = request.args.get('all') in ('1', 'true', 'yes')
    query = LocationZoneType.query.order_by(LocationZoneType.letter)
    if not include_archived:
        query = query.filter_by(active=True)
    zones = query.all()
    return jsonify({
        'success': True,
        'zones': [z.to_dict() for z in zones],
    })


@location_zone_bp.route('/api/admin/location-zones', methods=['POST'])
def api_create_location_zone():
    data = request.get_json(silent=True) or {}
    for field in ('letter', 'name', 'kind'):
        if not data.get(field):
            return jsonify({'success': False, 'error': f'Поле {field} обязательно'}), 400

    letter = str(data['letter']).strip().upper()
    existing = LocationZoneType.query.filter_by(letter=letter).first()
    if existing:
        if existing.active:
            return jsonify({'success': False, 'error': f'Буква зоны «{letter}» уже занята'}), 400
        existing.name = data['name'].strip()
        existing.kind = data['kind']
        existing.description = data.get('description', '')
        existing.active = True
        db.session.commit()
        return jsonify({
            'success': True,
            'zone': existing.to_dict(),
            'message': f'Зона «{letter}» восстановлена из архива',
        }), 200

    zone = LocationZoneType(
        letter=letter,
        name=data['name'].strip(),
        kind=data['kind'],
        description=data.get('description', ''),
        active=True,
    )
    db.session.add(zone)
    db.session.commit()
    return jsonify({'success': True, 'zone': zone.to_dict()}), 201


@location_zone_bp.route('/api/admin/location-zones/<int:zone_id>', methods=['PUT'])
def api_update_location_zone(zone_id):
    zone = LocationZoneType.query.get_or_404(zone_id)
    data = request.get_json(silent=True) or {}
    if 'name' in data:
        zone.name = data['name']
    if 'kind' in data:
        zone.kind = data['kind']
    if 'description' in data:
        zone.description = data['description']
    if 'active' in data:
        zone.active = bool(data['active'])
    if 'letter' in data:
        new_letter = str(data['letter']).strip().upper()
        existing = LocationZoneType.query.filter_by(letter=new_letter).first()
        if existing and existing.id != zone.id:
            return jsonify({'success': False, 'error': 'Буква зоны уже занята'}), 400
        zone.letter = new_letter
    db.session.commit()
    return jsonify({'success': True, 'zone': zone.to_dict()})


@location_zone_bp.route('/api/admin/location-zones/<int:zone_id>/archive', methods=['POST'])
def api_archive_location_zone(zone_id):
    """Архивировать зону – нельзя назначать новым местам, у старых остаётся."""
    from internal.models.coworking import Location

    zone = LocationZoneType.query.get_or_404(zone_id)
    if not zone.active:
        return jsonify({'success': True, 'message': 'Зона уже в архиве', 'zone': zone.to_dict()})

    zone.active = False
    db.session.commit()
    linked = Location.query.filter_by(zone_type_id=zone.id).count()
    return jsonify({
        'success': True,
        'message': (
            f'Зона «{zone.letter}» архивирована'
            + (f' (используется в {linked} локациях)' if linked else '')
        ),
        'zone': zone.to_dict(),
    })


@location_zone_bp.route('/api/admin/location-zones/<int:zone_id>/unarchive', methods=['POST'])
def api_unarchive_location_zone(zone_id):
    """Разархивировать зону – снова доступна для новых мест."""
    zone = LocationZoneType.query.get_or_404(zone_id)
    zone.active = True
    db.session.commit()
    return jsonify({
        'success': True,
        'message': f'Зона «{zone.letter}» восстановлена',
        'zone': zone.to_dict(),
    })


@location_zone_bp.route('/api/admin/location-zones/<int:zone_id>', methods=['DELETE'])
def api_delete_location_zone(zone_id):
    """Устаревший маршрут: всегда архивирует, не удаляет."""
    return api_archive_location_zone(zone_id)


def _apply_zone_to_place(place, zone_type_id, floor_num):
    zone = LocationZoneType.query.get(int(zone_type_id))
    if not zone:
        return False, 'Зона локации не найдена', None
    if not zone.active:
        return False, 'Архивная зона недоступна для новых мест. Выберите активную зону.', None

    ok, err, meta = apply_place_location_zone(place, floor_num, zone_type_id)
    if not ok:
        return False, err, None
    return True, None, meta


@location_zone_bp.route('/api/admin/place/<int:place_id>/location-zone', methods=['PUT'])
def api_set_place_location_zone(place_id):
    data = request.get_json(silent=True) or {}
    zone_type_id = data.get('zone_type_id')
    if not zone_type_id:
        return jsonify({'success': False, 'error': 'Укажите тип зоны'}), 400

    place = PlaceRepository.get_or_404(place_id)
    floor_num = int(data.get('floor') or (place.floor.number if place.floor else 1))
    ok, err, rename_meta = _apply_zone_to_place(place, int(zone_type_id), floor_num)
    if not ok:
        return jsonify({'success': False, 'error': err}), 400

    db.session.refresh(place)
    layout_meta = get_layout_place_meta(place.code)
    zone = LocationZoneType.query.get(int(zone_type_id))
    msg = 'Зона обновлена'
    if rename_meta and rename_meta.get('renamed'):
        msg = f'Код переименован: {rename_meta["old_code"]} → {rename_meta["code"]}'
    return jsonify({
        'success': True,
        'message': msg,
        'place': place.to_dict(),
        'zone_type_id': int(zone_type_id),
        'location_code': place.location.code if place.location else None,
        'code_hint': f'{floor_num}{zone.letter}-N' if zone else None,
        'layout_zone_type_id': layout_meta.get('zone_type_id'),
        'renamed': rename_meta.get('renamed') if rename_meta else False,
        'old_code': rename_meta.get('old_code') if rename_meta else None,
    })


@location_zone_bp.route('/api/admin/place-by-code/<path:code>/location-zone', methods=['PUT'])
def api_set_place_location_zone_by_code(code):
    data = request.get_json(silent=True) or {}
    zone_type_id = data.get('zone_type_id')
    if not zone_type_id:
        return jsonify({'success': False, 'error': 'Укажите тип зоны'}), 400

    place = PlaceRepository.sync_by_code(code)
    if not place:
        return jsonify({'success': False, 'error': 'Место не найдено'}), 404

    floor_num = int(data.get('floor') or (place.floor.number if place.floor else 1))
    ok, err, rename_meta = _apply_zone_to_place(place, int(zone_type_id), floor_num)
    if not ok:
        return jsonify({'success': False, 'error': err}), 400

    msg = 'Зона обновлена'
    if rename_meta and rename_meta.get('renamed'):
        msg = f'Код переименован: {rename_meta["old_code"]} → {rename_meta["code"]}'
    return jsonify({
        'success': True,
        'message': msg,
        'place': place.to_dict(),
        'location_code': place.location.code if place.location else None,
        'renamed': rename_meta.get('renamed') if rename_meta else False,
    })
