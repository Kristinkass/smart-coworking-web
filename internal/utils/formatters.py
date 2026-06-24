"""Template and display helpers."""
from datetime import datetime, timezone


def _normalize_place_segment(code, location_code=''):
    """Сегмент кода с префиксом зоны локации."""
    code = (code or '').strip()
    location_code = (location_code or '').strip()
    if not code:
        return location_code
    if location_code and not (code == location_code or code.startswith(f'{location_code}-')):
        return f'{location_code}-{code.lstrip("-")}'
    return code


def _place_location_code(place):
    if not place:
        return ''
    if hasattr(place, 'location') and place.location:
        return (place.location.code or '').strip()
    return (getattr(place, 'location_code', None) or '').strip()


def format_place_code(place):
    """Код места (стол, комната) без иерархии."""
    if not place:
        return '–'
    return _normalize_place_segment(getattr(place, 'code', ''), _place_location_code(place)) or '–'


def format_place_container(place):
    """Локация-контейнер для стола; пусто, если стол в открытом коридоре."""
    if not place or not hasattr(place, 'is_desk') or not place.is_desk():
        return ''
    container = place.get_container_place() if hasattr(place, 'get_container_place') else None
    if not container:
        return ''
    name = (container.name or '').strip()
    code = format_place_code(container)
    if name and code:
        return f'{name} ({code})'
    return name or code or ''


def format_place_full_code(place):
    """Полный иерархический код: локация · контейнер · место."""
    if not place:
        return '–'
    loc_code = _place_location_code(place)
    segments = []
    if loc_code:
        segments.append(loc_code)
    if hasattr(place, 'is_desk') and place.is_desk():
        container = place.get_container_place() if hasattr(place, 'get_container_place') else None
        if container:
            container_loc = _place_location_code(container) or loc_code
            container_seg = _normalize_place_segment(container.code, container_loc)
            if container_seg and container_seg not in segments:
                segments.append(container_seg)
    place_seg = _normalize_place_segment(getattr(place, 'code', ''), loc_code)
    if place_seg and place_seg not in segments:
        segments.append(place_seg)
    return ' · '.join(segments) if segments else '–'


def format_place_full_code_dict(place_dict, by_code=None):
    """Полный код для объекта места из API карты."""
    if not place_dict:
        return '–'
    loc_code = (place_dict.get('location_code') or '').strip()
    segments = []
    if loc_code:
        segments.append(loc_code)
    if place_dict.get('kind') == 'desk':
        container_code = (place_dict.get('container_code') or '').strip()
        if container_code:
            parent = (by_code or {}).get(container_code) or {}
            parent_loc = (parent.get('location_code') or loc_code).strip()
            container_seg = _normalize_place_segment(container_code, parent_loc or loc_code)
            if container_seg and container_seg not in segments:
                segments.append(container_seg)
    place_seg = _normalize_place_segment(place_dict.get('code'), loc_code)
    if place_seg and place_seg not in segments:
        segments.append(place_seg)
    return ' · '.join(segments) if segments else '–'


def format_money(amount):
    """Сумма в рублях без копеек для отображения."""
    if amount is None:
        return '0 ₽'
    return f'{int(round(float(amount)))} ₽'


