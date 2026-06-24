"""Booking API handlers (15-min slots)."""
from datetime import datetime, date

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from internal.models import Booking, Subscription, db
from internal.repositories.place_repository import PlaceRepository
from internal.services import booking_service


def _zone_booking_rules(place, people_count):
    """Закрытая зона столов бронируется целиком."""
    if place.is_container() and place.allows_child_desks():
        if people_count != 1:
            return False, 'Закрытую зону можно забронировать только целиком (на все места сразу)'
    return True, None


def _duration_hours_from_times(start_time, end_time):
    """Длительность по 15-минутной сетке (совпадает с модулем бронирования)."""
    start_m = start_time.hour * 60 + start_time.minute
    end_m = end_time.hour * 60 + end_time.minute
    slots = max(0, (end_m - start_m) // 15)
    return slots * 0.25


def _calc_booking_total(place, tariff, tariff_type, duration_hours, people_count,
                        start_time=None, end_time=None):
    """Стоимость в целых рублях.
    Зоны (open space с вложенными столами) и переговорные (rooms) – тариф за всё
    помещение целиком. Для столов тариф задаётся на одного человека, поэтому
    умножается на количество людей и не делится на вместимость стола.
    """
    is_zone = place.is_container() and place.allows_child_desks()
    is_room = place.kind == 'room'
    use_full_price = is_zone or is_room  # полная цена без деления на вместимость
    capacity = max(1, place.capacity or 1)
    people = max(1, people_count or 1)

    if tariff_type == 'hourly':
        if start_time is not None and end_time is not None:
            duration_hours = _duration_hours_from_times(start_time, end_time)
        if use_full_price:
            total = duration_hours * tariff.price
        else:
            total = duration_hours * tariff.price * people
        return int(round(total))

    if use_full_price:
        return int(round(tariff.price))
    return int(round(tariff.price * people))

booking_bp = Blueprint('booking_api', __name__)


@booking_bp.route('/api/booking/timegrid/<int:place_id>', methods=['GET'])
def get_timegrid(place_id):
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'success': False, 'error': 'Укажите дату'}), 400
    try:
        booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'error': 'Неверный формат даты'}), 400

    resolved_id = PlaceRepository.resolve_id(place_id)
    if not resolved_id:
        return jsonify({'success': False, 'error': 'Место не найдено'}), 404
    
    grid = booking_service.get_timegrid_for_place(resolved_id, booking_date)
    if 'error' in grid:
        return jsonify({'success': False, 'error': grid['error']}), 404
    return jsonify({'success': True, 'data': grid})

@booking_bp.route('/api/booking/check', methods=['POST'])
@login_required
def check_booking():
    data = request.json
    required = ['place_id', 'date', 'start_time', 'end_time']
    for field in required:
        if field not in data:
            return jsonify({'success': False, 'error': f'Отсутствует: {field}'}), 400
    
    try:
        place_id = PlaceRepository.resolve_id(data['place_id'])
        if not place_id:
            return jsonify({'success': False, 'error': 'Место не найдено'}), 404
        booking_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        start_time = datetime.strptime(data['start_time'], '%H:%M').time()
        end_time = datetime.strptime(data['end_time'], '%H:%M').time()
        people_count = int(data.get('people_count', 1))
        tariff_type = data.get('tariff_type', 'hourly')
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Некорректные данные запроса'}), 400

    place = PlaceRepository.get_by_id(place_id)
    if not place:
        return jsonify({'success': False, 'error': 'Место не найдено'}), 404
    
    is_available, message, slots = booking_service.check_period_availability(
        place_id, booking_date, start_time, end_time, people_count,
        tariff_type=tariff_type,
    )

    total_price = None
    if is_available and place.category:
        tariff = place.category.get_tariff(tariff_type)
        if tariff:
            total_price = _calc_booking_total(
                place, tariff, tariff_type, 0, people_count,
                start_time=start_time, end_time=end_time,
            )

    return jsonify({
        'success': True,
        'is_available': is_available,
        'message': message,
        'total_price': total_price,
        'slots': [s.to_dict() for s in slots] if slots else None
    })

