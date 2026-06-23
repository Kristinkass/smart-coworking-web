"""
Модуль бронирования coworking space
Временные слоты: 15 минут
Минимальное бронирование: 30 минут (2 слота)
"""

from datetime import datetime, date, time, timedelta
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

from internal import models
from internal.models import db
from internal.models.schedule import (
    effective_close_minutes,
    format_close_time,
    minutes_to_time,
    time_to_minutes,
)


class TimeSlotStatus(Enum):
    FREE = "free"           # Полностью свободно
    PARTIAL = "partial"     # Частично занято (можно добавить людей)
    FULL = "full"           # Полностью занято


@dataclass
class TimeSlot:
    """15-минутный временной слот"""
    start_time: time
    end_time: time
    occupied_seats: int      # Сколько мест занято
    capacity: int            # Общая вместимость
    bookings: List[int]      # ID бронирований в этом слоте
    
    @property
    def available_seats(self) -> int:
        return self.capacity - self.occupied_seats
    
    @property
    def status(self) -> TimeSlotStatus:
        if self.occupied_seats == 0:
            return TimeSlotStatus.FREE
        elif self.occupied_seats < self.capacity:
            return TimeSlotStatus.PARTIAL
        else:
            return TimeSlotStatus.FULL
    
    def to_dict(self) -> Dict:
        return {
            'start_time': self.start_time.strftime('%H:%M'),
            'end_time': self.end_time.strftime('%H:%M'),
            'occupied_seats': self.occupied_seats,
            'capacity': self.capacity,
            'available_seats': self.available_seats,
            'status': self.status.value,
            'bookings': self.bookings
        }


# Константы
SLOT_DURATION_MINUTES = 15
MIN_BOOKING_SLOTS = 2      # Минимум 30 минут
MAX_BOOKING_SLOTS = 32     # Максимум 8 часов
WEEKLY_PERIOD_DAYS = 7
MONTHLY_PERIOD_DAYS = 30


def period_days_for_tariff(tariff_type: str) -> int:
    if tariff_type == 'weekly':
        return WEEKLY_PERIOD_DAYS
    if tariff_type == 'monthly':
        return MONTHLY_PERIOD_DAYS
    return 1


def booking_period_end(booking) -> date:
    """Последний день действия брони (включительно)."""
    days = period_days_for_tariff(getattr(booking, 'tariff_type', 'hourly') or 'hourly')
    if days > 1:
        return booking.booking_date + timedelta(days=days - 1)
    return booking.booking_date


def booking_covers_date(booking, target_date: date) -> bool:
    if booking.status != 'active':
        return False
    return booking.booking_date <= target_date <= booking_period_end(booking)


def effective_booking_times(booking, target_date: date, open_time: time, close_time: time):
    """Интервал занятости брони на конкретный день."""
    if not booking_covers_date(booking, target_date):
        return None, None
    if booking.tariff_type in ('weekly', 'monthly'):
        return open_time, close_time
    if booking.booking_date == target_date:
        return booking.start_time, booking.end_time
    return None, None


def slot_overlaps_booking(slot_start: time, slot_end: time, book_start: time, book_end: time) -> bool:
    return (
        book_start <= slot_start < book_end
        or book_start < slot_end <= book_end
        or (slot_start <= book_start and slot_end >= book_end)
    )


def get_child_desk_places(container):
    """Активные столы внутри закрытой локации (по container_code)."""
    if not container or not container.is_container() or not container.allows_child_desks():
        return []
    return [c for c in container.get_child_places() if c.kind == 'desk' and c.active]


def get_place_effective_capacity(place) -> int:
    """Вместимость для брони и шкалы: у зоны столов – сумма мест за столами."""
    if place.is_container() and place.allows_child_desks():
        children = get_child_desk_places(place)
        if children:
            return sum(c.capacity for c in children)
    return place.capacity


