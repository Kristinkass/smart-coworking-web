"""Tests for booking cancel/extend API."""
from datetime import date, time, timedelta

from internal.models import Booking, CategoryTariff, User, db


def test_client_can_cancel_own_booking(auth_client, app, sample_booking):
    with app.app_context():
        r = auth_client.post(f'/api/cancel_booking/{sample_booking}', json={})
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        booking = db.session.get(Booking, sample_booking)
        assert booking.status == 'cancelled'


def test_client_cannot_cancel_other_booking(auth_client, app, sample_booking):
    with app.app_context():
        other = User.query.filter_by(email='other@test.com').first()
        booking = db.session.get(Booking, sample_booking)
        booking.user_id = other.id
        db.session.commit()

    r = auth_client.post(f'/api/cancel_booking/{sample_booking}', json={})
    assert r.status_code == 403


def test_cannot_cancel_completed_booking(auth_client, app, sample_booking):
    with app.app_context():
        booking = db.session.get(Booking, sample_booking)
        booking.status = 'completed'
        db.session.commit()

    r = auth_client.post(f'/api/cancel_booking/{sample_booking}', json={})
    assert r.status_code == 400
    assert 'заверш' in r.get_json()['error'].lower()


def test_cancel_requires_auth(client, sample_booking):
    r = client.post(f'/api/cancel_booking/{sample_booking}', json={})
    assert r.status_code == 401


def test_extend_booking_today(auth_client, app):
    from datetime import datetime
    now = datetime.now()
    if now.hour >= 20:
        import pytest
        pytest.skip('Слишком поздно для теста продления')

    start_h = max(8, now.hour)
    end_h = min(start_h + 2, 21)
    start_t = time(start_h, 0)
    end_t = time(end_h, 0)
    # Бронь должна ещё не закончиться
    if now.time() >= end_t:
        end_t = time(min(now.hour + 2, 21), 0)
    if now.time() >= end_t:
        import pytest
        pytest.skip('Нет подходящего окна времени')

    with app.app_context():
        from internal.models import Place
        user = User.query.filter_by(email='client@test.com').first()
        place = Place.query.filter_by(code='1Б-T01').first()
        booking = Booking(
            user_id=user.id,
            place_id=place.id,
            booking_date=date.today(),
            start_time=start_t,
            end_time=end_t,
            duration_hours=float(end_h - start_h),
            total_price=250.0,
            tariff_type='hourly',
            status='active',
        )
        db.session.add(booking)
        db.session.commit()
        bid = booking.id

    r = auth_client.post('/api/extend_booking', json={'booking_id': bid, 'hours': 1})
    assert r.status_code == 200, r.get_json()
    with app.app_context():
        b = db.session.get(Booking, bid)
        assert (b.end_time.hour, b.end_time.minute) >= (end_t.hour, end_t.minute)


def test_cannot_cancel_within_one_hour(auth_client, app):
    """Отмена запрещена менее чем за 1 ч до начала (CANCEL_MIN_HOURS_BEFORE)."""
    from datetime import datetime
    now = datetime.now()
    start_dt = now + timedelta(minutes=30)
    if start_dt.date() != date.today():
        import pytest
        pytest.skip('Нет подходящего окна для теста отмены')
    start_t = start_dt.time().replace(second=0, microsecond=0)
    end_dt = start_dt + timedelta(hours=2)
    end_t = end_dt.time().replace(second=0, microsecond=0)

    with app.app_context():
        from internal.models import Place
        user = User.query.filter_by(email='client@test.com').first()
        place = Place.query.filter_by(code='1Б-T01').first()
        booking = Booking(
            user_id=user.id,
            place_id=place.id,
            booking_date=date.today(),
            start_time=start_t,
            end_time=end_t,
            duration_hours=2.0,
            total_price=500.0,
            tariff_type='hourly',
            status='active',
        )
        db.session.add(booking)
        db.session.commit()
        bid = booking.id

    r = auth_client.post(f'/api/cancel_booking/{bid}', json={})
    assert r.status_code == 400
    assert '1' in r.get_json()['error']