def format_local_datetime(dt):
    """Показать UTC-время из БД в локальном часовом поясе пользователя."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone()
    else:
        dt = dt.astimezone()
    return dt.strftime('%d.%m.%Y %H:%M')


def get_type_name(type_code):
    type_names = {
        'desk': 'Рабочий стол',
        'room': 'Переговорная',
        'space': 'Помещение',
    }
    return type_names.get(type_code, type_code)


def normalize_place_kind(kind):
    """Внутренний kind → группа для статистики и абонементов."""
    if kind in ('space', 'room'):
        return 'room'
    return kind


def get_status_name(status_code):
    status_names = {
        'free': 'Свободно',
        'occupied': 'Занято сейчас',
        'reserved': 'Забронировано',
        'maintenance': 'На обслуживании',
        'active': 'Активно',
        'completed': 'Завершено',
        'cancelled': 'Отменено',
    }
    return status_names.get(status_code, status_code)


def render_stars(rating):
    if not rating:
        return '<span style="color: #d1d5db;">☆☆☆☆☆</span>'
    full_stars = int(rating)
    half_star = rating % 1 >= 0.5
    empty_stars = 5 - full_stars - (1 if half_star else 0)
    stars_html = '★' * full_stars
    if half_star:
        stars_html += '½'
    stars_html += '☆' * empty_stars
    return f'<span style="color: #F59E0B;">{stars_html}</span>'


def format_booking_location(place):
    """Полная подпись локации для карточки бронирования."""
    if not place:
        return '–'
    full_code = format_place_full_code(place)
    container = place.get_container_place() if place.is_desk() else None
    if container:
        loc = container.location or place.location
        zone_label = f'{loc.name} ({loc.code})' if loc else ''
        container_code = format_place_full_code(container)
        return f'{zone_label}, локация {container_code}, стол {full_code}'.strip(', ')
    loc = place.location
    if loc and place.is_container():
        return f'{loc.name} ({loc.code}), {full_code}'
    if loc:
        return f'{loc.name} ({loc.code}), {full_code}'
    return full_code


def format_duration(hours):
    if hours is None:
        return '0 ч'
    if hours < 1:
        return f'{int(hours * 60)} мин'
    h = int(hours)
    m = int((hours - h) * 60)
    if m:
        return f'{h} ч {m} мин'
    return f'{h} ч'


def format_duration_mins(hours):
    if hours is None:
        return '0 мин'
    return f'{int(hours * 60)} мин'


def get_tariff_type_label(tariff_type):
    labels = {
        'hourly': 'Почасовой',
        'weekly': 'Недельный',
        'monthly': 'Месячный',
    }
    return labels.get(tariff_type, tariff_type or '-')


def format_booking_tariff_label(booking):
    """Подпись тарифа или абонемента для списков и истории."""
    if not booking:
        return '–'
    if booking.subscription_id:
        if booking.subscription:
            return f'Абонемент: {booking.subscription.name}'
        return 'Абонемент'
    label = get_tariff_type_label(booking.tariff_type)
    if booking.tariff_type in ('hourly', 'weekly', 'monthly'):
        return f'{label} тариф'
    return label


REPORT_SECTIONS = [
    {'key': 'hourly', 'title': 'Почасовые бронирования', 'mode': 'time', 'value_label': 'Длительность'},
    {'key': 'subscription', 'title': 'Бронирования по абонементу', 'mode': 'subscription', 'value_label': ''},
    {'key': 'weekly', 'title': 'Недельные тарифы', 'mode': 'period', 'value_label': 'Срок'},
    {'key': 'monthly', 'title': 'Месячные тарифы', 'mode': 'period', 'value_label': 'Срок'},
]


def format_booking_period_range(booking):
    """Диапазон дат для недельных/месячных тарифов."""
    end = booking.period_end_date
    return f"{booking.booking_date.strftime('%d.%m.%Y')} - {end.strftime('%d.%m.%Y')}"


def format_booking_time_range(booking):
    """Интервал времени для почасовых и абонементных броней."""
    start = booking.start_time.strftime('%H:%M') if booking.start_time else '-'
    end = booking.end_time.strftime('%H:%M') if booking.end_time else '-'
    return f'{start} - {end}'


def format_booking_time_or_period(booking):
    """Время для почасовых/абонементных или период для недельных/месячных."""
    if booking.tariff_type in ('weekly', 'monthly'):
        return format_booking_period_range(booking)
    return format_booking_time_range(booking)


def format_booking_duration_display(booking):
    """Единица длительности в зависимости от типа тарифа."""
    if booking.subscription_id:
        return '–'
    if booking.tariff_type == 'weekly':
        return '7 дней'
    if booking.tariff_type == 'monthly':
        return '30 дней'
    return format_duration(booking.duration_hours)


def format_booking_subscription_name(booking):
    if booking.subscription:
        return booking.subscription.name
    return '-'


def group_bookings_for_report(bookings):
    """Разделение бронирований: сначала по типу тарифа, затем абонемент для почасовых."""
    groups = {
        'hourly': [],
        'subscription': [],
        'weekly': [],
        'monthly': [],
    }
    for booking in bookings:
        if booking.tariff_type == 'weekly':
            groups['weekly'].append(booking)
        elif booking.tariff_type == 'monthly':
            groups['monthly'].append(booking)
        elif booking.subscription_id:
            groups['subscription'].append(booking)
        else:
            groups['hourly'].append(booking)
    return groups


def build_report_stats(bookings):
    """Сводная статистика для страницы отчётов (plain dict, ключи для Jinja через [])."""
    grouped = group_bookings_for_report(bookings)
    total_revenue = sum(
        b.total_price for b in bookings if b.status == 'completed'
    )
    unique_users = len({b.user_id for b in bookings})

    hourly_hours = sum(b.duration_hours for b in grouped['hourly'])

    tariff_summary = []
    if grouped['hourly']:
        tariff_summary.append({
            'label': 'Почасовые',
            'detail': format_duration(hourly_hours),
        })
    if grouped['weekly']:
        tariff_summary.append({
            'label': 'Недельные',
            'detail': f'{len(grouped["weekly"])} шт.',
        })
    if grouped['monthly']:
        tariff_summary.append({
            'label': 'Месячные',
            'detail': f'{len(grouped["monthly"])} шт.',
        })

    subscription_summary = []
    sub_name_counts = {}
    seen_sub_ids = set()
    for booking in grouped['subscription']:
        sub_id = booking.subscription_id
        if not sub_id or sub_id in seen_sub_ids:
            continue
        seen_sub_ids.add(sub_id)
        name = format_booking_subscription_name(booking)
        sub_name_counts[name] = sub_name_counts.get(name, 0) + 1
    for name in sorted(sub_name_counts):
        subscription_summary.append({
            'label': name,
            'detail': f"{sub_name_counts[name]} шт.",
        })

    by_place_type = {}
    for booking in bookings:
        if not (booking.place and booking.place.kind):
            continue
        kind = booking.place.kind
        if kind not in by_place_type:
            by_place_type[kind] = {
                'count': 0,
                'total_revenue': 0,
            }
        by_place_type[kind]['count'] += 1
        if booking.status == 'completed':
            by_place_type[kind]['total_revenue'] += booking.total_price

    for kind_data in by_place_type.values():
        kind_data['total_revenue'] = int(round(kind_data['total_revenue']))

    user_stats = {}
    for booking in bookings:
        if booking.status != 'completed':
            continue
        user_id = booking.user_id
        if user_id not in user_stats:
            user_stats[user_id] = {
                'username': booking.user.username,
                'phone': booking.user.phone,
                'booking_count': 0,
                'total_spent': 0,
            }
        user_stats[user_id]['booking_count'] += 1
        user_stats[user_id]['total_spent'] += booking.total_price

    top_users = sorted(user_stats.values(), key=lambda x: x['total_spent'], reverse=True)[:10]
    for u in top_users:
        u['total_spent'] = int(round(u['total_spent']))

    return {
        'total_bookings': len(bookings),
        'total_revenue': int(round(total_revenue)),
        'unique_users': unique_users,
        'tariff_summary': tariff_summary,
        'subscription_summary': subscription_summary,
        'by_place_type': by_place_type,
        'top_users': top_users,
    }, grouped