def _child_desk_occupies_slot(
    child,
    booking_date: date,
    slot_start: time,
    slot_end: time,
    open_time: time,
    close_time: time,
) -> bool:
    for booking in get_bookings_for_place_on_date(child.id, booking_date):
        b_start, b_end = effective_booking_times(booking, booking_date, open_time, close_time)
        if b_start is None:
            continue
        if slot_overlaps_booking(slot_start, slot_end, b_start, b_end):
            return True
    return False


def _slot_occupied_for_check(slot, exclude_booking_id: Optional[int]) -> int:
    occupied = slot.occupied_seats
    if exclude_booking_id and exclude_booking_id in slot.bookings:
        booking = models.Booking.query.get(exclude_booking_id)
        if booking:
            occupied -= booking.people_count
    return max(0, occupied)


def _interval_overlaps_bookings(
    place_id: int,
    booking_date: date,
    start_time: time,
    end_time: time,
    open_time: time,
    close_time: time,
    exclude_booking_id: Optional[int] = None,
) -> bool:
    """Есть ли активная бронь на месте, пересекающаяся с интервалом."""
    for booking in get_bookings_for_place_on_date(place_id, booking_date):
        b_start, b_end = effective_booking_times(booking, booking_date, open_time, close_time)
        if b_start is None:
            continue
        if exclude_booking_id and booking.id == exclude_booking_id:
            continue
        if slot_overlaps_booking(start_time, end_time, b_start, b_end):
            return True
    return False


def _child_desks_block_container(
    container,
    booking_date: date,
    start_time: time,
    end_time: time,
    open_time: time,
    close_time: time,
    exclude_booking_id: Optional[int] = None,
) -> Tuple[bool, str]:
    """Нельзя бронировать зону целиком, если занят хотя бы один стол внутри."""
    for child in get_child_desk_places(container):
        schedule = get_place_day_schedule(child.id, booking_date)
        if not schedule:
            continue
        start_idx = time_to_slot_index(start_time, open_time)
        end_idx = time_to_slot_index(end_time, open_time)
        for slot in schedule[start_idx:end_idx]:
            if _slot_occupied_for_check(slot, exclude_booking_id) > 0:
                return False, (
                    f'В помещении занят стол {child.code} '
                    f'с {slot.start_time.strftime("%H:%M")}'
                )
    return True, ''


def _parent_container_blocks_desk(
    place,
    booking_date: date,
    start_time: time,
    end_time: time,
    open_time: time,
    close_time: time,
    exclude_booking_id: Optional[int] = None,
) -> Tuple[bool, str]:
    """Нельзя бронировать стол, если локация забронирована целиком."""
    if not place.container_code:
        return True, ''
    parent = models.Place.query.filter_by(code=place.container_code).first()
    if not parent or not parent.is_container() or not parent.allows_child_desks():
        return True, ''
    if _interval_overlaps_bookings(
        parent.id, booking_date, start_time, end_time,
        open_time, close_time, exclude_booking_id,
    ):
        return False, f'Помещение {parent.code} забронировано целиком на это время'
    return True, ''


def get_bookings_for_place_on_date(place_id: int, booking_date: date) -> List:
    """Активные брони места, действующие в указанный день (включая недельные/месячные)."""
    bookings = models.Booking.query.filter(
        models.Booking.place_id == place_id,
        models.Booking.status == 'active',
    ).all()
    return [b for b in bookings if booking_covers_date(b, booking_date)]


def get_coworking_schedule_for_place(place_id: int, booking_date: date):
    """Получить расписание коворкинга для места на конкретную дату"""
    place = models.Place.query.get(place_id)
    if not place:
        return None, None, None

    floor = None
    if place.location and place.location.floor:
        floor = place.location.floor
    elif place.floor_id:
        floor = models.Floor.query.get(place.floor_id)

    coworking_id = floor.coworking_id if floor else None
    if not coworking_id:
        from internal.models.coworking import Coworking
        cw = Coworking.get_singleton()
        coworking_id = cw.id if cw else None
    if not coworking_id:
        return None, None, None
    
    # Получаем расписание на день недели
    day_of_week = booking_date.weekday()  # 0=Monday, 6=Sunday
    schedule = models.CoworkingSchedule.query.filter_by(
        id_coworking=coworking_id,
        day_of_week=day_of_week
    ).first()
    
    if not schedule or not schedule.is_active:
        return None, None, None
    
    return schedule.open_time, schedule.close_time, schedule.is_bookable


