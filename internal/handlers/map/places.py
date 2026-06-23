"""Map and place API."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from flask import jsonify, request
from flask_login import login_required
from sqlalchemy.orm import joinedload

from internal.handlers.deps import (
    Booking, Place, PlaceRepository, booking_legacy_service, models, BookingRepository,
)
from internal.models import Floor
from internal.layout.repository import LayoutRepository
from internal.services import booking_service
from internal.utils.formatters import format_place_full_code_dict
from internal.utils.errors import user_error_message


def register_place_routes(app):
    @app.route('/api/floors', methods=['GET'])
    def get_floors():
        """Список этажей коворкинга."""
        floors = Floor.query.order_by(Floor.number).all()
        return jsonify({
            'success': True,
            'floors': [
                {
                    'id': f.id,
                    'number': f.number,
                    'name': f.name,
                    'label': f.name or f'Этаж {f.number}',
                }
                for f in floors
            ],
        })

    @app.route('/api/places', methods=['GET'])
    def get_places():
        try:
            layout = LayoutRepository.load()
            layout_places = layout.get('places', [])
            walls = layout.get('walls', [])
            doors = layout.get('doors', [])

            layout_by_code = {
                p.get('code'): p for p in layout_places if p.get('code')
            }
            children_by_parent = defaultdict(list)
            for lp in layout_places:
                if lp.get('container_code') and lp.get('kind') == 'desk':
                    children_by_parent[lp['container_code']].append(lp)

            places_by_code = PlaceRepository.get_by_codes(layout_by_code.keys())
            floors_by_number = {
                f.number: f.name for f in Floor.query.all()
            }
            zone_types_by_id = {
                z.id_zone_type: z for z in models.LocationZoneType.query.all()
            }
            locations_by_code = {
                loc.code: loc for loc in models.Location.query.all()
            }

            def is_amenity_layout_item(lp):
                from internal.models.location_zone import is_amenity_zone_kind, layout_place_belongs_in_db
                return not layout_place_belongs_in_db(lp)

            now = datetime.now()
            active_bookings = Booking.query.filter(
                Booking.status == 'active',
                Booking.booking_date == now.date(),
                Booking.start_time <= now.time(),
                Booking.end_time > now.time(),
            ).all()
            bookings_by_place_id = defaultdict(list)
            for booking in active_bookings:
                bookings_by_place_id[booking.place_id].append(booking)

            child_ids_by_container_code = defaultdict(list)
            places_by_id = {}
            for db_place in places_by_code.values():
                places_by_id[db_place.id] = db_place
                if db_place.container_code and db_place.kind == 'desk':
                    child_ids_by_container_code[db_place.container_code].append(db_place.id)

            category_tariffs = {}

            def live_status(db_place):
                if db_place.is_on_maintenance():
                    return {
                        'status': 'maintenance',
                        'current_occupancy': 0,
                        'occupied_until': None,
                        'partial_occupancy': None,
                        'taken_seats': [],
                        'whole_table_taken': False,
                    }

                current = bookings_by_place_id.get(db_place.id, [])
                current_occupancy = sum(b.people_count or 0 for b in current)
                capacity = db_place.capacity if db_place.capacity else 1

                if current_occupancy == 0:
                    status = 'free'
                elif capacity > 1 and current_occupancy < capacity:
                    status = 'partial'
                else:
                    status = 'occupied'

                occupied_until = None
                if current:
                    occupied_until = max(b.end_time for b in current).strftime('%H:%M')

                taken_seats = []
                whole_table_taken = any(
                    (b.people_count or 0) >= capacity for b in current
                )
                partial_occupancy = None
                if capacity > 1 and 0 < current_occupancy < capacity:
                    partial_occupancy = {
                        'occupied': current_occupancy,
                        'capacity': capacity,
                        'available': capacity - current_occupancy,
                    }

                return {
                    'status': status,
                    'current_occupancy': current_occupancy,
                    'occupied_until': occupied_until,
                    'partial_occupancy': partial_occupancy,
                    'taken_seats': taken_seats,
                    'whole_table_taken': whole_table_taken,
                }

            def display_status(db_place):
                if db_place.is_on_maintenance():
                    return live_status(db_place)

                if db_place.is_container() and child_ids_by_container_code.get(db_place.code):
                    own = live_status(db_place)
                    if own['current_occupancy'] > 0:
                        return own

                    child_ids = child_ids_by_container_code[db_place.code]
                    child_id_set = set(child_ids)
                    children = [places_by_id[i] for i in child_ids if i in places_by_id]
                    total_cap = sum(c.capacity for c in children)
                    total_occ = sum(
                        sum(b.people_count or 0 for b in bookings_by_place_id.get(c.id, []))
                        for c in children
                    )
                    if total_occ == 0:
                        status = 'free'
                    elif total_cap > 1 and total_occ < total_cap:
                        status = 'partial'
                    else:
                        status = 'occupied'
                    return {
                        'status': status,
                        'current_occupancy': total_occ,
                        'occupied_until': own.get('occupied_until'),
                        'partial_occupancy': {
                            'occupied': total_occ,
                            'capacity': total_cap,
                            'available': total_cap - total_occ,
                        } if total_cap > 1 and 0 < total_occ < total_cap else None,
                        'taken_seats': [],
                        'whole_table_taken': status == 'occupied',
                    }
                return live_status(db_place)

            # Преобразуем места: БД уже синхронизирована выше, дальше работаем из кэшей
            formatted_places = []
            for p in layout_places:
                code = p.get('code')
                db_place = places_by_code.get(code)

                if db_place:
                    place_id = db_place.id
                    category_info = None
                    hourly_price = db_place.get_price('hourly')
                    if db_place.category:
                        cat = db_place.category
                        category_info = {
                            'id': cat.id,
                            'name': cat.name,
                            'capacity': cat.capacity,
                            'kind': cat.kind,
                            'hourly_price': hourly_price,
                        }
                        if cat.id not in category_tariffs:
                            category_tariffs[cat.id] = [
                                t.to_dict() for t in cat.tariffs if t.active
                            ]
                elif is_amenity_layout_item(p):
                    place_id = None
                    category_info = None
                else:
                    continue

                hourly_price = db_place.get_price('hourly') if db_place else None
                show_list_price = bool(
                    db_place
                    and (
                        db_place.kind == 'desk'
                        or db_place.is_meeting_room()
                        or db_place.kind == 'room'
                    )
                    and not (
                        db_place.is_container()
                        and db_place.allows_child_desks()
                        and not db_place.is_meeting_room()
                    )
                )

                live = display_status(db_place) if db_place else {'status': 'free'}
                layout_meta = p
                children_count = len(children_by_parent.get(code, []))

                floor_num = int(p.get('floor', 1))
                floor_name = floors_by_number.get(floor_num, f'{floor_num}-й этаж')
                loc = db_place.location if db_place else locations_by_code.get(p.get('location'))
                zone_type = None
                if loc and loc.zone_type:
                    zone_type = loc.zone_type.to_dict()
                elif layout_meta.get('zone_type_id'):
                    zt = zone_types_by_id.get(layout_meta['zone_type_id'])
                    if zt:
                        zone_type = zt.to_dict()

                from internal.models.category import PlaceCategory as PC
                w_px = float(p.get('width', 0) or 0)
                h_px = float(p.get('height', 0) or 0)
                layout_w_m = round(w_px / PC.SCALE_FACTOR, 2) if w_px else None
                layout_h_m = round(h_px / PC.SCALE_FACTOR, 2) if h_px else None
                place_name = p.get('name') or code
                amenity = is_amenity_layout_item(p) or bool(
                    zone_type and zone_type.get('kind') in (
                        'amenity_zone', 'lounge_zone', 'kitchen_zone', 'wc_zone',
                    )
                )

                formatted_places.append({
                    'id': place_id,
                    'code': code,
                    'name': place_name,
                    'display_name': f'{place_name} ({code})',
                    'kind': p.get('kind', 'desk'),
                    'x': p.get('x', 0),
                    'y': p.get('y', 0),
                    'width': p.get('width', 100),
                    'height': p.get('height', 100),
                    'width_m': layout_w_m,
                    'height_m': layout_h_m,
                    'size_label': (
                        f'{layout_w_m}×{layout_h_m} м' if layout_w_m and layout_h_m else None
                    ),
                    'rotation': p.get('rotation', 0),
                    'floor': floor_num,
                    'floor_name': floor_name,
                    'location_code': loc.code if loc else p.get('location'),
                    'location_name': loc.name if loc else None,
                    'zone_type': zone_type,
                    'zone_type_id': zone_type['id'] if zone_type else layout_meta.get('zone_type_id'),
                    'capacity': db_place.capacity if db_place else p.get('capacity', 1),
                    'price_per_hour': hourly_price,
                    'show_list_price': show_list_price,
                    'active': p.get('active', True),
                    'maintenance': db_place.is_on_maintenance() if db_place else False,
                    'own_maintenance': db_place.maintenance if db_place else False,
                    'status': live['status'],
                    'current_occupancy': live.get('current_occupancy', 0),
                    'occupied_until': live.get('occupied_until'),
                    'partial_occupancy': live.get('partial_occupancy'),
                    'taken_seats': live.get('taken_seats', []),
                    'whole_table_taken': live.get('whole_table_taken', False),
                    'container_code': (
                        (db_place.container_code if db_place else None)
                        or layout_meta.get('container_code')
                        or p.get('container_code')
                    ),
                    'enclosed': db_place.enclosed if db_place else p.get('enclosed', False),
                    'bookable': False if amenity else layout_meta.get('bookable', p.get('bookable', True)),
                    'is_amenity': amenity,
                    'is_container': db_place.is_container() if db_place else p.get('kind') in ('room', 'space'),
                    'allows_desks': db_place.allows_child_desks() if db_place else not amenity,
                    'is_meeting_room': db_place.is_meeting_room() if db_place else False,
                    'children_count': children_count,
                    'rating': round(db_place.rating, 1) if db_place and db_place.rating else 0.0,
                    'rating_count': db_place.rating_count if db_place else 0,
                    'category': category_info,
                    'in_db': db_place is not None,
                })

            by_code = {p['code']: p for p in formatted_places}
            for p in formatted_places:
                if not p.get('is_container') or p.get('is_meeting_room'):
                    p['zone_seat_capacity'] = p.get('capacity', 1)
                    continue
                if p.get('allows_desks'):
                    p['zone_seat_capacity'] = sum(
                        by_code[c]['capacity']
                        for c in by_code
                        if by_code[c].get('kind') == 'desk'
                        and by_code[c].get('container_code') == p['code']
                    )
                else:
                    p['zone_seat_capacity'] = p.get('capacity', 1)

            for p in formatted_places:
                container_code = p.get('container_code')
                if p.get('kind') == 'desk' and container_code:
                    parent = by_code.get(container_code)
                    if parent:
                        p['parent_name'] = parent.get('name')
                        p['location_display'] = f"{parent.get('name')} ({parent.get('code')})"
                elif p.get('location_name') or p.get('location_code'):
                    loc_name = p.get('location_name') or ''
                    loc_code = p.get('location_code') or ''
                    p['location_display'] = (
                        f'{loc_name} ({loc_code})' if loc_name else loc_code
                    )

            for p in formatted_places:
                p['full_code'] = format_place_full_code_dict(p, by_code)

            return jsonify({
                'places': formatted_places,
                'walls': walls,
                'doors': doors,
                'category_tariffs': category_tariffs,
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({'error': user_error_message(e)}), 500

    @app.route('/api/seat_occupancy/<int:place_id>', methods=['GET'])
    @login_required
    def get_seat_occupancy(place_id):
        """Какие места за столом заняты на указанный интервал времени."""
        try:
            place = PlaceRepository.get_or_404(place_id)
            date_str = request.args.get('date')
            start_str = request.args.get('start')
            end_str = request.args.get('end')
            if not (date_str and start_str and end_str):
                return jsonify({'success': False, 'error': 'Укажите дату, время начала и окончания'}), 400

            booking_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            start_t = datetime.strptime(start_str, '%H:%M').time()
            end_t = datetime.strptime(end_str, '%H:%M').time()

            status = place.get_seats_status_at(booking_date_obj, start_t, end_t)
            return jsonify({
                'success': True,
                'place_id': place.id,
                'capacity': place.capacity,
                'taken_seats': status['taken_seats'],
                'whole_table_taken': status['whole_table_taken'],
            })
        except Exception as e:
            return jsonify({'success': False, 'error': user_error_message(e)}), 500

    @app.route('/api/available_times/<int:place_id>', methods=['GET'])
    @login_required
    def get_available_times(place_id):
        """Получить доступное время для места на выбранную дату."""
        try:
            date_str = request.args.get('date')
            if not date_str:
                return jsonify({'error': 'Дата не указана'}), 400

            booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            place = PlaceRepository.get_or_404(place_id)
            bookings = BookingRepository.get_active_for_place_on_date(place_id, booking_date)

            now = datetime.now()
            today = now.date()
            current_time = now.time()

            current_booking = None
            if booking_date == today:
                current_booking = Booking.query.filter(
                    Booking.place_id == place_id,
                    Booking.status == 'active',
                    Booking.booking_date == today,
                    Booking.start_time <= current_time,
                    Booking.end_time > current_time,
                ).first()

            work_start, work_end, is_bookable = booking_service.get_coworking_schedule_for_place(
                place_id, booking_date,
            )
            if not work_start or not work_end or not is_bookable:
                return jsonify({
                    'place': place.to_dict(),
                    'date': date_str,
                    'available_slots': [],
                    'all_slots': [],
                    'grouped_slots': [],
                    'schedule_message': 'Коворкинг не работает в этот день',
                })

            available_slots = []
            all_slots = []

            def is_slot_available(slot_start, slot_end):
                if booking_date == today and slot_start < current_time:
                    return False
                for booking in bookings:
                    if not (slot_end <= booking.start_time or slot_start >= booking.end_time):
                        return False
                return True

            slot_times = booking_service.generate_time_slots(work_start, work_end)
            for current_time_slot in slot_times:
                slot_end_dt = datetime.combine(date.today(), current_time_slot) + timedelta(minutes=15)
                slot_end = slot_end_dt.time()
                if slot_end > work_end:
                    break
                is_available = is_slot_available(current_time_slot, slot_end)
                all_slots.append({
                    'start': current_time_slot.strftime('%H:%M'),
                    'end': slot_end.strftime('%H:%M'),
                    'available': is_available,
                })
                if is_available:
                    available_slots.append({
                        'start': current_time_slot.strftime('%H:%M'),
                        'end': slot_end.strftime('%H:%M'),
                        'label': f"{current_time_slot.strftime('%H:%M')} - {slot_end.strftime('%H:%M')}",
                    })

            grouped_slots = []
            temp_slot = None
            for slot in available_slots:
                if not temp_slot:
                    temp_slot = slot.copy()
                elif slot['start'] == temp_slot['end']:
                    temp_slot['end'] = slot['end']
                    temp_slot['label'] = f"{temp_slot['start']} - {slot['end']}"
                else:
                    grouped_slots.append(temp_slot)
                    temp_slot = slot.copy()
            if temp_slot:
                grouped_slots.append(temp_slot)

            current_occupation_info = None
            if current_booking:
                current_occupation_info = {
                    'start': current_booking.start_time.strftime('%H:%M'),
                    'end': current_booking.end_time.strftime('%H:%M'),
                    'occupied_until': current_booking.end_time.strftime('%H:%M'),
                }

            return jsonify({
                'place': place.to_dict(),
                'date': date_str,
                'available_slots': grouped_slots,
                'all_slots': all_slots,
                'capacity': place.capacity,
                'bookings': [{
                    'start': b.start_time.strftime('%H:%M'),
                    'end': b.end_time.strftime('%H:%M'),
                } for b in bookings],
                'current_occupation': current_occupation_info,
            })
        except Exception as e:
            return jsonify({'error': user_error_message(e)}), 500


