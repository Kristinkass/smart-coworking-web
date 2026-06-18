"""Legacy booking availability and slot helpers."""
from datetime import datetime, date, timedelta

from sqlalchemy import func

from internal import models
from internal.models import db


def is_time_slot_available(place_id, booking_date, start_time, end_time, exclude_booking_id=None, people_count=1, user_id=None, tariff_type='hourly'):
    """Проверка, свободен ли слот для бронирования с учетом количества человек.

    people_count: количество человек для бронирования (по умолчанию 1)
    
    Логика:
      - Для одиночных столов (capacity=1): либо свободно, либо занято
      - Для многоместных столов (capacity>1): проверяем сумму people_count существующих броней
      - Для переговорных: только целиком
      - Для weekly/monthly: ослабленные проверки, исключаем собственные бронирования
    """
    try:
        # Конвертируем строки в объекты
        if isinstance(start_time, str):
            start_time = datetime.strptime(start_time, '%H:%M').time()
        if isinstance(end_time, str):
            end_time = datetime.strptime(end_time, '%H:%M').time()
        if isinstance(booking_date, str):
            booking_date = datetime.strptime(booking_date, '%Y-%m-%d').date()
        if isinstance(people_count, str):
            people_count = int(people_count)
        if people_count is None:
            people_count = 1

        place = models.Place.query.get(place_id)
        if not place:
            return False, "Место не найдено"

        # Проверка флага обслуживания
        if place.is_on_maintenance():
            return False, "Место находится на обслуживании"

        # Проверка времени пройденного
        now = datetime.now()
        if booking_date < now.date():
            return False, "Нельзя бронировать на прошедшую дату"

        if (
            booking_date == now.date()
            and tariff_type not in ('weekly', 'monthly')
            and start_time < now.time()
        ):
            return False, "Нельзя бронировать на прошедшее время"

        # Проверка корректности времени (для абонементов start==end допустимо)
        if tariff_type not in ('weekly', 'monthly') and start_time >= end_time:
            return False, "Время окончания должно быть позже времени начала"

        from internal.services.booking_service import get_coworking_schedule_for_place
        open_time, close_time, is_bookable = get_coworking_schedule_for_place(place_id, booking_date)
        if not open_time or not close_time or not is_bookable:
            return False, "Коворкинг не работает в выбранный день"
        if start_time < open_time or end_time > close_time:
            return False, (
                f"Бронирование возможно только с {open_time.strftime('%H:%M')} "
                f"до {close_time.strftime('%H:%M')}"
            )

        start_dt = datetime.combine(date.today(), start_time)
        end_dt = datetime.combine(date.today(), end_time)
        duration_hours = (end_dt - start_dt).seconds / 3600

        # Проверки длительности только для почасового тарифа
        if tariff_type not in ('weekly', 'monthly'):
            if duration_hours < 0.25:
                return False, "Минимальная продолжительность бронирования - 15 минут"

            # Проверка кратности 15 минутам (0.25 часа)
            if (duration_hours * 60) % 15 != 0:
                return False, "Забронировать можно только на промежутки, кратные 15 минутам (15 мин, 30 мин, 45 мин, 1 час и т.д.)"

            if duration_hours > 8:
                return False, "Максимальная продолжительность бронирования - 8 часов"

        # Проверка количества человек
        if people_count < 1:
            return False, "Количество человек должно быть не менее 1"
        if people_count > place.capacity:
            return False, f"Количество человек ({people_count}) превышает вместимость стола ({place.capacity})"

        from internal.services.booking_service import (
            get_bookings_for_place_on_date,
            effective_booking_times,
            get_coworking_schedule_for_place,
        )

        open_time, close_time, _ = get_coworking_schedule_for_place(place_id, booking_date)
        if not open_time:
            open_time = work_start
        if not close_time:
            close_time = work_end

        def has_overlap():
            for other in get_bookings_for_place_on_date(place_id, booking_date):
                if exclude_booking_id and other.id == exclude_booking_id:
                    continue
                if user_id and other.user_id == user_id and other.tariff_type in ('weekly', 'monthly'):
                    continue
                b_start, b_end = effective_booking_times(other, booking_date, open_time, close_time)
                if b_start is None:
                    continue
                if b_start < end_time and b_end > start_time:
                    return True
            return False

        # Переговорные - только целиком
        if place.kind == 'room':
            if has_overlap():
                return False, "Переговорная уже забронирована на это время"
            return True, "Время доступно"

        # Для одиночных столов - простая проверка
        if place.capacity == 1:
            if has_overlap():
                return False, "Стол уже забронирован на это время"
            return True, "Время доступно"

        # Для многоместных столов - проверяем сумму people_count
        from sqlalchemy import func
        overlap_query = models.Booking.query.filter(
            models.Booking.place_id == place_id,
            models.Booking.booking_date == booking_date,
            models.Booking.status == 'active',
            models.Booking.start_time < end_time,
            models.Booking.end_time > start_time,
        )
        if exclude_booking_id:
            overlap_query = overlap_query.filter(models.Booking.id != exclude_booking_id)
        if user_id:
            overlap_query = overlap_query.filter(models.Booking.user_id != user_id)
        
        # Считаем сумму people_count для существующих броней (исключая текущего пользователя)
        current_occupancy = db.session.query(func.sum(models.Booking.people_count)).filter(
            models.Booking.place_id == place_id,
            models.Booking.booking_date == booking_date,
            models.Booking.status == 'active',
            models.Booking.start_time < end_time,
            models.Booking.end_time > start_time,
        )
        if user_id:
            current_occupancy = current_occupancy.filter(models.Booking.user_id != user_id)
        current_occupancy = current_occupancy.scalar() or 0

        if exclude_booking_id:
            # Вычитаем people_count текущего бронирования (для редактирования)
            current_booking = models.Booking.query.get(exclude_booking_id)
            if current_booking:
                current_occupancy -= current_booking.people_count

        available_seats = place.capacity - current_occupancy
        
        if people_count > available_seats:
            return False, f"Недостаточно свободных мест. Занято {current_occupancy}/{place.capacity}, доступно {available_seats}, требуется {people_count}"
        
        return True, f"Доступно {available_seats} мест из {place.capacity} (занято {current_occupancy})"
        
    except Exception as e:
        return False, f"Ошибка проверки: {str(e)}"


