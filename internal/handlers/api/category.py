"""API категорий мест, привязки категорий к местам и тарифов."""

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from internal.models import CategoryTariff, PlaceCategory, db
from internal.layout.repository import LayoutRepository
from internal.repositories.place_repository import PlaceRepository
from internal.utils.errors import user_error_message

VALID_CATEGORY_KINDS = frozenset({'desk', 'room'})

category_bp = Blueprint('category_api', __name__)


def _validate_category_kind(kind):
    if kind not in VALID_CATEGORY_KINDS:
        return f'Допустимые типы категории: desk (стол), room (переговорная)'
    return None


@category_bp.before_request
@login_required
def require_admin_api():
    if not current_user.is_admin():
        return jsonify({
            'success': False,
            'error': 'Доступ запрещен. Требуются права администратора.',
        }), 403


def _parse_category_id(raw):
    if raw is None or raw == '':
        return None
    return int(raw)


def _place_category_payload(place):
    cat = place.category
    return {
        'id': place.id,
        'code': place.code,
        'name': place.name,
        'kind': place.kind,
        'category': {
            'id': cat.id,
            'name': cat.name,
            'capacity': cat.capacity,
        } if cat else None,
    }


def _apply_place_category(place, category_id):
    """Назначить категорию месту в БД и layout.json."""
    from internal.models.location_zone import is_amenity_zone_kind

    parsed_id = _parse_category_id(category_id)
    if parsed_id:
        category = PlaceCategory.query.get(parsed_id)
        if not category:
            return False, 'Категория не найдена'
        zone_kind = None
        if place.location and place.location.zone_type:
            zone_kind = place.location.zone_type.kind
        if place.kind == 'desk' and category.kind != 'desk':
            return False, 'Тип категории не совпадает с типом места'
        if place.kind in ('room', 'space') and category.kind != 'room':
            return False, 'Помещению можно назначить только категорию переговорной'
        if place.kind not in ('desk', 'room', 'space'):
            return False, 'Категории назначаются только рабочим столам и переговорным'
        if category.kind == 'room':
            if zone_kind and is_amenity_zone_kind(zone_kind):
                return False, 'Служебной зоне нельзя назначить переговорную'
        place.category_id = parsed_id
    else:
        place.category_id = None
        parsed_id = None

    try:
        LayoutRepository.save_place_category(place.code, parsed_id)
    except Exception:
        pass

    db.session.commit()
    db.session.refresh(place)
    return True, None


def _enrich_category(cat):
    """Добавить коды мест, размеры из layout и подписи для админки."""
    import re
    from internal.models import Place
    from internal.models.category import PlaceCategory
    from internal.models.layout import get_place_geometry

    data = cat.to_dict()
    places = Place.query.filter(
        Place.category_id == cat.id,
        Place.kind.in_(['desk', 'room']),
    ).order_by(Place.code).all()
    data['place_codes'] = [p.code for p in places if p.active]
    data['location_codes'] = sorted({
        p.location.code for p in places if p.location and p.location.code
    })
    data['places_count'] = len(data['place_codes'])
    data['floor_numbers'] = sorted({
        p.floor.number for p in places if p.floor and p.floor.number is not None
    })
    data['floor_labels'] = [f'{n}-й этаж' for n in data['floor_numbers']]

    places_detail = []
    for p in places:
        geom = get_place_geometry(p.code) or {}
        w_px = float(geom.get('width') or 0)
        h_px = float(geom.get('height') or 0)
        w_m = round(w_px / PlaceCategory.SCALE_FACTOR, 2) if w_px else 0
        h_m = round(h_px / PlaceCategory.SCALE_FACTOR, 2) if h_px else 0
        size_label = f'{w_m}×{h_m} м' if w_m and h_m else '–'
        places_detail.append({
            'code': p.code,
            'name': p.name,
            'width_m': w_m,
            'height_m': h_m,
            'size_label': size_label,
        })
    data['places_detail'] = places_detail

    seat_m = re.search(r'·\s*(\d+)\s*мест', cat.name or '')
    if seat_m:
        data['seat_count_display'] = int(seat_m.group(1))
    elif cat.description and 'рабочих мест' in (cat.description or ''):
        dm = re.search(r'(\d+)', cat.description)
        data['seat_count_display'] = int(dm.group(1)) if dm else cat.capacity
    else:
        data['seat_count_display'] = cat.capacity

    if places_detail:
        from collections import Counter
        size_counts = Counter(
            d['size_label'] for d in places_detail if d['size_label'] != '–'
        )
        if len(size_counts) == 1:
            data['display_size_m'] = next(iter(size_counts))
        elif size_counts:
            parts = [f'{sz} ({cnt} шт.)' for sz, cnt in size_counts.most_common(3)]
            data['display_size_m'] = ', '.join(parts)
            if len(size_counts) > 3:
                data['display_size_m'] += f' +{len(size_counts) - 3} вариантов'
        else:
            data['display_size_m'] = f'{cat.width_m}×{cat.height_m} м'
    else:
        data['display_size_m'] = f'{cat.width_m}×{cat.height_m} м'

    return data


