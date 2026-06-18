"""Сводная статистика по коворкингу."""
from internal.models.place import Place


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
    count = 0
    for place in _active_places():
        if place.kind == 'room' or place.is_meeting_room():
            count += 1
    return count