def add_hours_to_time(time_obj, hours):
    dummy_date = datetime(2000, 1, 1)
    combined = datetime.combine(dummy_date, time_obj)
    new_time = combined + timedelta(hours=hours)
    return new_time.time()


def update_booking_statuses():
    # обновлять статусы бронирований
    try:
        now = datetime.now()
        today = now.date()
        current_time = now.time()

        # активные бронирования которые надо завершить
        bookings_to_complete = models.Booking.query.filter(
            models.Booking.status == 'active',
            db.or_(
                models.Booking.booking_date < today,
                db.and_(
                    models.Booking.booking_date == today,
                    models.Booking.end_time <= current_time
                )
            )
        ).all()

        for booking in bookings_to_complete:
            booking.status = 'completed'

        if bookings_to_complete:
            db.session.commit()
            print(f"Обновлено {len(bookings_to_complete)} бронирований")
            return len(bookings_to_complete)

    except Exception as e:
        print(f"Ошибка обновления статусов: {e}")
        db.session.rollback()

    return 0


def get_time_slots_for_place(place_id, booking_date, interval_minutes=15):
    """Генерация временных слотов на основе расписания коворкинга из БД

    Args:
        place_id: ID места
        booking_date: дата бронирования (date объект или строка YYYY-MM-DD)
        interval_minutes: интервал в минутах (по умолчанию 15)

    Returns:
        dict: {'slots': [...], 'open_time': 'HH:MM', 'close_time': 'HH:MM'} или None
    """
    from booking_module import get_coworking_schedule_for_place

    # Конвертируем дату если нужно
    if isinstance(booking_date, str):
        booking_date = datetime.strptime(booking_date, '%Y-%m-%d').date()

    # Получаем расписание коворкинга
    open_time, close_time, is_bookable = get_coworking_schedule_for_place(place_id, booking_date)
    if not open_time or not close_time or not is_bookable:
        return None

    slots = []
    current = datetime.combine(booking_date, open_time)
    end = datetime.combine(booking_date, close_time)

    while current < end:
        slots.append({
            'start': current.strftime("%H:%M"),
            'label': current.strftime("%H:%M")
        })
        current = current + timedelta(minutes=interval_minutes)

    return {
        'slots': slots,
        'open_time': open_time.strftime("%H:%M"),
        'close_time': close_time.strftime("%H:%M")
    }


def get_occupied_times_for_date(place_id, date_obj):
    # занятые времена места на конкретную дату
    bookings = models.Booking.query.filter(
        models.Booking.place_id == place_id,
        models.Booking.booking_date == date_obj,
        models.Booking.status == 'active'
    ).order_by(models.Booking.start_time).all()

    occupied_times = []
    for booking in bookings:
        occupied_times.append({
            'start': booking.start_time.strftime('%H:%M'),
            'end': booking.end_time.strftime('%H:%M')
        })

    return occupied_times


def format_duration(hours):
    """Преобразует часы в человекочитаемый русский формат: 'X ч Y мин'"""
    if not hours:
        return '0 мин'
    total_minutes = int(round(hours * 60))
    h = total_minutes // 60
    m = total_minutes % 60
    if h > 0 and m > 0:
        return f"{h} ч {m} мин"
    elif h > 0:
        return f"{h} ч"
    else:
        return f"{m} мин"


def format_duration_mins(hours):
    """Возвращает только минуты (для отчетов)"""
    if not hours:
        return 0
    return int(round(hours * 60))