def test_extend_booking_two_hours(auth_client, app):
    from datetime import datetime
    now = datetime.now()
    if now.hour >= 19:
        import pytest
        pytest.skip('Слишком поздно для теста продления на 2ч')

    start_h = max(8, now.hour)
    end_h = min(start_h + 2, 20)
    start_t = time(start_h, 0)
    end_t = time(end_h, 0)
    if now.time() >= end_t:
        import pytest
        pytest.skip('Нет подходящего окна времени')

    with app.app_context():
        from internal.models import Place
        user = User.query.filter_by(email='client@test.com').first()
        place = Place.query.filter_by(code='1Б-T01').first()
        booking = Booking(
            user_id=user.id,
            place_id=place.id,
            booking_date=date.today(),
            start_time=start_t,
            end_time=end_t,
            duration_hours=float(end_h - start_h),
            total_price=250.0,
            tariff_type='hourly',
            status='active',
        )
        db.session.add(booking)
        db.session.commit()
        bid = booking.id
        old_end = end_t

    r = auth_client.post('/api/extend_booking', json={'booking_id': bid, 'hours': 2})
    assert r.status_code == 200, r.get_json()
    with app.app_context():
        b = db.session.get(Booking, bid)
        expected_h = min(old_end.hour + 2, 22)
        assert b.end_time.hour == expected_h


def test_weekly_booking_blocks_next_day(auth_client, app):
    from internal.models import Place

    start = date.today() + timedelta(days=5)
    with app.app_context():
        user = User.query.filter_by(email='client@test.com').first()
        place = Place.query.filter_by(code='1Б-T01').first()
        place_id = place.id
        weekly = Booking(
            user_id=user.id,
            place_id=place_id,
            booking_date=start,
            start_time=time(10, 0),
            end_time=time(18, 0),
            duration_hours=56.0,
            total_price=3500.0,
            tariff_type='weekly',
            status='active',
        )
        db.session.add(weekly)
        db.session.commit()

    next_day = (start + timedelta(days=1)).strftime('%Y-%m-%d')
    r = auth_client.post('/api/booking/create', json={
        'place_id': place_id,
        'date': next_day,
        'start_time': '12:00',
        'end_time': '13:00',
        'people_count': 1,
        'tariff_type': 'hourly',
    })
    assert r.status_code == 400
    assert 'занят' in r.get_json()['error'].lower()


def test_weekly_price_scales_with_people(auth_client, app):
    from internal.models import Place, PlaceCategory  # noqa: F811

    start = date.today() + timedelta(days=10)
    with app.app_context():
        place = Place.query.filter_by(code='1Б-T01').first()
        cat = PlaceCategory(name='Стол 2м', kind='desk', capacity=2, width_m=1, height_m=0.75)
        db.session.add(cat)
        db.session.flush()
        db.session.add_all([
            CategoryTariff(category_id=cat.id, tariff_type='weekly', price=6000, active=True),
        ])
        place.category_id = cat.id
        db.session.commit()
        pid = place.id

    r = auth_client.post('/api/booking/price', json={
        'place_id': pid,
        'start_time': '10:00',
        'end_time': '18:00',
        'people_count': 2,
        'tariff_type': 'weekly',
    })
    assert r.status_code == 200
    assert r.get_json()['total_price'] == 12000

    r2 = auth_client.post('/api/booking/price', json={
        'place_id': pid,
        'start_time': '10:00',
        'end_time': '18:00',
        'people_count': 1,
        'tariff_type': 'weekly',
    })
    assert r2.get_json()['total_price'] == 6000


def test_whole_zone_blocked_when_child_desk_occupied(app):
    """Нельзя забронировать помещение целиком, если занят стол внутри."""
    from internal.services.booking_service import check_availability_15min
    from internal.models import Floor, Location, Place, PlaceCategory

    with app.app_context():
        fl = Floor.query.first()
        loc = Location.query.filter_by(code='1Б').first()
        cat = PlaceCategory(name='Зона 3м', kind='desk', capacity=1, width_m=3, height_m=2)
        db.session.add(cat)
        db.session.flush()
        db.session.add(CategoryTariff(
            category_id=cat.id, tariff_type='hourly', price=900, active=True,
        ))

        zone = Place(
            code='1Б-Z01', name='Зона тест', location_id=loc.id,
            floor_id=fl.id, kind='space', category_id=cat.id,
        )
        db.session.add(zone)
        db.session.flush()

        desk_cat = PlaceCategory.query.filter_by(capacity=1, kind='desk').first()
        desk = Place(
            code='1Б-Z01-1', name='Стол в зоне', location_id=loc.id,
            floor_id=fl.id, kind='desk', category_id=desk_cat.id,
            container_code=zone.code,
        )
        db.session.add(desk)
        db.session.flush()

        user = User.query.filter_by(email='client@test.com').first()
        db.session.add(Booking(
            user_id=user.id,
            place_id=desk.id,
            booking_date=date.today() + timedelta(days=5),
            start_time=time(11, 0),
            end_time=time(13, 0),
            duration_hours=2.0,
            total_price=500.0,
            tariff_type='hourly',
            status='active',
        ))
        db.session.commit()

        ok, msg, _ = check_availability_15min(
            zone.id,
            date.today() + timedelta(days=5),
            time(10, 0),
            time(14, 0),
            people_count=1,
        )
        assert ok is False
        assert '1Б-Z01-1' in msg


