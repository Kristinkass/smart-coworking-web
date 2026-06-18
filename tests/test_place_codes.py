"""Tests for place code formatting."""
from internal.utils.formatters import (
    format_place_code,
    format_place_container,
    format_place_full_code_dict,
)


def test_format_place_code_orphan_desk(app):
    from internal.models import Place

    with app.app_context():
        place = Place.query.filter_by(code='1Б-T01').first()
        assert place is not None
        assert format_place_code(place) == '1Б-T01'
        assert format_place_container(place) == ''


def test_format_place_container_for_desk_in_zone(app):
    from internal.models import Place

    with app.app_context():
        desk = Place.query.filter(Place.container_code.isnot(None)).first()
        if not desk:
            return
        container = desk.get_container_place()
        label = format_place_container(desk)
        assert container.name in label or container.code in label


def test_format_place_full_code_dict():
    by_code = {
        '1A-L96': {'code': '1A-L96', 'location_code': '1A', 'kind': 'space'},
    }
    desk = {
        'code': '1A-T108',
        'location_code': '1A',
        'kind': 'desk',
        'container_code': '1A-L96',
    }
    assert format_place_full_code_dict(desk, by_code) == '1A · 1A-L96 · 1A-T108'


def test_schedule_api_accepts_24_close(admin_client, app):
    """PUT /api/admin/schedule/<id> с close_time 24:00 не падает с NameError."""
    from internal.models import Coworking, CoworkingSchedule
    from internal.models.schedule import format_close_time

    with app.app_context():
        cw = Coworking.get_singleton()
        sched = CoworkingSchedule.query.filter_by(id_coworking=cw.id, day_of_week=0).first()
        sched_id = sched.id

    r = admin_client.put(
        f'/api/admin/schedule/{sched_id}',
        json={'close_time': '24:00'},
    )
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data['success'] is True
    with app.app_context():
        sched = CoworkingSchedule.query.get(sched_id)
        assert format_close_time(sched.open_time, sched.close_time) == '24:00'
