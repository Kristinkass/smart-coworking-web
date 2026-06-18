"""Fixtures for unit tests."""
from datetime import date, time, timedelta

import pytest

from internal.application import create_app
from internal.config import TestConfig
from internal.models import (
    Booking,
    CategoryTariff,
    Coworking,
    CoworkingSchedule,
    Floor,
    Location,
    Place,
    PlaceCategory,
    User,
    db,
)


def _seed_minimal():
    cw = Coworking(name='Тестовый коворкинг', address='ул. Тестовая, 1')
    db.session.add(cw)
    db.session.flush()

    fl1 = Floor(coworking_id=cw.id, number=1, name='1-й этаж')
    fl2 = Floor(coworking_id=cw.id, number=2, name='2-й этаж')
    db.session.add_all([fl1, fl2])
    db.session.flush()

    loc1 = Location(floor_id=fl1.id, code='1Б', name='Зона столов', kind='desk_zone')
    loc2 = Location(floor_id=fl2.id, code='2А', name='Переговорные', kind='room_zone')
    db.session.add_all([loc1, loc2])
    db.session.flush()

    cat = PlaceCategory(
        name='Стол тестовый', kind='desk', capacity=1,
        width_m=0.5, height_m=0.75,
    )
    db.session.add(cat)
    db.session.flush()
    db.session.add_all([
        CategoryTariff(category_id=cat.id, tariff_type='hourly', price=250, active=True),
        CategoryTariff(category_id=cat.id, tariff_type='weekly', price=3500, active=True),
        CategoryTariff(category_id=cat.id, tariff_type='monthly', price=12000, active=True),
    ])
    CoworkingSchedule.init_default_schedule(cw.id)

    place = Place(
        code='1Б-T01', name='Стол 1', location_id=loc1.id,
        floor_id=fl1.id, kind='desk', category_id=cat.id,
    )
    db.session.add(place)

    client = User(
        email='client@test.com', username='Клиент',
        phone='+7 999 000 33 44', role='client', visitor_kind='tariff',
    )
    client.set_password('123456')
    other = User(
        email='other@test.com', username='Другой',
        phone='+7 999 000 44 55', role='client', visitor_kind='tariff',
    )
    other.set_password('123456')
    db.session.add_all([client, other])
    db.session.commit()
    return client, other, place


@pytest.fixture
def app():
    application = create_app(TestConfig)
    with application.app_context():
        db.create_all()
        _seed_minimal()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client, app):
    with app.app_context():
        user = User.query.filter_by(email='client@test.com').first()
        client.post('/login', data={'email': user.email, 'password': '123456'}, follow_redirects=True)
    return client


@pytest.fixture
def admin_client(client, app):
    with app.app_context():
        admin = User.query.filter_by(role='admin').first()
        if not admin:
            admin = User(email='admin@test.com', username='Админ', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
        client.post('/login', data={'email': admin.email, 'password': 'admin123'}, follow_redirects=True)
    return client


@pytest.fixture
def sample_booking(app):
    with app.app_context():
        user = User.query.filter_by(email='client@test.com').first()
        place = Place.query.filter_by(code='1Б-T01').first()
        booking = Booking(
            user_id=user.id,
            place_id=place.id,
            booking_date=date.today() + timedelta(days=3),
            start_time=time(10, 0),
            end_time=time(12, 0),
            duration_hours=2.0,
            total_price=500.0,
            tariff_type='hourly',
            status='active',
        )
        db.session.add(booking)
        db.session.commit()
        return booking.id