@booking_bp.route('/api/booking/price', methods=['POST'])
@login_required
def calculate_price():
    """Рассчитать стоимость бронирования.
    Если у клиента есть абонемент, покрывающий переданную дату и тип места,
    возвращает 0 руб. (бесплатно по абонементу).
    """
    data = request.json
    required = ['place_id', 'start_time', 'end_time', 'tariff_type']
    for field in required:
        if field not in data:
            return jsonify({'success': False, 'error': f'Отсутствует: {field}'}), 400

    try:
        place_id = PlaceRepository.resolve_id(data['place_id'])
        if not place_id:
            return jsonify({'success': False, 'error': 'Место не найдено'}), 404
        start_time = datetime.strptime(data['start_time'], '%H:%M').time()
        end_time = datetime.strptime(data['end_time'], '%H:%M').time()
        people_count = int(data.get('people_count', 1))
        tariff_type = data['tariff_type']
        booking_date = None
        if data.get('date'):
            booking_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Некорректные данные запроса'}), 400

    place = PlaceRepository.get_by_id(place_id)
    if not place:
        return jsonify({'success': False, 'error': 'Место не найдено'}), 404

    ok_rules, rules_err = _zone_booking_rules(place, people_count)
    if not ok_rules:
        return jsonify({'success': False, 'error': rules_err}), 400

    duration_hours = _duration_hours_from_times(start_time, end_time)

    tariff = None
    if place.category:
        tariff = place.category.get_tariff(tariff_type)

    if not tariff:
        return jsonify({
            'success': False,
            'error': f'Тариф "{tariff_type}" не доступен для этой категории'
        }), 400

    total_price = _calc_booking_total(
        place, tariff, tariff_type, duration_hours, people_count,
        start_time=start_time, end_time=end_time,
    )
    is_zone = place.is_container() and place.allows_child_desks()

    # Проверяем абонемент (только почасовой тариф и если передана дата)
    is_subscription = False
    subscription_info = None
    if tariff_type == 'hourly' and booking_date and not data.get('no_subscription'):
        sub = Subscription.query.filter(
            Subscription.user_id == current_user.id,
            Subscription.active == True,
            Subscription.start_date <= booking_date,
            Subscription.end_date >= booking_date,
        ).first()
        if sub and sub.can_book_place(place.kind):
            # Проверяем лимит часов
            if not sub.hours_limit or (sub.hours_used + duration_hours <= sub.hours_limit):
                is_subscription = True
                remaining = None if not sub.hours_limit else round(sub.hours_limit - sub.hours_used, 1)
                subscription_info = {
                    'id': sub.id_subscription,
                    'name': sub.name,
                    'remaining_hours': remaining,
                    'valid_until': sub.end_date.strftime('%d.%m.%Y'),
                }

    return jsonify({
        'success': True,
        'tariff_type': tariff_type,
        'tariff_label': tariff.tariff_type_label,
        'duration_hours': round(duration_hours, 2),
        'total_price': 0 if is_subscription else total_price,
        'full_price': total_price,
        'is_subscription': is_subscription,
        'subscription': subscription_info,
        'price_per_person': (
            int(round(total_price / people_count)) if people_count and not is_zone and tariff_type == 'hourly'
            else None
        ),
    })

@booking_bp.route('/api/places/<int:place_id>/tariffs', methods=['GET'])
@login_required
def get_place_tariffs(place_id):
    """Получить доступные тарифы для места"""
    place = PlaceRepository.get_by_id(place_id)
    if not place:
        return jsonify({'success': False, 'error': 'Место не найдено'}), 404

    tariffs = []
    if place.category:
        tariffs = [t.to_dict() for t in place.category.tariffs if t.active]

    return jsonify({
        'success': True,
        'place_id': place_id,
        'place_name': place.name,
        'tariffs': tariffs
    })