def _is_auto_zone_category(cat) -> bool:
    from internal.models.category import is_auto_zone_category
    return is_auto_zone_category(cat)


@category_bp.route('/api/admin/categories', methods=['GET'])
def api_get_categories():
    """Список категорий (все, включая неактивные – для админки)."""
    try:
        categories = PlaceCategory.query.order_by(
            PlaceCategory.kind, PlaceCategory.capacity
        ).all()
        visible = [cat for cat in categories if not _is_auto_zone_category(cat)]
        return jsonify({
            'success': True,
            'categories': [_enrich_category(cat) for cat in visible],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': user_error_message(e)}), 500


@category_bp.route('/api/admin/categories', methods=['POST'])
def api_create_category():
    try:
        data = request.get_json(silent=True) or {}
        for field in ('name', 'kind', 'capacity'):
            if field not in data:
                return jsonify({'success': False, 'error': f'Отсутствует поле: {field}'}), 400

        kind_err = _validate_category_kind(data['kind'])
        if kind_err:
            return jsonify({'success': False, 'error': kind_err}), 400

        category = PlaceCategory(
            name=data['name'],
            kind=data['kind'],
            capacity=int(data['capacity']),
            description=data.get('description', ''),
            active=True,
            width_m=float(data.get('width_m', 1.0)),
            height_m=float(data.get('height_m', 0.75)),
        )
        db.session.add(category)
        db.session.commit()
        return jsonify({
            'success': True,
            'category': category.to_dict(),
            'message': f'Категория "{category.name}" создана',
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': user_error_message(e)}), 500


@category_bp.route('/api/admin/categories/<int:category_id>', methods=['PUT'])
def api_update_category(category_id):
    try:
        category = PlaceCategory.query.get_or_404(category_id)
        data = request.get_json(silent=True) or {}

        if 'name' in data:
            category.name = data['name']
        if 'kind' in data:
            kind_err = _validate_category_kind(data['kind'])
            if kind_err:
                return jsonify({'success': False, 'error': kind_err}), 400
            category.kind = data['kind']
        if 'capacity' in data:
            category.capacity = int(data['capacity'])
        if 'description' in data:
            category.description = data['description']
        if 'active' in data:
            category.active = bool(data['active'])
        if 'width_m' in data:
            category.width_m = float(data['width_m'])
        if 'height_m' in data:
            category.height_m = float(data['height_m'])

        db.session.commit()
        return jsonify({
            'success': True,
            'category': category.to_dict(),
            'message': f'Категория "{category.name}" обновлена',
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': user_error_message(e)}), 500


@category_bp.route('/api/admin/categories/<int:category_id>', methods=['DELETE'])
def api_delete_category(category_id):
    try:
        category = PlaceCategory.query.get_or_404(category_id)

        # Отвязываем места – зоны и столы остаются на карте без категории
        for place in list(category.places):
            place.category_id = None
            try:
                LayoutRepository.save_place_category(place.code, None)
            except Exception:
                pass

        name = category.name
        db.session.delete(category)  # тарифы удаляются cascade
        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Категория «{name}» удалена. Места сохранены без категории.',
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': user_error_message(e)}), 500


@category_bp.route('/api/admin/place/<int:place_id>/category', methods=['PUT'])
def api_set_place_category(place_id):
    try:
        place = PlaceRepository.get_by_id(place_id)
        if not place:
            return jsonify({'success': False, 'error': f'Место с ID {place_id} не найдено'}), 404

        data = request.get_json(silent=True) or {}
        ok, err = _apply_place_category(place, data.get('category_id'))
        if not ok:
            return jsonify({'success': False, 'error': err}), 404

        return jsonify({
            'success': True,
            'message': 'Категория места обновлена',
            'place': _place_category_payload(place),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': user_error_message(e)}), 500


@category_bp.route('/api/admin/place-by-code/<path:code>/category', methods=['PUT'])
def api_set_place_category_by_code(code):
    try:
        place = PlaceRepository.sync_by_code(code)
        if not place:
            return jsonify({'success': False, 'error': f'Место с кодом {code} не найдено'}), 404

        data = request.get_json(silent=True) or {}
        ok, err = _apply_place_category(place, data.get('category_id'))
        if not ok:
            return jsonify({'success': False, 'error': err}), 404

        return jsonify({
            'success': True,
            'message': 'Категория места обновлена',
            'place': _place_category_payload(place),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': user_error_message(e)}), 500


@category_bp.route('/api/admin/tariffs', methods=['GET'])
def api_get_tariffs():
    try:
        category_id = request.args.get('category_id')
        query = CategoryTariff.query
        if category_id:
            query = query.filter_by(category_id=category_id)
        tariffs = query.all()
        return jsonify({'success': True, 'tariffs': [t.to_dict() for t in tariffs]})
    except Exception as e:
        return jsonify({'success': False, 'error': user_error_message(e)}), 500


@category_bp.route('/api/admin/categories/<int:category_id>/available-tariff-types', methods=['GET'])
def api_get_available_tariff_types(category_id):
    try:
        PlaceCategory.query.get_or_404(category_id)
        existing_tariffs = CategoryTariff.query.filter_by(category_id=category_id).all()
        existing_types = {t.tariff_type for t in existing_tariffs}
        all_types = {'hourly', 'weekly', 'monthly'}
        return jsonify({
            'success': True,
            'available_types': list(all_types - existing_types),
            'existing_types': list(existing_types),
            'is_complete': len(existing_types) == 3,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': user_error_message(e)}), 500


@category_bp.route('/api/admin/categories/<int:category_id>/tariffs', methods=['POST'])
def api_create_category_tariff(category_id):
    try:
        PlaceCategory.query.get_or_404(category_id)
        data = request.get_json(silent=True) or {}
        tariff_type = data.get('tariff_type')
        price = data.get('price')

        if not tariff_type or tariff_type not in ('hourly', 'weekly', 'monthly'):
            return jsonify({'success': False, 'error': 'Неверный тип тарифа'}), 400
        if price is None or price < 0:
            return jsonify({'success': False, 'error': 'Неверная цена'}), 400

        existing = CategoryTariff.query.filter_by(
            category_id=category_id, tariff_type=tariff_type
        ).first()
        if existing:
            return jsonify({'success': False, 'error': 'Тариф этого типа уже существует'}), 400

        tariff = CategoryTariff(
            category_id=category_id,
            tariff_type=tariff_type,
            price=float(price),
            active=data.get('active', True),
        )
        db.session.add(tariff)
        db.session.commit()
        return jsonify({
            'success': True,
            'tariff': tariff.to_dict(),
            'message': f'{tariff.tariff_type_label} тариф добавлен',
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': user_error_message(e)}), 500


@category_bp.route('/api/admin/tariffs/<int:tariff_id>', methods=['PUT'])
def api_update_category_tariff(tariff_id):
    try:
        tariff = CategoryTariff.query.get_or_404(tariff_id)
        data = request.get_json(silent=True) or {}
        if 'price' in data:
            tariff.price = float(data['price'])
        if 'active' in data:
            tariff.active = bool(data['active'])
        db.session.commit()
        return jsonify({
            'success': True,
            'tariff': tariff.to_dict(),
            'message': 'Тариф обновлен',
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': user_error_message(e)}), 500


@category_bp.route('/api/admin/tariffs/<int:tariff_id>', methods=['DELETE'])
def api_delete_category_tariff(tariff_id):
    try:
        tariff = CategoryTariff.query.get_or_404(tariff_id)
        db.session.delete(tariff)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Тариф удален'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': user_error_message(e)}), 500
