"""Отчёты, статистика и согласованность данных."""
from datetime import date, time, timedelta

import pytest

from internal.models import Booking, User, db
from internal.utils.formatters import build_report_stats


def test_build_report_stats_has_by_tariff(app, sample_booking):
    with app.app_context():
        booking = Booking.query.get(sample_booking)
        stats, grouped = build_report_stats([booking])
        assert 'tariff_summary' in stats
        assert grouped['hourly']
        assert any(row['label'] == 'Почасовые' for row in stats['tariff_summary'])


def test_admin_reports_page_renders(app, admin_client, sample_booking):
    with app.app_context():
        r = admin_client.get('/admin/reports')
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert 'Почасовые бронирования' in text
    assert 'by_tariff' not in text
    assert 'tariff_summary' not in text


def test_admin_reports_pdf(app, admin_client, sample_booking):
    with app.app_context():
        r = admin_client.get('/api/admin/reports/pdf')
    assert r.status_code == 200
    assert r.mimetype == 'application/pdf'


def test_public_stats_endpoint(client, app, sample_booking):
    with app.app_context():
        r = client.get('/api/public/stats')
    assert r.status_code == 200
    data = r.get_json()
    assert 'total_places' in data
    assert 'total_users' in data
    assert 'today_bookings' in data
    assert data['total_places'] >= 1


def test_available_times_respects_schedule(app, auth_client):
    """API available_times не должен отдавать слоты вне расписания."""
    from internal.models import CoworkingSchedule, Coworking, Place

    with app.app_context():
        cw = Coworking.get_singleton()
        sched = CoworkingSchedule.query.filter_by(id_coworking=cw.id, day_of_week=0).first()
        sched.open_time = time(10, 0)
        sched.close_time = time(18, 0)
        db.session.commit()
        place = Place.query.filter_by(code='1Б-T01').first()
        # ближайший понедельник
        d = date.today()
        while d.weekday() != 0:
            d += timedelta(days=1)
        r = auth_client.get(f'/api/available_times/{place.id}?date={d.isoformat()}')
        assert r.status_code == 200
        data = r.get_json()
        assert data['all_slots']
        assert data['all_slots'][0]['start'] == '10:00'
        assert all(s['start'] < '18:00' or s['end'] <= '18:00' for s in data['all_slots'])


def test_admin_statistics_page(app, admin_client):
    with app.app_context():
        r = admin_client.get('/admin/statistics')
    assert r.status_code == 200
    assert 'Посетителей' in r.get_data(as_text=True)