def test_monthly_booking_today_allowed(auth_client, app):
    """Месячный тариф на сегодня не считается «прошедшим временем» и не ограничен 8 ч."""
    from internal.models import Place

    with app.app_context():
        place = Place.query.filter_by(code='1Б-T01').first()
        place_id = place.id

    r = auth_client.post('/api/booking/create', json={
        'place_id': place_id,
        'date': date.today().strftime('%Y-%m-%d'),
        'start_time': '08:00',
        'end_time': '22:00',
        'people_count': 1,
        'tariff_type': 'monthly',
    })
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data['success'] is True
    assert data.get('is_subscription') is not True


def test_subscription_not_applied_to_monthly_tariff(auth_client, app):
    """Абонемент с лимитом часов не списывается при выборе месячного тарифа."""
    from internal.models import Place, Subscription

    with app.app_context():
        user = User.query.filter_by(email='client@test.com').first()
        place = Place.query.filter_by(code='1Б-T01').first()
        sub = Subscription(
            user_id=user.id,
            name='40 ч',
            place_kinds='["desk"]',
            start_date=date.today() - timedelta(days=1),
            end_date=date.today() + timedelta(days=30),
            hours_limit=40,
            hours_used=0,
            price=5000,
            active=True,
        )
        db.session.add(sub)
        db.session.commit()
        place_id = place.id

    r = auth_client.post('/api/booking/create', json={
        'place_id': place_id,
        'date': (date.today() + timedelta(days=1)).strftime('%Y-%m-%d'),
        'start_time': '08:00',
        'end_time': '22:00',
        'people_count': 1,
        'tariff_type': 'monthly',
    })
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data['success'] is True
    assert data.get('is_subscription') is not True
    assert data['total_price'] > 0

    with app.app_context():
        sub = Subscription.query.filter_by(name='40 ч').first()
        assert sub.hours_used == 0


def test_timegrid_reflects_updated_coworking_schedule(auth_client, app):
    """Изменение расписания в админке должно отражаться на шкале бронирования."""
    from internal.models import Coworking, CoworkingSchedule, Place

    with app.app_context():
        place = Place.query.filter_by(code='1Б-T01').first()
        target_date = date.today() + timedelta(days=7)
        cw = Coworking.get_singleton()
        sched = CoworkingSchedule.query.filter_by(
            id_coworking=cw.id,
            day_of_week=target_date.weekday(),
        ).first()
        sched.open_time = time(10, 0)
        sched.close_time = time(18, 0)
        sched.is_active = True
        sched.is_bookable = True
        db.session.commit()
        place_id = place.id
        date_str = target_date.strftime('%Y-%m-%d')

    r = auth_client.get(f'/api/booking/timegrid/{place_id}?date={date_str}')
    assert r.status_code == 200, r.get_json()
    data = r.get_json()['data']
    assert data['open_time'] == '10:00'
    assert data['close_time'] == '18:00'
    assert data['slots'][0]['time'] == '10:00'
    assert data['slots'][-1]['time'] == '17:45'


