"""Admin place editor API."""
from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from internal.handlers.deps import (
    BookingRepository, Place, UserRepository, admin_required, db, get_type_name, models, staff_required,
)
from internal.models.category import PlaceCategory
from internal.layout.geometry import (
    find_place_overlap,
    effective_rect_for_rotation,
    adjust_rect_from_walls_rotated,
    clamp_rect_in_parent_rotated,
    rect_overlaps_walls_rotated,
)
from internal.layout.repository import LayoutRepository
from internal.repositories.place_repository import PlaceRepository
from internal.utils.errors import user_error_message
from internal.utils.phone import normalize_phone


def _api_error(exc):
    """Сообщение об ошибке для API (без технического английского)."""
    return user_error_message(exc)


def _desk_blocked_message(container):
    """Человечный текст, если стол нельзя поместить в выбранную локацию."""
    zone_name = None
    if container and container.location and container.location.zone_type:
        zone_name = container.location.zone_type.name
        if container.location.zone_type.kind == 'room_zone':
            return 'В переговорную нельзя добавлять столы. Это единая локация для бронирования целиком.'
    if zone_name:
        return f'В «{zone_name}» нельзя размещать столы.'
    return 'В этой локации нельзя размещать столы.'


def _desk_center_in_rect(fx, fy, w, h, rx, ry, rw, rh):
    cx, cy = fx + w / 2, fy + h / 2
    return rx <= cx <= rx + rw and ry <= cy <= ry + rh


def _desk_target_container_code(layout_places, fx, fy, w, h, floor_num):
    """Контейнер под центром стола в новой позиции или ошибка для служебной зоны."""
    matches = []
    for lp in layout_places:
        if lp.get('kind') not in ('room', 'space'):
            continue
        if int(lp.get('floor', 1)) != int(floor_num):
            continue
        if not _desk_center_in_rect(
            fx, fy, w, h, lp['x'], lp['y'], lp['width'], lp['height'],
        ):
            continue
        matches.append((lp['width'] * lp['height'], lp))

    if not matches:
        return None, None

    matches.sort(key=lambda item: item[0])
    target = matches[0][1]
    container = PlaceRepository.sync_by_code(target.get('code'))
    if container and not container.allows_child_desks():
        return None, _desk_blocked_message(container)
    return target.get('code') if container else None, None


def _desk_effective_in_parent(fx, fy, w, h, rotation, rx, ry, rw, rh, inset=0):
    """Проверить, что повёрнутый стол целиком внутри родительской локации."""
    from internal.layout.geometry import effective_rect_for_rotation
    eff_x, eff_y, eff_w, eff_h = effective_rect_for_rotation(fx, fy, w, h, rotation)
    return (
        eff_x >= rx + inset
        and eff_y >= ry + inset
        and eff_x + eff_w <= rx + rw - inset
        and eff_y + eff_h <= ry + rh - inset
    )


def _validate_desk_geometry(code, x, y, width, height, rotation, floor_num, container_code=None):
    """Проверить размещение стола с учётом поворота."""
    walls = LayoutRepository.load_walls()
    layout_places = LayoutRepository.load().get('places', [])
    meta = models.get_layout_place_meta(code) if code else {}
    wall_bound_parent = False
    parent = None
    parent_meta = {}

    if container_code:
        parent = PlaceRepository.get_by_code(container_code)
        parent_meta = models.get_layout_place_meta(container_code) or {}
        wall_bound_parent = (
            parent_meta.get('source') == 'walls'
            and parent_meta.get('enclosed', True) is not False
        )

    ax, ay = float(x), float(y)
    if container_code and parent and parent_meta.get('enclosed', True) is not False:
        pg = models.get_place_geometry(container_code)
        if pg:
            clamped = clamp_rect_in_parent_rotated(
                ax, ay, width, height, rotation,
                pg['x'], pg['y'], pg['width'], pg['height'],
            )
            if clamped[0] is None:
                return None, None, 'Стол не помещается внутри локации'
            ax, ay = clamped
    elif not wall_bound_parent:
        ax, ay = adjust_rect_from_walls_rotated(
            ax, ay, width, height, rotation, walls, floor_num,
        )

    if not wall_bound_parent and rect_overlaps_walls_rotated(
        ax, ay, width, height, rotation, walls, floor_num,
    ):
        return None, None, 'Нельзя разместить на стене. Отодвиньте от границ.'

    overlap_err = find_place_overlap(
        layout_places, code, ax, ay, width, height,
        floor_num, 'desk', container_code, rotation=rotation,
    )
    if overlap_err:
        return None, None, overlap_err

    return ax, ay, None


