"""Сводная статистика по коворкингу."""
from internal.models.place import Place

_STATISTICS_KIND_ORDER = ('desk', 'room')


def place_statistics_kind(place):
    """Группа места для статистики: desk, room или None (служебные зоны).

    Переговорные в БД часто имеют kind=space (контейнер по стенам), а не room.
    """
    if not place:
        return None
    if place.kind == 'desk':
        return 'desk'
    if place.kind == 'room':
        return 'room'
    if place.kind == 'space':
        if place.is_meeting_room():
            return 'room'
        if place.allows_child_desks():
            return 'desk'
    return None


def aggregate_bookings_by_statistics_kind(bookings):
    """Число бронирований по группам desk / room (для графиков и отчётов)."""
    counts = {k: 0 for k in _STATISTICS_KIND_ORDER}
    for booking in bookings:
        kind = place_statistics_kind(booking.place if booking else None)
        if kind in counts:
            counts[kind] += 1
    return [(k, counts[k]) for k in _STATISTICS_KIND_ORDER if counts[k] > 0]


def _active_places():
    return Place.query.filter_by(active=True, maintenance=False).all()


def compute_desk_seat_capacity():
    """Суммарная вместимость всех рабочих столов (kind=desk)."""
    total = 0
    for place in _active_places():
        if place.kind != 'desk':
            continue
        total += max(1, place.capacity or 1)
    return total


def compute_meeting_room_count():
    """Количество переговорных (каждая комната — 1, без суммирования вместимости)."""
    codes = set()
    for place in _active_places():
        if place.kind in ('room', 'space') and place.is_meeting_room():
            codes.add(place.code)
    return len(codes)