def test_schedule_midnight_close_means_24_00(auth_client, app):
    """00:00 как время закрытия = 24:00 (конец рабочего дня)."""
    from internal.models import Coworking, CoworkingSchedule, Place
    from internal.models.schedule import format_close_time
    from internal.services.booking_service import generate_time_slots

    with app.app_context():
        assert format_close_time(time(8, 0), time(0, 0)) == '24:00'
        slots = generate_time_slots(time(8, 0), time(0, 0))
        assert slots[0] == time(8, 0)
        assert slots[-1] == time(23, 45)

        place = Place.query.filter_by(code='1Б-T01').first()
        target_date = date.today() + timedelta(days=8)
        cw = Coworking.get_singleton()
        sched = CoworkingSchedule.query.filter_by(
            id_coworking=cw.id,
            day_of_week=target_date.weekday(),
        ).first()
        sched.open_time = time(8, 0)
        sched.close_time = time(0, 0)
        sched.is_active = True
        sched.is_bookable = True
        db.session.commit()
        place_id = place.id
        date_str = target_date.strftime('%Y-%m-%d')

    r = auth_client.get(f'/api/booking/timegrid/{place_id}?date={date_str}')
    assert r.status_code == 200, r.get_json()
    data = r.get_json()['data']
    assert data['close_time'] == '24:00'
    assert data['slots'][-1]['time'] == '23:45'


def test_zone_timegrid_shows_occupied_when_child_desk_booked(auth_client, app):
    """Шкала зоны должна показывать занятость, если внутри забронирован стол."""
    from internal.models import Floor, Location, Place, PlaceCategory

    with app.app_context():
        fl = Floor.query.first()
        loc = Location.query.filter_by(code='1Б').first()
        cat = PlaceCategory(name='Зона шкала', kind='desk', capacity=1, width_m=3, height_m=2)
        db.session.add(cat)
        db.session.flush()
        db.session.add(CategoryTariff(
            category_id=cat.id, tariff_type='hourly', price=900, active=True,
        ))

        zone = Place(
            code='1Б-Z02', name='Зона шкала', location_id=loc.id,
            floor_id=fl.id, kind='space', category_id=cat.id,
        )
        db.session.add(zone)
        db.session.flush()

        desk_cat = PlaceCategory.query.filter_by(capacity=1, kind='desk').first()
        desk = Place(
            code='1Б-Z02-1', name='Стол в зоне 2', location_id=loc.id,
            floor_id=fl.id, kind='desk', category_id=desk_cat.id,
            container_code=zone.code,
        )
        db.session.add(desk)
        db.session.flush()

        booking_day = date.today() + timedelta(days=5)
        user = User.query.filter_by(email='client@test.com').first()
        db.session.add(Booking(
            user_id=user.id,
            place_id=desk.id,
            booking_date=booking_day,
            start_time=time(11, 0),
            end_time=time(13, 0),
            duration_hours=2.0,
            total_price=500.0,
            tariff_type='hourly',
            status='active',
        ))
        db.session.commit()
        zone_id = zone.id
        date_str = booking_day.strftime('%Y-%m-%d')

    r = auth_client.get(f'/api/booking/timegrid/{zone_id}?date={date_str}')
    assert r.status_code == 200, r.get_json()
    data = r.get_json()['data']
    assert data['zone_capacity'] == 1
    slots = {s['time']: s for s in data['slots']}
    assert slots['11:00']['status'] == 'full'
    assert slots['10:00']['status'] == 'free'


def test_child_desk_timegrid_shows_occupied_when_whole_zone_booked(auth_client, app):
    """Если зона забронирована целиком, столы внутри на шкале тоже заняты."""
    from internal.models import Floor, Location, Place, PlaceCategory

    with app.app_context():
        fl = Floor.query.first()
        loc = Location.query.filter_by(code='1Б').first()
        cat = PlaceCategory(name='Зона целиком', kind='desk', capacity=1, width_m=3, height_m=2)
        db.session.add(cat)
        db.session.flush()
        db.session.add(CategoryTariff(
            category_id=cat.id, tariff_type='hourly', price=900, active=True,
        ))

        zone = Place(
            code='1Б-Z04', name='Зона целиком', location_id=loc.id,
            floor_id=fl.id, kind='space', category_id=cat.id,
        )
        db.session.add(zone)
        db.session.flush()

        desk_cat = PlaceCategory.query.filter_by(capacity=1, kind='desk').first()
        desk = Place(
            code='1Б-Z04-1', name='Стол в зоне 4', location_id=loc.id,
            floor_id=fl.id, kind='desk', category_id=desk_cat.id,
            container_code=zone.code,
        )
        db.session.add(desk)
        db.session.flush()

        booking_day = date.today() + timedelta(days=6)
        user = User.query.filter_by(email='client@test.com').first()
        db.session.add(Booking(
            user_id=user.id,
            place_id=zone.id,
            booking_date=booking_day,
            start_time=time(11, 0),
            end_time=time(13, 0),
            duration_hours=2.0,
            total_price=900.0,
            tariff_type='hourly',
            status='active',
        ))
        db.session.commit()
        desk_id = desk.id
        date_str = booking_day.strftime('%Y-%m-%d')

    r = auth_client.get(f'/api/booking/timegrid/{desk_id}?date={date_str}')
    assert r.status_code == 200, r.get_json()
    slots = {s['time']: s for s in r.get_json()['data']['slots']}
    assert slots['11:00']['status'] == 'full'
    assert slots['10:00']['status'] == 'free'