def schedule_hours_for_date(coworking_id: int, booking_date: date) -> float:
    """Число рабочих часов коворкинга в конкретный день по расписанию."""
    schedule = models.CoworkingSchedule.query.filter_by(
        id_coworking=coworking_id,
        day_of_week=booking_date.weekday(),
    ).first()
    if not schedule or not schedule.is_active or not schedule.is_bookable:
        return 0.0
    open_m = time_to_minutes(schedule.open_time)
    close_m = effective_close_minutes(schedule.open_time, schedule.close_time)
    return max(0.0, (close_m - open_m) / 60)


def total_available_hours_for_period(
    coworking_id: int,
    start_date: date,
    end_date: date,
    units: int = 1,
) -> float:
    """Суммарно доступных часов = units × часы по расписанию за каждый день периода."""
    if units <= 0:
        return 0.0
    day_hours = 0.0
    current = start_date
    while current <= end_date:
        day_hours += schedule_hours_for_date(coworking_id, current)
        current += timedelta(days=1)
    return units * day_hours


def get_default_coworking_id() -> Optional[int]:
    from internal.models.coworking import Coworking
    cw = Coworking.get_singleton()
    return cw.id if cw else None


def get_coworking_hour_range(coworking_id: int) -> Tuple[int, int]:
    """Минимальный и максимальный час для графиков по расписанию коворкинга."""
    schedules = models.CoworkingSchedule.query.filter_by(
        id_coworking=coworking_id,
        is_active=True,
        is_bookable=True,
    ).all()
    if not schedules:
        return 8, 22
    min_hour = min(s.open_time.hour for s in schedules)
    max_close = max(
        effective_close_minutes(s.open_time, s.close_time) // 60
        for s in schedules
    )
    return min_hour, max(max_close, min_hour + 1)


def generate_time_slots(open_time: time, close_time: time) -> List[time]:
    """Генерирует временные метки начала слотов для заданного расписания."""
    slots = []
    open_m = time_to_minutes(open_time)
    close_m = effective_close_minutes(open_time, close_time)
    current_m = open_m

    while current_m < close_m:
        slots.append(minutes_to_time(current_m))
        current_m += SLOT_DURATION_MINUTES

    return slots