@booking_bp.route('/api/booking/create', methods=['POST'])
@login_required
def create_booking_route():
    from flask_login import current_user
    from internal.repositories.user_repository import UserRepository

    data = request.json
    required = ['place_id', 'date', 'start_time', 'end_time']
    for field in required:
        if field not in data:
            return jsonify({'success': False, 'error': f'Отсутствует: {field}'}), 400
    
    try:
        place_id = PlaceRepository.resolve_id(data['place_id'])
        if not place_id:
            return jsonify({'success': False, 'error': 'Место не найдено'}), 404
        booking_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        start_time = datetime.strptime(data['start_time'], '%H:%M').time()
        end_time = datetime.strptime(data['end_time'], '%H:%M').time()
        people_count = int(data.get('people_count', 1))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Некорректные данные запроса'}), 400
    
    tariff_type = data.get('tariff_type', 'hourly')

    target_user_id = current_user.id
    if data.get('user_id') and current_user.is_manager():
        target_user = UserRepository.get_by_id(data['user_id'])
        if target_user and target_user.role == 'client':
            target_user_id = target_user.id

    place = PlaceRepository.get_by_id(place_id)
    if not place:
        return jsonify({'success': False, 'error': 'Место не найдено'}), 404

    ok_rules, rules_err = _zone_booking_rules(place, people_count)
    if not ok_rules:
        return jsonify({'success': False, 'error': rules_err}), 400

    is_available, message, slots = booking_service.check_period_availability(
        place_id, booking_date, start_time, end_time, people_count,
        tariff_type=tariff_type,
    )
    if not is_available:
        return jsonify({'success': False, 'error': message}), 400

    if tariff_type in ('weekly', 'monthly'):
        open_time, close_time, _ = booking_service.get_coworking_schedule_for_place(place_id, booking_date)
        if open_time and close_time:
            start_time, end_time = open_time, close_time
        period_days = booking_service.period_days_for_tariff(tariff_type)
        day_hours = (
            datetime.combine(date.today(), end_time) - datetime.combine(date.today(), start_time)
        ).seconds / 3600
        duration_hours = day_hours * period_days
    else:
        start_dt = datetime.combine(date.today(), start_time)
        end_dt = datetime.combine(date.today(), end_time)
        duration_hours = (end_dt - start_dt).seconds / 3600

    # Проверяем абонемент (только для будущих бронирований)
    now = datetime.now()
    is_subscription_booking = False
    subscription = None

    if booking_date >= now.date():
        use_subscription = data.get('use_subscription', True)
        if use_subscription is False or use_subscription == 'false' or use_subscription == 0:
            use_subscription = False
        else:
            use_subscription = True

        # Ищем действующий абонемент для типа места (у клиента, за которого оформляют)
        subscription = Subscription.query.filter(
            Subscription.user_id == target_user_id,
            Subscription.active == True,
            Subscription.start_date <= booking_date,
            Subscription.end_date >= booking_date
        ).first()

        # Абонемент с лимитом часов – только для почасового тарифа
        if (
            use_subscription
            and tariff_type == 'hourly'
            and subscription
            and subscription.can_book_place(place.kind)
        ):
            if people_count != 1:
                return jsonify({
                    'success': False,
                    'error': 'По абонементу можно бронировать только на 1 человека',
                }), 400
            if subscription.hours_limit and (subscription.hours_used + duration_hours > subscription.hours_limit):
                return jsonify({
                    'success': False,
                    'error': f'Превышен лимит абонемента. Осталось {subscription.hours_remaining} ч, требуется {duration_hours} ч'
                }), 400
            is_subscription_booking = True

    # Рассчитываем цену на основе тарифа
    total_price = 0
    category_tariff_id = None

    if not is_subscription_booking:
        if place.category:
            # Получаем тариф для категории
            tariff = place.category.get_tariff(tariff_type)
            if tariff:
                category_tariff_id = tariff.id
                total_price = _calc_booking_total(
                    place, tariff, tariff_type, duration_hours, people_count,
                    start_time=start_time, end_time=end_time,
                )
            else:
                return jsonify({
                    'success': False,
                    'error': f'Тариф "{tariff_type}" не настроен для этой категории мест'
                }), 400
        else:
            return jsonify({
                'success': False,
                'error': 'У места не назначена категория - бронирование невозможно'
            }), 400

    booking = Booking(
        user_id=target_user_id,
        place_id=place_id,
        booking_date=booking_date,
        start_time=start_time,
        end_time=end_time,
        duration_hours=duration_hours,
        total_price=total_price,
        people_count=people_count,
        tariff_type=tariff_type,
        category_tariff_id=category_tariff_id,
        status='active',
    )
    db.session.add(booking)
    
    # Если использован абонемент - обновляем счетчик часов
    if is_subscription_booking and subscription:
        subscription.hours_used += duration_hours
        db.session.add(subscription)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': (
            f'Бронирование создано: {place.name}'
            + (' (зона целиком)' if place.is_container() and place.allows_child_desks() else f' на {people_count} чел.')
            + (' (по абонементу)' if is_subscription_booking else '')
        ),
        'booking_id': booking.id,
        'total_price': total_price,
        'is_subscription': is_subscription_booking
    })