def test_zone_timegrid_capacity_sums_desks(auth_client, app):
    """Вместимость зоны на шкале — сумма мест всех столов."""
    from internal.models import Floor, Location, Place, PlaceCategory

    with app.app_context():
        fl = Floor.query.first()
        loc = Location.query.filter_by(code='1Б').first()
        cat = PlaceCategory(name='Зона 5 мест', kind='desk', capacity=1, width_m=3, height_m=2)
        db.session.add(cat)
        db.session.flush()
        db.session.add(CategoryTariff(
            category_id=cat.id, tariff_type='hourly', price=900, active=True,
        ))

        zone = Place(
            code='1Б-Z03', name='Зона 5 мест', location_id=loc.id,
            floor_id=fl.id, kind='space', category_id=cat.id,
        )
        db.session.add(zone)
        db.session.flush()

        desk_cat = PlaceCategory.query.filter_by(capacity=1, kind='desk').first()
        for i in range(1, 4):
            db.session.add(Place(
                code=f'1Б-Z03-{i}', name=f'Стол {i}', location_id=loc.id,
                floor_id=fl.id, kind='desk', category_id=desk_cat.id,
                container_code=zone.code,
            ))
        db.session.commit()
        zone_id = zone.id
        date_str = (date.today() + timedelta(days=3)).strftime('%Y-%m-%d')

    r = auth_client.get(f'/api/booking/timegrid/{zone_id}?date={date_str}')
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['data']['zone_capacity'] == 3


def test_create_booking_without_subscription_when_flag_false(auth_client, app):
    """Клиент может сознать почасовую бронь по тарифу, не списывая абонемент."""
    from internal.models import Place, Subscription

    with app.app_context():
        user = User.query.filter_by(email='client@test.com').first()
        place = Place.query.filter_by(code='1Б-T01').first()
        sub = Subscription(
            user_id=user.id,
            name='40 ч opt-out',
            place_kinds='["desk"]',
            start_date=date.today() - timedelta(days=1),
            end_date=date.today() + timedelta(days=30),
            hours_limit=40,
            hours_used=0,
            price=5000,
            active=True,
        )
        db.session.add(sub)
        db.session.commit()
        place_id = place.id

    booking_day = date.today() + timedelta(days=2)
    r = auth_client.post('/api/booking/create', json={
        'place_id': place_id,
        'date': booking_day.strftime('%Y-%m-%d'),
        'start_time': '10:00',
        'end_time': '12:00',
        'people_count': 1,
        'tariff_type': 'hourly',
        'use_subscription': False,
    })
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data['success'] is True
    assert data.get('is_subscription') is not True
    assert data['total_price'] > 0

    with app.app_context():
        sub = Subscription.query.filter_by(name='40 ч opt-out').first()
        assert sub.hours_used == 0


def test_price_api_without_subscription(auth_client, app):
    """При no_subscription цена считается по тарифу, а не 0."""
    from internal.models import Place, Subscription, User, db

    with app.app_context():
        user = User.query.filter_by(email='client@test.com').first()
        place = Place.query.filter_by(code='1Б-T01').first()
        sub = Subscription(
            user_id=user.id,
            name='40 ч price test',
            place_kinds='["desk"]',
            start_date=date.today() - timedelta(days=1),
            end_date=date.today() + timedelta(days=30),
            hours_limit=40,
            hours_used=0,
            price=5000,
            active=True,
        )
        db.session.add(sub)
        db.session.commit()
        place_id = place.id

    booking_day = date.today() + timedelta(days=2)
    r = auth_client.post('/api/booking/price', json={
        'place_id': place_id,
        'date': booking_day.strftime('%Y-%m-%d'),
        'start_time': '10:00',
        'end_time': '12:00',
        'people_count': 1,
        'tariff_type': 'hourly',
        'no_subscription': True,
    })
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data['success'] is True
    assert data['is_subscription'] is not True
    assert data['total_price'] > 0