def time_to_slot_index(t: time, open_time: time) -> int:
    """Конвертирует время в индекс слота относительно времени открытия"""
    minutes_from_start = (t.hour - open_time.hour) * 60 + (t.minute - open_time.minute)
    return max(0, minutes_from_start // SLOT_DURATION_MINUTES)


def slot_index_to_time(index: int, open_time: time) -> time:
    """Конвертирует индекс слота в время начала"""
    total_minutes = (open_time.hour * 60 + open_time.minute) + index * SLOT_DURATION_MINUTES
    hour = total_minutes // 60
    minute = total_minutes % 60
    return time(hour, minute)


def get_place_day_schedule(place_id: int, booking_date: date) -> List[TimeSlot]:
    """
    Получает расписание места на день - список всех 15-минутных слотов
    с информацией о занятости (с учетом расписания коворкинга)
    """
    from sqlalchemy import func
    
    place = models.Place.query.get(place_id)
    if not place:
        return []
    
    # Получаем расписание коворкинга
    open_time, close_time, is_bookable = get_coworking_schedule_for_place(place_id, booking_date)
    if not open_time or not close_time or not is_bookable:
        # Нет расписания или день нерабочий
        return []
    
    bookings = get_bookings_for_place_on_date(place_id, booking_date)
    parent_bookings = []
    if place.kind == 'desk' and place.container_code:
        parent = models.Place.query.filter_by(code=place.container_code).first()
        if parent and parent.is_container() and parent.allows_child_desks():
            parent_bookings = get_bookings_for_place_on_date(parent.id, booking_date)
    effective_capacity = get_place_effective_capacity(place)
    child_desks = get_child_desk_places(place)
    is_whole_space = place.kind in ('room', 'space') and not child_desks

    # Генерируем слоты по расписанию коворкинга
    slots = []
    time_slots = generate_time_slots(open_time, close_time)
    
    for i, start in enumerate(time_slots):
        # Конец слота = начало + 15 минут
        end_dt = datetime.combine(date.today(), start) + timedelta(minutes=SLOT_DURATION_MINUTES)
        end = end_dt.time()
        
        # Считаем сколько мест занято в этом слоте
        occupied = 0
        slot_bookings = []

        for booking in bookings:
            b_start, b_end = effective_booking_times(booking, booking_date, open_time, close_time)
            if b_start is None:
                continue
            if slot_overlaps_booking(start, end, b_start, b_end):
                occupied += booking.people_count
                slot_bookings.append(booking.id)

        # Если забронирована вся родительская зона, каждый стол внутри неё
        # считается занятым на этот же интервал.
        for booking in parent_bookings:
            b_start, b_end = effective_booking_times(booking, booking_date, open_time, close_time)
            if b_start is None:
                continue
            if slot_overlaps_booking(start, end, b_start, b_end):
                occupied = effective_capacity
                slot_bookings.append(booking.id)
                break

        # Зона столов: занятость любого стола блокирует бронь всей зоны
        if child_desks:
            for child in child_desks:
                if _child_desk_occupies_slot(
                    child, booking_date, start, end, open_time, close_time,
                ):
                    occupied = effective_capacity
                    break
        elif is_whole_space and slot_bookings:
            occupied = effective_capacity

        slots.append(TimeSlot(
            start_time=start,
            end_time=end,
            occupied_seats=occupied,
            capacity=effective_capacity,
            bookings=slot_bookings
        ))
    
    return slots


def check_availability_15min(
    place_id: int,
    booking_date: date,
    start_time: time,
    end_time: time,
    people_count: int = 1,
    exclude_booking_id: Optional[int] = None,
    tariff_type: str = 'hourly',
) -> Tuple[bool, str, List[TimeSlot]]:
    """
    Проверяет доступность временного интервала с учетом 15-минутных слотов
    и расписания коворкинга
    
    Returns:
        (is_available, message, affected_slots)
    """
    # Получаем расписание коворкинга
    open_time, close_time, is_bookable = get_coworking_schedule_for_place(place_id, booking_date)
    if not open_time or not close_time:
        return False, "Нет расписания для этого дня", []
    if not is_bookable:
        return False, "Бронирование недоступно в этот день", []
    
    # Запрет бронирования в прошлом (для недельного/месячного достаточно даты ≥ сегодня)
    now = datetime.now()
    if booking_date < now.date():
        return False, "Нельзя бронировать на прошедшую дату", []
    if booking_date == now.date() and tariff_type not in ('weekly', 'monthly'):
        start_dt = datetime.combine(booking_date, start_time)
        if start_dt < now.replace(second=0, microsecond=0):
            return False, "Нельзя бронировать на прошедшее время", []

    # Валидация времени
    if start_time >= end_time:
        return False, "Время окончания должно быть позже времени начала", []

    close_limit = effective_close_minutes(open_time, close_time)
    if time_to_minutes(start_time) < time_to_minutes(open_time) or time_to_minutes(end_time) > close_limit:
        close_label = format_close_time(open_time, close_time)
        return False, f"Бронирование возможно только с {open_time.strftime('%H:%M')} до {close_label}", []
    
    # Проверка кратности 15 минутам
    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    
    if start_minutes % SLOT_DURATION_MINUTES != 0:
        return False, f"Время начала должно быть кратно {SLOT_DURATION_MINUTES} минутам", []
    
    if end_minutes % SLOT_DURATION_MINUTES != 0:
        return False, f"Время окончания должно быть кратно {SLOT_DURATION_MINUTES} минутам", []
    
    # Проверка минимальной длительности
    duration_minutes = end_minutes - start_minutes
    if duration_minutes < MIN_BOOKING_SLOTS * SLOT_DURATION_MINUTES:
        return False, f"Минимальная продолжительность бронирования - {MIN_BOOKING_SLOTS * SLOT_DURATION_MINUTES} минут", []
    
    # Лимит 8 часов – только для почасового тарифа; недельный/месячный – весь рабочий день
    if tariff_type == 'hourly' and duration_minutes > MAX_BOOKING_SLOTS * SLOT_DURATION_MINUTES:
        return False, f"Максимальная продолжительность бронирования - {MAX_BOOKING_SLOTS * SLOT_DURATION_MINUTES} минут", []
    
    # Получаем расписание слотов
    schedule = get_place_day_schedule(place_id, booking_date)
    if not schedule:
        return False, "Место не найдено или нет расписания", []
    
    # Находим затронутые слоты
    start_idx = time_to_slot_index(start_time, open_time)
    end_idx = time_to_slot_index(end_time, open_time)
    affected_slots = schedule[start_idx:end_idx]
    
    # Проверяем каждый слот
    place = models.Place.query.get(place_id)
    if not place:
        return False, "Место не найдено", []
    
    ok_parent, msg_parent = _parent_container_blocks_desk(
        place, booking_date, start_time, end_time,
        open_time, close_time, exclude_booking_id,
    )
    if not ok_parent:
        return False, msg_parent, affected_slots

    if people_count > place.capacity:
        return False, f"Количество человек ({people_count}) превышает вместимость ({place.capacity})", []
    
    # Для переговорных – только целиком (space с категорией room или kind=room)
    is_meeting = place.kind == 'room' or (
        place.is_container() and (
            (place.category and place.category.kind == 'room')
            or (hasattr(place, 'is_meeting_room') and place.is_meeting_room())
        )
    )
    if is_meeting:
        if people_count != place.capacity:
            return False, f"Переговорную можно забронировать только целиком ({place.capacity} мест)", affected_slots
        for slot in affected_slots:
            # Исключаем текущее бронирование при проверке
            current_occupied = slot.occupied_seats
            if exclude_booking_id and exclude_booking_id in slot.bookings:
                booking = models.Booking.query.get(exclude_booking_id)
                if booking:
                    current_occupied -= booking.people_count
            
            if current_occupied > 0:
                return False, f"Переговорная занята с {slot.start_time.strftime('%H:%M')}", affected_slots
        return True, "Время доступно", affected_slots

    # Закрытая зона столов – бронь целиком: все столы внутри должны быть свободны
    if place.is_container() and place.allows_child_desks():
        ok_children, msg_children = _child_desks_block_container(
            place, booking_date, start_time, end_time,
            open_time, close_time, exclude_booking_id,
        )
        if not ok_children:
            return False, msg_children, affected_slots
        for slot in affected_slots:
            current_occupied = _slot_occupied_for_check(slot, exclude_booking_id)
            if current_occupied > 0:
                return False, (
                    f'Помещение занято с {slot.start_time.strftime("%H:%M")}'
                ), affected_slots
        return True, "Время доступно", affected_slots
    
    # Для одиночных столов
    if place.capacity == 1:
        for slot in affected_slots:
            current_occupied = slot.occupied_seats
            if exclude_booking_id and exclude_booking_id in slot.bookings:
                booking = models.Booking.query.get(exclude_booking_id)
                if booking:
                    current_occupied -= booking.people_count
            
            if current_occupied > 0:
                return False, f"Стол занят с {slot.start_time.strftime('%H:%M')}", affected_slots
        return True, "Время доступно", affected_slots
    
    # Для многоместных столов - проверяем каждый слот
    min_available = float('inf')
    for slot in affected_slots:
        current_occupied = slot.occupied_seats
        if exclude_booking_id and exclude_booking_id in slot.bookings:
            booking = models.Booking.query.get(exclude_booking_id)
            if booking:
                current_occupied -= booking.people_count
        
        available = place.capacity - current_occupied
        min_available = min(min_available, available)
        
        if people_count > available:
            return False, (
                f"Недостаточно мест с {slot.start_time.strftime('%H:%M')}. "
                f"Доступно {available}, требуется {people_count}"
            ), affected_slots
    
    return True, f"Доступно {min_available} мест на весь период", affected_slots


def check_period_availability(
    place_id: int,
    start_date: date,
    start_time: time,
    end_time: time,
    people_count: int = 1,
    tariff_type: str = 'hourly',
    exclude_booking_id: Optional[int] = None,
) -> Tuple[bool, str, List[TimeSlot]]:
    """Проверка доступности на весь период (неделя/месяц) или один день."""
    days = period_days_for_tariff(tariff_type)
    check_date = start_date
    last_slots: List[TimeSlot] = []

    for _ in range(days):
        day_start, day_end = start_time, end_time
        if tariff_type in ('weekly', 'monthly'):
            open_time, close_time, is_bookable = get_coworking_schedule_for_place(place_id, check_date)
            if not open_time or not close_time:
                return False, f"Нет расписания на {check_date.strftime('%d.%m.%Y')}", []
            if not is_bookable:
                return False, f"Бронирование недоступно {check_date.strftime('%d.%m.%Y')}", []
            day_start, day_end = open_time, close_time

        ok, msg, slots = check_availability_15min(
            place_id, check_date, day_start, day_end, people_count,
            exclude_booking_id=exclude_booking_id,
            tariff_type=tariff_type,
        )
        last_slots = slots
        if not ok:
            if days > 1:
                return False, f"Место занято {check_date.strftime('%d.%m.%Y')}: {msg}", slots
            return False, msg, slots
        check_date += timedelta(days=1)

    if days > 1:
        end_date = start_date + timedelta(days=days - 1)
        return True, f"Доступно с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}", last_slots
    return True, "Время доступно", last_slots


CANCEL_MIN_HOURS_BEFORE = 1


def refund_subscription_hours_on_cancel(booking):
    """Вернуть часы абонемента при отмене почасовой брони по абонементу."""
    if booking.tariff_type != 'hourly':
        return False

    from internal.models import Subscription

    subscription = None
    if booking.subscription_id:
        subscription = Subscription.query.get(booking.subscription_id)
    elif not booking.total_price and booking.people_count == 1:
        subscription = Subscription.query.filter(
            Subscription.user_id == booking.user_id,
            Subscription.active.is_(True),
            Subscription.start_date <= booking.booking_date,
            Subscription.end_date >= booking.booking_date,
        ).order_by(Subscription.end_date.desc()).first()

    if not subscription:
        return False

    refund_hours = booking.duration_hours or 0
    if refund_hours <= 0:
        return False

    subscription.hours_used = max(0, subscription.hours_used - int(round(refund_hours)))
    return True


def can_cancel_booking(booking, now=None, allow_staff=False, is_staff=False):
    """Отмена не позднее чем за CANCEL_MIN_HOURS_BEFORE ч до начала."""
    if booking.status in ('cancelled', 'completed'):
        return False, 'Бронирование уже завершено или отменено'
    if is_staff and allow_staff:
        return True, None
    now = now or datetime.now()
    start_dt = datetime.combine(booking.booking_date, booking.start_time)
    if start_dt - now < timedelta(hours=CANCEL_MIN_HOURS_BEFORE):
        return False, (
            f'Отмена возможна не позднее чем за {CANCEL_MIN_HOURS_BEFORE} ч до начала'
        )
    return True, None


def extend_booking_hours(booking, hours):
    """Продлить активную почасовую бронь на hours от текущего end_time."""
    from internal.services import booking_legacy_service

    hours = int(hours or 0)
    if hours < 1:
        return False, 'Укажите количество часов', None

    if booking.status != 'active':
        return False, 'Можно продлевать только активные бронирования', None
    if booking.tariff_type != 'hourly':
        return False, 'Продление доступно только для почасовых броней', None

    today = datetime.now().date()
    now_time = datetime.now().time()
    if booking.booking_date < today:
        return False, 'Нельзя продлить прошедшее бронирование', None
    if booking.booking_date == today and booking.end_time <= now_time:
        return False, 'Бронирование уже завершено по времени', None

    allowed = {opt['hours'] for opt in get_extend_options(booking)}
    if hours not in allowed:
        return False, 'Продление на это время недоступно – место занято', None

    new_end_time = booking_legacy_service.add_hours_to_time(booking.end_time, hours)
    start_dt = datetime.combine(booking.booking_date, booking.start_time)
    new_end_dt = datetime.combine(booking.booking_date, new_end_time)
    new_duration_hours = (new_end_dt - start_dt).total_seconds() / 3600

    booking.end_time = new_end_time
    booking.duration_hours = new_duration_hours
    additional_cost = 0.0
    if booking.place and booking.place.category:
        tariff = booking.place.category.get_tariff('hourly')
        if tariff:
            if booking.place.kind == 'room' or (
                booking.place.is_container() and booking.place.allows_child_desks()
            ):
                additional_cost = tariff.price * hours
            else:
                additional_cost = tariff.price * booking.people_count * hours
            booking.total_price = round(booking.total_price + additional_cost, 2)

    hours_label = '1 час' if hours == 1 else f'{hours} ч'
    return True, None, {
        'message': f'Бронирование продлено на {hours_label} (до {new_end_time.strftime("%H:%M")})',
        'new_end_time': booking.end_time.strftime('%H:%M'),
        'new_duration': round(booking.duration_hours, 1),
        'new_total_price': booking.total_price,
        'additional_cost': round(additional_cost, 2),
    }


def get_extend_options(booking) -> List[Dict]:
    """Варианты продления (только почасовые активные брони)."""
    from internal.services import booking_legacy_service

    if booking.tariff_type != 'hourly' or booking.status != 'active':
        return []

    duration = getattr(booking, 'duration_hours', None) or 0
    max_extra = max(0, int(8 - duration))
    if max_extra < 1:
        return []

    open_time, close_time, is_bookable = get_coworking_schedule_for_place(
        booking.place_id, booking.booking_date,
    )
    if not open_time or not close_time or not is_bookable:
        return []
    work_end = close_time

    others = [
        b for b in get_bookings_for_place_on_date(booking.place_id, booking.booking_date)
        if b.id != booking.id
    ]

    options = []
    for hours in range(1, max_extra + 1):
        new_end = booking_legacy_service.add_hours_to_time(booking.end_time, hours)
        if new_end > work_end:
            break

        conflict = False
        for other in others:
            b_start, b_end = effective_booking_times(
                other, booking.booking_date, open_time, close_time,
            )
            if b_start is None:
                continue
            if b_start < new_end and b_end > booking.end_time:
                conflict = True
                break
        if conflict:
            break

        label = '1 час' if hours == 1 else f'{hours} ч'
        options.append({'hours': hours, 'label': label})

    return options


def get_timegrid_for_place(place_id: int, booking_date: date) -> Dict:
    """
    Возвращает временную сетку для отображения на frontend
    Показывает для каждого 15-минутного слота сколько занято/свободно
    Включает open_time/close_time из расписания коворкинга
    """
    schedule = get_place_day_schedule(place_id, booking_date)
    place = models.Place.query.get(place_id)

    if not place:
        return {'error': 'Место не найдено'}

    # Получаем расписание коворкинга для определения open/close time
    open_time, close_time, is_bookable = get_coworking_schedule_for_place(place_id, booking_date)
    if not open_time or not close_time:
        return {'error': 'Коворкинг не работает в этот день'}

    effective_capacity = get_place_effective_capacity(place)
    is_desk_zone = place.is_container() and place.allows_child_desks()

    if not schedule:
        message = 'Бронирование недоступно в этот день'
        if not is_bookable:
            close_label = format_close_time(open_time, close_time)
            message = f'Бронирование закрыто (режим {open_time.strftime("%H:%M")}–{close_label})'
        return {
            'place_id': place_id,
            'place_code': place.code,
            'place_name': place.name,
            'capacity': effective_capacity,
            'zone_capacity': effective_capacity if is_desk_zone else None,
            'date': booking_date.strftime('%Y-%m-%d'),
            'open_time': open_time.strftime('%H:%M'),
            'close_time': format_close_time(open_time, close_time),
            'is_bookable': bool(is_bookable),
            'schedule_message': message,
            'slot_duration_minutes': SLOT_DURATION_MINUTES,
            'slots': [],
        }

    from datetime import datetime
    now = datetime.now()
    is_today = booking_date == now.date()
    current_time = now.time()

    if not is_bookable:
        close_label = format_close_time(open_time, close_time)
        return {
            'place_id': place_id,
            'place_code': place.code,
            'place_name': place.name,
            'capacity': effective_capacity,
            'zone_capacity': effective_capacity if is_desk_zone else None,
            'date': booking_date.strftime('%Y-%m-%d'),
            'open_time': open_time.strftime('%H:%M'),
            'close_time': close_label,
            'is_bookable': False,
            'schedule_message': f'Бронирование закрыто (режим {open_time.strftime("%H:%M")}–{close_label})',
            'slot_duration_minutes': SLOT_DURATION_MINUTES,
            'slots': [],
        }

    close_limit = effective_close_minutes(open_time, close_time)
    now_minutes = time_to_minutes(current_time) if is_today else None

    slots_data = []
    for slot in schedule:
        is_past = False
        if is_today:
            slot_start = slot.start_time
            is_past = (slot_start.hour < current_time.hour or
                      (slot_start.hour == current_time.hour and slot_start.minute < current_time.minute))

        slots_data.append({
            'time': slot.start_time.strftime('%H:%M'),
            'occupied': slot.occupied_seats,
            'capacity': slot.capacity,
            'available': slot.available_seats,
            'status': slot.status.value,
            'percent_full': round(slot.occupied_seats / slot.capacity * 100, 1) if slot.capacity > 0 else 0,
            'is_past': is_past
        })

    has_future_bookable = any(
        not s['is_past'] and s['status'] != 'full' and s['available'] > 0
        for s in slots_data
    )
    if not is_today and slots_data:
        has_future_bookable = True
    if is_today and now_minutes is not None and now_minutes >= close_limit:
        has_future_bookable = False

    schedule_message = None
    if not has_future_bookable:
        close_label = format_close_time(open_time, close_time)
        if is_today and now_minutes is not None and now_minutes >= close_limit:
            schedule_message = f'Коворкинг уже закрыт (режим {open_time.strftime("%H:%M")}–{close_label})'
        else:
            schedule_message = 'Нет доступного времени для бронирования на этот день'

    return {
        'place_id': place_id,
        'place_code': place.code,
        'place_name': place.name,
        'capacity': effective_capacity,
        'zone_capacity': effective_capacity if is_desk_zone else None,
        'date': booking_date.strftime('%Y-%m-%d'),
        'open_time': open_time.strftime('%H:%M'),
        'close_time': format_close_time(open_time, close_time),
        'is_bookable': has_future_bookable,
        'schedule_message': schedule_message,
        'slot_duration_minutes': SLOT_DURATION_MINUTES,
        'slots': slots_data,
    }


def find_available_slots(
    place_id: int,
    booking_date: date,
    duration_minutes: int = 30,
    people_count: int = 1
) -> List[Tuple[time, time]]:
    """
    Находит все доступные временные интервалы заданной длительности
    """
    schedule = get_place_day_schedule(place_id, booking_date)
    place = models.Place.query.get(place_id)
    
    if not place or not schedule:
        return []
    
    slots_needed = duration_minutes // SLOT_DURATION_MINUTES
    available_intervals = []
    
    for i in range(len(schedule) - slots_needed + 1):
        window = schedule[i:i + slots_needed]
        
        # Проверяем все слоты в окне
        is_available = True
        for slot in window:
            if people_count > slot.available_seats:
                is_available = False
                break
        
        if is_available:
            start = window[0].start_time
            end = window[-1].end_time
            available_intervals.append((start, end))
    
    return available_intervals