def _suppress_zone_redetection(code):
    """После удаления зоны стены остаются – скрыть повторный черновик."""
    from internal.models.layout import add_ignored_draft
    from internal.utils.room_geometry import resolve_wall_room_for_geometry

    geom = models.get_place_geometry(code)
    if not geom:
        return
    room = resolve_wall_room_for_geometry(geom, int(geom.get('floor', 1)))
    add_ignored_draft(room or geom, int(geom.get('floor', 1)))


def _orphan_children_of_place(place):
    """Отвязать столы от удаляемой локации (layout + БД)."""
    if not place or place.kind not in ('space', 'room'):
        return
    from internal.utils import paths
    import json
    layout = models.load_layout()
    changed = False
    for lp in layout.get('places', []):
        if lp.get('container_code') == place.code:
            del lp['container_code']
            changed = True
    if changed:
        with open(paths.LAYOUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        models.reload_layout()
    for child in Place.query.filter_by(container_code=place.code).all():
        child.container_code = None
    db.session.flush()


def register_admin_place_routes(app):
    @app.route('/admin/places')
    @admin_required
    def admin_places():
        """Управление местами"""
        try:
            places = Place.query.order_by(models.Place.created_at.desc()).all()
            return render_template('admin/admin_places.html',
                                   places=places,
                                   get_type_name=get_type_name,
                                   get_status_name=get_status_name)
        except Exception as e:
            flash(f'Ошибка при загрузке мест: {_api_error(e)}', 'error')
            return redirect(url_for('admin_dashboard'))



    @app.route('/api/admin/place/<int:place_id>/toggle_maintenance', methods=['POST'])
    @staff_required
    def admin_toggle_maintenance(place_id):
        """Переключить флаг обслуживания для места."""
        try:
            place = PlaceRepository.get_or_404(place_id)
            place.apply_maintenance(not place.maintenance)
            db.session.commit()

            return jsonify({
                'success': True,
                'maintenance': place.maintenance,
                'status': place.status,
                'message': f'Место "{place.name}" {"переведено на обслуживание" if place.maintenance else "снято с обслуживания"}'
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': _api_error(e)}), 500



    @app.route('/api/admin/places/<int:place_id>/maintenance', methods=['PUT'])
    @staff_required
    def admin_set_maintenance(place_id):
        """Установить флаг обслуживания для места (explicit true/false)."""
        try:
            data = request.get_json()
            maintenance = data.get('maintenance', False)

            place = PlaceRepository.get_or_404(place_id)
            place.apply_maintenance(maintenance)
            db.session.commit()

            parent = place.get_container_place()
            inherited = bool(
                not maintenance
                and parent
                and parent.maintenance
                and place.is_desk()
            )
            effective = place.is_on_maintenance()
            if maintenance:
                message = f'Место "{place.name}" переведено на обслуживание'
            elif inherited:
                message = (
                    f'С места "{place.name}" снято обслуживание, '
                    f'но зона «{parent.name}» всё ещё на обслуживании'
                )
            else:
                message = f'Место "{place.name}" снято с обслуживания'

            return jsonify({
                'success': True,
                'maintenance': effective,
                'own_maintenance': place.maintenance,
                'inherited_from_parent': inherited,
                'status': place.status,
                'message': message,
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': _api_error(e)}), 500



    @app.route('/api/admin/quick_register', methods=['POST'])
    @staff_required
    def admin_quick_register():
        """Быстрая регистрация клиента менеджером.
        Вход: username, phone (обязательны), email (необязателен)
        Выход: {success, user_id, temp_password, message}
        """
        try:
            data = request.json
            username = (data.get('username') or '').strip()
            phone = normalize_phone(data.get('phone'))

            if not username or not phone:
                return jsonify({'success': False, 'error': 'Имя и телефон обязательны'}), 400

            if UserRepository.get_by_phone(phone):
                return jsonify({'success': False, 'error': 'Пользователь с таким телефоном уже существует'}), 400

            email = (data.get('email') or '').strip().lower() or None
            if email:
                if '@' not in email or '.' not in email.split('@')[-1]:
                    return jsonify({'success': False, 'error': 'Укажите корректный email'}), 400
                if UserRepository.get_by_email(email):
                    return jsonify({'success': False, 'error': 'Этот email уже занят'}), 400

            # Генерация временного пароля (6 цифр)
            import random, string
            temp_password = ''.join(random.choices(string.digits, k=6))

            user = models.User(
                email=email,
                username=username,
                phone=phone,
                role='client',
                active=True,
                visitor_kind='tariff',
                must_change_password=True,
                issued_temp_password=temp_password,
            )
            user.set_password(temp_password)
            db.session.add(user)
            db.session.commit()

            return jsonify({
                'success': True,
                'user_id': user.id,
                'temp_password': temp_password,
                'message': f'Клиент {username} создан. Временный пароль: {temp_password}'
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': _api_error(e)}), 500



    @app.route('/api/admin/place/create', methods=['POST'])
    @admin_required
    def admin_create_place():
        """Создать новое рабочее место (БД + layout.json)."""
        data = request.json
        required = ['name', 'kind', 'x', 'y', 'width', 'height']
        for f in required:
            if f not in data:
                return jsonify({'success': False, 'error': f'Отсутствует поле: {f}'}), 400

        if data['kind'] == 'desk' and data.get('container_code'):
            parent = PlaceRepository.get_by_code(data['container_code'])
            if parent and not models.place_allows_child_desks(parent):
                return jsonify({
                    'success': False,
                    'error': _desk_blocked_message(parent),
                }), 400

        if data.get('kind') in ('space', 'room') and data.get('container_code'):
            return jsonify({
                'success': False,
                'error': 'Помещение не может находиться внутри другого помещения.',
            }), 400

        place_kind = 'space' if data['kind'] in ('room', 'space') else data['kind']
        floor_num = int(data.get('floor', 1))
        zone_type_id = data.get('zone_type_id')

        if zone_type_id:
            from internal.models.location_zone import LocationZoneType
            zone_type = LocationZoneType.query.get(int(zone_type_id))
            if not zone_type:
                return jsonify({'success': False, 'error': 'Категория зоны локации не найдена'}), 404
            if not zone_type.active:
                return jsonify({
                    'success': False,
                    'error': 'Архивная зона недоступна для новых мест',
                }), 400
            location = models.ensure_location_for_zone(floor_num, int(zone_type_id))
            if not location:
                return jsonify({'success': False, 'error': 'Категория зоны локации не найдена'}), 404
            location_code = location.code
        else:
            location_code = data.get('location_code') or models.default_location_code_for_floor(floor_num)
            location = models.Location.query.filter_by(code=location_code).first()
            if not location:
                return jsonify({'success': False, 'error': f'Локация {location_code} не найдена'}), 404

        walls = LayoutRepository.load_walls()
        rotation = int(data.get('rotation', 0)) % 360
        parent = None
        parent_meta = {}
        wall_bound_parent = False
        if data['kind'] == 'desk' and data.get('container_code'):
            parent = PlaceRepository.get_by_code(data['container_code'])
            parent_meta = models.get_layout_place_meta(data['container_code']) or {}
            wall_bound_parent = (
                parent_meta.get('source') == 'walls'
                and parent_meta.get('enclosed', True) is not False
            )

        ax, ay = float(data['x']), float(data['y'])
        if place_kind == 'desk':
            ax, ay, geom_err = _validate_desk_geometry(
                None, ax, ay, data['width'], data['height'], rotation,
                floor_num, data.get('container_code'),
            )
            if geom_err:
                return jsonify({'success': False, 'error': geom_err}), 400
        elif not wall_bound_parent and models.rect_overlaps_walls(
            ax, ay, data['width'], data['height'], walls, floor_num,
        ):
            return jsonify({
                'success': False,
                'error': 'Нельзя разместить на стене. Отодвиньте от границ.',
            }), 400

        layout_places = LayoutRepository.load().get('places', [])
        if place_kind != 'desk':
            overlap_err = find_place_overlap(
                layout_places, None, ax, ay, data['width'], data['height'],
                floor_num, place_kind, data.get('container_code'),
            )
            if overlap_err:
                return jsonify({'success': False, 'error': overlap_err}), 400

        category_id = data.get('category_id')
        floor_obj = models.Floor.query.filter_by(number=floor_num).first()
        floor_id = floor_obj.id if floor_obj else location.floor_id

        for _ in range(5):
            code = None
            layout_written = False
            try:
                code = PlaceRepository.generate_code(place_kind, location_code)

                place = models.Place(
                    code=code,
                    name=data['name'],
                    kind=place_kind,
                    location_id=location.id,
                    floor_id=floor_id,
                    status='free',
                    active=True,
                    category_id=category_id if category_id else None,
                )
                if data.get('container_code'):
                    parent = PlaceRepository.get_by_code(data['container_code'])
                    if parent and place_kind == 'desk':
                        place.container_code = parent.code
                if place_kind == 'space':
                    place.enclosed = bool(data.get('enclosed', True))
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
                    'rotation': rotation,
                    'floor': floor_num,
                }
                if zone_type_id:
                    place_dict['zone_type_id'] = int(zone_type_id)
                if data.get('container_code'):
                    place_dict['container_code'] = data['container_code']
                if data.get('kind') in ('room', 'space'):
                    place_dict['enclosed'] = bool(data.get('enclosed', True))
                    if place_dict['enclosed'] is False and category_id:
                        cat = PlaceCategory.query.get(int(category_id))
                        if cat and cat.kind == 'room':
                            category_id = None
                            place.category_id = None
                if category_id:
                    place_dict['category_id'] = int(category_id)
                LayoutRepository.add_place(place_dict)
                layout_written = True

                if place_kind == 'space' and data.get('enclosed', True) and data.get('source') != 'walls':
                    models.create_walls_around_rect(
                        int(ax), int(ay), int(data['width']), int(data['height']), floor_num,
                    )

                db.session.commit()
                models.ensure_place_parent_links()
                db.session.refresh(place)

                layout_meta = models.get_layout_place_meta(code)
                container_code = layout_meta.get('container_code')
                parent_info = None
                if container_code:
                    parent = PlaceRepository.sync_by_code(container_code)
                    if parent:
                        parent_info = {
                            'code': parent.code,
                            'name': parent.name,
                            'enclosed': parent.enclosed,
                        }

                msg = f'Место "{place.name}" создано (код {code})'
                if data['kind'] == 'desk' and parent_info:
                    msg = f'Стол {code} добавлен в помещение «{parent_info["name"]}»'
                elif data['kind'] == 'desk' and not container_code:
                    msg = f'Стол {code} добавлен в коридор (без привязки к помещению)'

                return jsonify({
                    'success': True,
                    'message': msg,
                    'place': place.to_dict(),
                    'container_code': container_code,
                    'parent': parent_info,
                }), 201
            except IntegrityError:
                db.session.rollback()
                if layout_written and code:
                    models.remove_place_from_layout(code)
                continue
            except Exception as e:
                db.session.rollback()
                if layout_written and code:
                    models.remove_place_from_layout(code)
                return jsonify({'success': False, 'error': _api_error(e)}), 500

        return jsonify({
            'success': False,
            'error': 'Не удалось создать место: код уже занят. Обновите страницу.',
        }), 500



    @app.route('/api/admin/place/<int:place_id>', methods=['DELETE'])
    @admin_required
    def admin_delete_place(place_id):
        """Удалить рабочее место по ID (БД + layout.json)."""
        try:
            place = PlaceRepository.get_by_id(place_id)
            if not place:
                print(f"[WARN] Place {place_id} not found")
                return jsonify({'success': False, 'error': f'Место с ID {place_id} не найдено'}), 404

            code = place.code
            print(f"[DEBUG] Deleting place {place_id} (code: {code})")

            _orphan_children_of_place(place)
            if place.is_container():
                _suppress_zone_redetection(code)

            # С карты снимаем, запись places остаётся – code/name доступны для отчётов по броням
            PlaceRepository.deactivate_from_map(place)
            print(f"[DEBUG] Place {place_id} deactivated (code: {code})")

            return jsonify({
                'success': True,
                'message': f'Место "{code}" удалено',
            })
        except Exception as e:
            db.session.rollback()
            import traceback
            print(f"[ERROR] Failed to delete place {place_id}: {e}")
            traceback.print_exc()
            return jsonify({'success': False, 'error': _api_error(e)}), 500



    @app.route('/api/admin/place-by-code/<path:code>', methods=['DELETE'])
    @admin_required
    def admin_delete_place_by_code(code):
        """Удалить рабочее место по коду (БД + layout.json)."""
        try:
            place = PlaceRepository.get_by_code(code)
            if not place:
                print(f"[WARN] Place with code {code} not found in DB")
                geom = models.get_place_geometry(code)
                removed = LayoutRepository.remove_place(code)
                if geom:
                    from internal.models.layout import add_ignored_draft
                    from internal.utils.room_geometry import resolve_wall_room_for_geometry
                    room = resolve_wall_room_for_geometry(geom, int(geom.get('floor', 1)))
                    add_ignored_draft(room or geom, int(geom.get('floor', 1)))
                if removed or geom:
                    return jsonify({
                        'success': True,
                        'message': f'«{code}» убрано с карты',
                    })
                return jsonify({'success': False, 'error': f'Место «{code}» не найдено'}), 404

            print(f"[DEBUG] Deleting place by code: {code} (ID: {place.id})")

            _orphan_children_of_place(place)
            if place.is_container():
                _suppress_zone_redetection(code)

            # С карты снимаем, запись places остаётся
            PlaceRepository.deactivate_from_map(place)
            print(f"[DEBUG] Place deactivated from map: {code}")

            return jsonify({
                'success': True,
                'message': f'Место "{code}" удалено',
            })
        except Exception as e:
            db.session.rollback()
            import traceback
            print(f"[ERROR] Failed to delete place {code}: {e}")
            traceback.print_exc()
            return jsonify({'success': False, 'error': _api_error(e)}), 500



    @app.route('/api/admin/place/<int:place_id>/layout', methods=['PUT'])
    @admin_required
    def admin_update_place_layout(place_id):
        """Имя и параметры закрытой локации."""
        try:
            data = request.json or {}
            place = PlaceRepository.get_by_id(place_id)
            if not place or not place.is_container():
                return jsonify({'success': False, 'error': 'Локация не найдена'}), 404

            meta = models.get_layout_place_meta(place.code)
            if meta.get('source') == 'walls' and data.get('enclosed') is False:
                return jsonify({
                    'success': False,
                    'error': 'Комната по стенам всегда закрытая. Редактируйте стены.',
                }), 400

            layout = LayoutRepository.load()
            for p in layout.get('places', []):
                if p.get('code') != place.code:
                    continue
                if 'name' in data and data['name']:
                    p['name'] = str(data['name']).strip()
                    place.name = p['name']
                p['enclosed'] = True
                place.enclosed = True
                break

            from internal.utils.paths import LAYOUT_PATH
            import json
            with open(LAYOUT_PATH, 'w', encoding='utf-8') as f:
                json.dump(layout, f, ensure_ascii=False, indent=2)
            models.reload_layout()
            db.session.commit()
            models.ensure_place_parent_links()

            return jsonify({
                'success': True,
                'message': 'Локация обновлена',
                'place': place.to_dict(),
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': _api_error(e)}), 500

    @app.route('/api/admin/places/reindex-codes', methods=['POST'])
    @admin_required
    def admin_reindex_place_codes():
        """Починить location, нормализовать омоглифы, перенумеровать коды подряд (1A-T1, 1A-T2, …)."""
        try:
            stats = models.compact_place_codes()
            return jsonify({'success': True, 'message': 'Коды мест обновлены', **stats})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': _api_error(e)}), 500

    @app.route('/api/admin/place/move', methods=['POST'])
    @admin_required
    def admin_move_place():
        """Переместить рабочее место на карте (drag-and-drop). Сохраняет координаты и этаж в layout.json и floor_id в БД."""
        try:
            data = request.json
            code = data.get('code')
            x = data.get('x')
            y = data.get('y')
            floor = data.get('floor')

            if not code or x is None or y is None:
                return jsonify({'success': False, 'error': 'Не указаны код, координаты X или Y'}), 400

            from internal.layout.codes import resolve_layout_place_code
            canonical = resolve_layout_place_code(code)
            if canonical:
                code = canonical

            place = PlaceRepository.sync_by_code(code)
            if not place:
                return jsonify({'success': False, 'error': f'Место с кодом {code} не найдено в layout'}), 404

            geom = models.get_place_geometry(place.code)
            if not geom:
                return jsonify({'success': False, 'error': 'Геометрия места не найдена на карте'}), 404
            w, h = geom['width'], geom['height']
            floor_num = int(floor) if floor is not None else int(geom.get('floor', 1))
            layout_places = LayoutRepository.load().get('places', [])
            fx, fy = float(x), float(y)
            meta = models.get_layout_place_meta(place.code)
            rotation = int(float(meta.get('rotation') or 0)) % 360
            container_code = meta.get('container_code')
            wall_bound_enclosed = False

            if place.kind == 'desk':
                target_container_code, target_err = _desk_target_container_code(
                    layout_places, fx, fy, w, h, floor_num,
                )
                if target_err:
                    return jsonify({'success': False, 'error': target_err}), 400
                container_code = target_container_code
                parent_meta = {}
                if container_code:
                    parent_meta = models.get_layout_place_meta(container_code) or {}
                is_enclosed = (
                    parent_meta.get('enclosed', True) is not False
                    or parent_meta.get('source') == 'walls'
                )
                wall_bound_enclosed = parent_meta.get('source') == 'walls' and is_enclosed
                if container_code and is_enclosed:
                    pg = models.get_place_geometry(container_code)
                    if pg:
                        clamped = clamp_rect_in_parent_rotated(
                            fx, fy, w, h, rotation,
                            pg['x'], pg['y'], pg['width'], pg['height'],
                        )
                        if clamped[0] is None:
                            return jsonify({
                                'success': False,
                                'error': 'Стол не помещается внутри помещения',
                            }), 400
                        fx, fy = clamped
                fx, fy, geom_err = _validate_desk_geometry(
                    place.code, fx, fy, w, h, rotation, floor_num, container_code,
                )
                if geom_err:
                    return jsonify({'success': False, 'error': geom_err}), 400
            else:
                walls = LayoutRepository.load_walls()
                if models.rect_overlaps_walls(fx, fy, w, h, walls, floor_num):
                    return jsonify({
                        'success': False,
                        'error': 'Нельзя оставить объект на стене. Отодвиньте от границ.',
                    }), 400
                overlap_err = find_place_overlap(
                    layout_places, place.code, fx, fy, w, h, floor_num,
                    place.kind, container_code,
                )
                if overlap_err:
                    return jsonify({'success': False, 'error': overlap_err}), 400

            ok = LayoutRepository.save_place_geometry(place.code, fx, fy, floor=floor)
            if not ok:
                return jsonify({'success': False, 'error': 'Не удалось сохранить координаты на карте'}), 500

            # Обновляем floor_id в БД для целостности данных
            if floor is not None:
                floor_obj = models.Floor.query.filter_by(number=int(floor)).first()
                if floor_obj:
                    place.floor_id = floor_obj.id
                    db.session.commit()

            models.ensure_place_parent_links()

            return jsonify({
                'success': True,
                'message': f'Место "{place.name}" перемещено (x={fx:.1f}, y={fy:.1f}, floor={floor})',
                'code': code, 'x': fx, 'y': fy, 'floor': floor,
                'container_code': place.container_code,
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': _api_error(e)}), 500



    @app.route('/api/admin/place/resize', methods=['POST'])
    @admin_required
    def admin_resize_place():
        """Изменить размеры места (width/height) в layout.json."""
        try:
            data = request.json
            code = data.get('code')
            width = data.get('width')
            height = data.get('height')
            if not code or width is None or height is None:
                return jsonify({'success': False, 'error': 'Не указаны код, ширина или высота'}), 400
            geom = models.get_place_geometry(code)
            floor_num = int(geom.get('floor', 1))
            walls = LayoutRepository.load_walls()
            if models.rect_overlaps_walls(
                geom['x'], geom['y'], width, height, walls, floor_num,
            ):
                return jsonify({
                    'success': False,
                    'error': 'Нельзя оставить объект на стене. Отодвиньте от границ.',
                }), 400
            meta = models.get_layout_place_meta(code)
            layout_places = LayoutRepository.load().get('places', [])
            overlap_err = find_place_overlap(
                layout_places, code, geom['x'], geom['y'], width, height, floor_num,
                meta.get('kind', 'desk'), meta.get('container_code'),
            )
            if overlap_err:
                return jsonify({'success': False, 'error': overlap_err}), 400
            ok = LayoutRepository.resize_place(code, width, height)
            if not ok:
                return jsonify({'success': False, 'error': 'Место не найдено'}), 404
            return jsonify({'success': True, 'message': f'Размеры {code} изменены: {width}×{height}'})
        except Exception as e:
            return jsonify({'success': False, 'error': _api_error(e)}), 500



    @app.route('/api/admin/place/rotate', methods=['POST'])
    @admin_required
    def admin_rotate_place():
        try:
            data = request.json
            code = data.get('code')
            rotation = data.get('rotation')
            if not code or rotation is None:
                return jsonify({'success': False, 'error': 'Не указаны код или угол поворота'}), 400

            from internal.layout.codes import resolve_layout_place_code
            canonical = resolve_layout_place_code(code)
            if canonical:
                code = canonical

            geom = models.get_place_geometry(code)
            if not geom:
                return jsonify({'success': False, 'error': 'Место не найдено на карте'}), 404
            meta = models.get_layout_place_meta(code) or {}
            rotation = int(float(rotation)) % 360
            floor_num = int(geom.get('floor', 1))
            container_code = meta.get('container_code')

            if meta.get('kind', 'desk') == 'desk':
                ax, ay, geom_err = _validate_desk_geometry(
                    code, geom['x'], geom['y'], geom['width'], geom['height'],
                    rotation, floor_num, container_code,
                )
                if geom_err:
                    return jsonify({'success': False, 'error': geom_err}), 400

            ok = LayoutRepository.rotate_place(code, rotation)
            if not ok:
                return jsonify({'success': False, 'error': 'Место не найдено'}), 404
            if meta.get('kind', 'desk') == 'desk':
                LayoutRepository.save_place_geometry(code, ax, ay, floor=floor_num)
            return jsonify({'success': True, 'message': f'Поворот {code}: {rotation}°'})
        except Exception as e:
            return jsonify({'success': False, 'error': _api_error(e)}), 500


    # --- Стены ---

    @app.route('/api/admin/walls', methods=['GET'])
    @admin_required
    def get_walls():
        return jsonify({'walls': LayoutRepository.load_walls(), 'doors': LayoutRepository.load_doors()})



    @app.route('/api/admin/wall/create', methods=['POST'])
    @admin_required
    def create_wall():
        try:
            d = request.json
            wall_id = LayoutRepository.add_wall(d['x1'], d['y1'], d['x2'], d['y2'], floor=d.get('floor', 1))
            return jsonify({'success': True, 'wall_id': wall_id})
        except Exception as e:
            return jsonify({'success': False, 'error': _api_error(e)}), 500



    @app.route('/api/admin/wall/<int:wall_id>', methods=['DELETE'])
    @admin_required
    def remove_wall(wall_id):
        try:
            LayoutRepository.delete_wall(wall_id)
            return jsonify({'success': True})
        except PermissionError as e:
            return jsonify({'success': False, 'error': user_error_message(e)}), 403
        except Exception as e:
            return jsonify({'success': False, 'error': _api_error(e)}), 500


    # --- Двери ---

    @app.route('/api/admin/door/create', methods=['POST'])
    @admin_required
    def create_door():
        try:
            d = request.json
            width = int(d.get('width', 100))
            door_id = LayoutRepository.add_door(
                d['wall_id'], d['position'], floor=d.get('floor', 1), width=width,
            )
            return jsonify({'success': True, 'door_id': door_id})
        except Exception as e:
            return jsonify({'success': False, 'error': _api_error(e)}), 500



    @app.route('/api/admin/door/<int:door_id>', methods=['DELETE'])
    @admin_required
    def remove_door(door_id):
        try:
            LayoutRepository.delete_door(door_id)
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': _api_error(e)}), 500



    @app.route('/api/admin/door/move', methods=['POST'])
    @admin_required
    def move_door():
        try:
            d = request.json
            ok = LayoutRepository.move_door(
                d['door_id'],
                wall_id=d.get('wall_id'),
                position=d.get('position'),
                width=d.get('width'),
            )
            if not ok:
                return jsonify({'success': False, 'error': 'Дверь не найдена'}), 404
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': _api_error(e)}), 500



    @app.route('/api/admin/wall/move', methods=['POST'])
    @admin_required
    def move_wall_route():
        try:
            d = request.json or {}
            synced = LayoutRepository.move_wall(
                d['wall_id'], d['x1'], d['y1'], d['x2'], d['y2'],
            )
            if synced is None:
                return jsonify({'success': False, 'error': 'Стена не найдена'}), 404
            models.ensure_place_parent_links()
            msg = 'Стена перемещена'
            if synced:
                msg += f'; локации подтянуты: {", ".join(synced)}'
            return jsonify({'success': True, 'message': msg, 'synced_places': synced})
        except PermissionError as e:
            return jsonify({'success': False, 'error': user_error_message(e)}), 403
        except Exception as e:
            return jsonify({'success': False, 'error': _api_error(e)}), 500



    @app.route('/admin/place/<int:place_id>/toggle_status', methods=['POST'])
    @admin_required
    def admin_toggle_place_status(place_id):
        """Активировать/деактивировать место"""
        try:
            place = PlaceRepository.get_or_404(place_id)
            place.active = not place.active

            db.session.commit()

            status = "активировано" if place.active else "деактивировано"
            flash(f'Место {place.name} {status}', 'success')

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при изменении статуса места: {_api_error(e)}', 'error')

        return redirect(url_for('admin_places'))


    # ================== API ДЛЯ АБОНЕМЕНТОВ ==================