@booking_bp.route('/api/cancel_booking/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking_route(booking_id):
    """Отменить бронирование (дублирует legacy-маршрут для надёжности)."""
    from internal.repositories.booking_repository import BookingRepository
    from internal.repositories.user_repository import UserRepository

    booking = BookingRepository.get_by_id(booking_id)
    if not booking:
        return jsonify({'success': False, 'error': 'Бронирование не найдено'}), 404

    if booking.user_id != current_user.id and not current_user.is_admin() and not current_user.is_manager():
        return jsonify({'success': False, 'error': 'Недостаточно прав'}), 403

    if booking.status == 'cancelled':
        return jsonify({'success': False, 'error': 'Бронирование уже отменено'}), 400

    if booking.status == 'completed':
        return jsonify({'success': False, 'error': 'Нельзя отменить завершённое бронирование'}), 400

    is_staff = current_user.is_admin() or current_user.is_manager()
    ok, err = booking_service.can_cancel_booking(
        booking, allow_staff=True, is_staff=is_staff,
    )
    if not ok:
        return jsonify({'success': False, 'error': err}), 400

    booking.status = 'cancelled'
    booking_service.refund_subscription_hours_on_cancel(booking)
    db.session.flush()

    user = UserRepository.get_by_id(booking.user_id)
    if user:
        UserRepository.sync_visitor_kind(user)

    db.session.commit()
    return jsonify({'success': True, 'message': 'Бронирование успешно отменено'})


@booking_bp.route('/api/booking/<int:booking_id>/extend_options', methods=['GET'])
@login_required
def extend_options_route(booking_id):
    """Варианты продления с учётом занятости после текущей брони."""
    from internal.repositories.booking_repository import BookingRepository

    booking = BookingRepository.get_by_id(booking_id)
    if not booking:
        return jsonify({'success': False, 'error': 'Бронирование не найдено'}), 404

    if booking.user_id != current_user.id and not current_user.is_admin() and not current_user.is_manager():
        return jsonify({'success': False, 'error': 'Нет доступа'}), 403

    if booking.tariff_type != 'hourly':
        return jsonify({'success': True, 'options': [],
                        'reason': 'Продление доступно только для почасовых броней'})

    today = datetime.now().date()
    now_time = datetime.now().time()
    if booking.booking_date < today or (
        booking.booking_date == today and booking.end_time <= now_time
    ):
        return jsonify({'success': True, 'options': [],
                        'reason': 'Время бронирования уже прошло'})

    duration = getattr(booking, 'duration_hours', None) or 0
    if duration >= 8:
        return jsonify({'success': True, 'options': [],
                        'reason': 'Достигнут максимум бронирования – 8 часов'})

    options = booking_service.get_extend_options(booking)
    reason = 'Следующие слоты заняты другим бронированием' if not options else None
    return jsonify({'success': True, 'options': options, 'reason': reason})


@booking_bp.route('/api/extend_booking', methods=['POST'])
@login_required
def extend_booking_route():
    """Продлить бронирование на выбранное количество часов."""
    from internal.repositories.booking_repository import BookingRepository
    from internal.services import booking_legacy_service

    data = request.get_json(silent=True) or {}
    booking_id = data.get('booking_id')
    hours = int(data.get('hours', 1) or 1)
    if not booking_id:
        return jsonify({'success': False, 'error': 'ID бронирования не указан'}), 400
    if hours < 1:
        return jsonify({'success': False, 'error': 'Укажите количество часов'}), 400

    booking = BookingRepository.get_by_id(booking_id)
    if not booking:
        return jsonify({'success': False, 'error': 'Бронирование не найдено'}), 404

    if booking.user_id != current_user.id and not current_user.is_admin() and not current_user.is_manager():
        return jsonify({'success': False, 'error': 'Нет доступа к этому бронированию'}), 403

    if booking.status != 'active':
        return jsonify({'success': False, 'error': 'Можно продлевать только активные бронирования'}), 400

    ok, err, payload = booking_service.extend_booking_hours(booking, hours)
    if not ok:
        return jsonify({'success': False, 'error': err}), 400

    db.session.commit()
    return jsonify({'success': True, **payload})


def register_booking_routes(app):
    app.register_blueprint(booking_bp)
