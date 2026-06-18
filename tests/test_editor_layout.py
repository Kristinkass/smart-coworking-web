"""Тесты редактора: перемещение столов в закрытых зонах, layout.json."""
import json

import pytest

import internal.models as models
from internal.models import (
    Coworking,
    Floor,
    Location,
    Place,
    User,
    db,
)
from internal.models.geometry import find_place_overlap, project_layout_positions


@pytest.fixture
def temp_layout(tmp_path, monkeypatch):
    """Изолированный layout.json для тестов редактора."""
    layout_file = tmp_path / 'layout.json'
    data = {
        'places': [
            {
                'code': 'T-ZONE-1', 'name': 'Закрытая зона', 'kind': 'space',
                'x': 100, 'y': 100, 'width': 600, 'height': 300,
                'floor': 1, 'enclosed': True, 'source': 'walls', 'location': '1A',
            },
            {
                'code': 'T-DESK-1', 'name': 'Стол тест 1', 'kind': 'desk',
                'x': 150, 'y': 150, 'width': 100, 'height': 75,
                'floor': 1, 'container_code': 'T-ZONE-1',
            },
            {
                'code': 'T-DESK-2', 'name': 'Стол тест 2', 'kind': 'desk',
                'x': 280, 'y': 150, 'width': 100, 'height': 75,
                'floor': 1, 'container_code': 'T-ZONE-1',
            },
        ],
        'walls': [],
        'doors': [],
        'coworking': {'name': 'Тест', 'address': ''},
    }
    layout_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr('internal.utils.paths.LAYOUT_PATH', str(layout_file))
    monkeypatch.setattr('internal.layout.store.LAYOUT_PATH', str(layout_file))
    models.reload_layout()
    return data, layout_file


@pytest.fixture
def enclosed_zone_db(app, temp_layout):
    """Place в БД: закрытая зона + столы."""
    with app.app_context():
        cw = Coworking.query.first()
        if not cw:
            cw = Coworking(name='Тест', address='')
            db.session.add(cw)
            db.session.flush()
        fl = Floor.query.filter_by(number=1).first()
        if not fl:
            fl = Floor(coworking_id=cw.id, number=1, name='Этаж 1')
            db.session.add(fl)
            db.session.flush()
        loc = Location.query.filter_by(code='1A').first()
        if not loc:
            loc = Location(floor_id=fl.id, code='1A', name='Зона A', kind='desk_zone')
            db.session.add(loc)
            db.session.flush()

        zone = Place.query.filter_by(code='T-ZONE-1').first()
        if not zone:
            zone = Place(
                code='T-ZONE-1', name='Закрытая зона', kind='space',
                location_id=loc.id, floor_id=fl.id, enclosed=True,
            )
            db.session.add(zone)
            db.session.flush()

        for code, name in (('T-DESK-1', 'Стол 89'), ('T-DESK-2', 'Стол 88')):
            if not Place.query.filter_by(code=code).first():
                db.session.add(Place(
                    code=code, name=name, kind='desk',
                    location_id=loc.id, floor_id=fl.id, container_code=zone.code,
                ))
        admin = User.query.filter_by(email='admin@test.com').first()
        if not admin:
            admin = User(email='admin@test.com', username='Админ', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
        db.session.commit()
        return zone.code


def test_models_exports_layout_helpers():
    """Публичный API internal.models содержит функции редактора."""
    assert hasattr(models, 'move_container_with_children')
    assert hasattr(models, 'project_layout_positions')
    assert hasattr(models, 'sync_wall_bound_places')
    assert hasattr(models, 'create_walls_around_rect')
    assert callable(models.move_container_with_children)


def test_project_layout_avoids_false_desk_overlap(temp_layout):
    """Столы внутри зоны не конфликтуют при групповом сдвиге (проекция layout)."""
    layout_places, _ = temp_layout
    dx, dy = 50, 30
    zone = next(p for p in layout_places['places'] if p['code'] == 'T-ZONE-1')

    updates = {zone['code']: {'x': zone['x'] + dx, 'y': zone['y'] + dy}}
    for lp in layout_places['places']:
        if lp.get('container_code') == zone['code']:
            updates[lp['code']] = {
                'x': lp['x'] + dx,
                'y': lp['y'] + dy,
            }

    projected = project_layout_positions(layout_places['places'], updates)

    for lp in layout_places['places']:
        if lp.get('container_code') != zone['code']:
            continue
        nx = lp['x'] + dx
        ny = lp['y'] + dy
        err = find_place_overlap(
            projected, lp['code'], nx, ny, lp['width'], lp['height'],
            1, 'desk', zone['code'],
        )
        assert err is None, f'Ложное пересечение для {lp["code"]}: {err}'

    lp89 = next(p for p in layout_places['places'] if p['code'] == 'T-DESK-1')
    stale_err = find_place_overlap(
        layout_places['places'],
        'T-DESK-1', lp89['x'] + dx, lp89['y'] + dy,
        lp89['width'], lp89['height'], 1, 'desk', zone['code'],
    )
    assert stale_err is not None


def test_api_move_desk_in_enclosed_zone(client, app, temp_layout, enclosed_zone_db):
    """POST /api/admin/place/move перемещает стол внутри закрытой зоны."""
    with app.app_context():
        client.post('/login', data={
            'email': 'admin@test.com',
            'password': 'admin123',
        }, follow_redirects=True)

        r = client.post(
            '/api/admin/place/move',
            json={'code': 'T-DESK-1', 'x': 180, 'y': 170, 'floor': 1},
            content_type='application/json',
        )
        assert r.status_code == 200, r.get_json()
        data = r.get_json()
        assert data['success'] is True

        geom = models.get_place_geometry('T-DESK-1')
        assert geom['x'] == 180
        assert geom['y'] == 170


def test_orphan_desks_not_auto_wrapped(app, temp_layout):
    """Столы в коридоре не оборачиваются в зону автоматически."""
    data, layout_file = temp_layout
    data['places'] = [
        {
            'code': 'T-DESK-3', 'name': 'Стол 91', 'kind': 'desk',
            'x': 400, 'y': 400, 'width': 100, 'height': 75,
            'floor': 1, 'location': '1A',
        },
        {
            'code': 'T-DESK-4', 'name': 'Стол 92', 'kind': 'desk',
            'x': 900, 'y': 900, 'width': 100, 'height': 75,
            'floor': 1, 'location': '1A',
        },
    ]
    layout_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    models.reload_layout()

    with app.app_context():
        models.ensure_place_parent_links()
        layout = models.load_layout()
    open_zones = [p for p in layout['places'] if p.get('kind') == 'space' and p.get('enclosed') is False]
    orphans = [p for p in layout['places'] if p.get('kind') == 'desk' and not p.get('container_code')]

    assert len(open_zones) == 0
    assert len(orphans) == 2


def test_sync_wall_bound_places(temp_layout):
    """sync_wall_bound_places подтягивает layout места к контуру стен."""
    _, layout_file = temp_layout
    data = json.loads(layout_file.read_text(encoding='utf-8'))
    data['walls'] = [
        {'id': 1, 'x1': 400, 'y1': 200, 'x2': 400, 'y2': 500, 'floor': 1},
        {'id': 2, 'x1': 750, 'y1': 200, 'x2': 750, 'y2': 500, 'floor': 1},
        {'id': 3, 'x1': 400, 'y1': 200, 'x2': 750, 'y2': 200, 'floor': 1},
        {'id': 4, 'x1': 400, 'y1': 500, 'x2': 750, 'y2': 500, 'floor': 1},
    ]
    data['places'].append({
        'code': '1B-11', 'name': 'Переговорная', 'kind': 'space',
        'x': 400, 'y': 200, 'width': 300, 'height': 300,
        'floor': 1, 'enclosed': True, 'source': 'walls', 'location': '1B',
    })
    layout_file.write_text(json.dumps(data), encoding='utf-8')
    models.reload_layout()

    synced = models.sync_wall_bound_places(floor=1)
    assert '1B-11' in synced

    geom = models.get_place_geometry('1B-11')
    assert geom['width'] == 350
    assert geom['height'] == 300


def test_adjacent_locations_do_not_conflict():
    """Соседние комнаты по общей стене — не считаются пересечением."""
    from internal.models.geometry import location_overlap_conflicts, rects_meaningful_overlap

    assert not rects_meaningful_overlap(0, 0, 100, 100, 100, 0, 80, 100)
    assert rects_meaningful_overlap(0, 0, 100, 100, 50, 50, 80, 80)

    places = [
        {'code': '1A-L1', 'kind': 'space', 'x': 0, 'y': 0, 'width': 100, 'height': 100, 'floor': 1},
        {'code': '1A-L2', 'kind': 'space', 'x': 100, 'y': 0, 'width': 80, 'height': 100, 'floor': 1},
    ]
    conflicts, _ = location_overlap_conflicts(places, '__new__', 100, 0, 80, 100, 1)
    assert conflicts == []


def test_rotated_desk_wall_collision_uses_effective_bbox():
    """Повёрнутый стол проверяется по visual bounding-box, а не по исходным width/height."""
    from internal.models.geometry import (
        effective_rect_for_rotation,
        rect_overlaps_walls_rotated,
    )

    walls = [{'x1': 200, 'y1': 0, 'x2': 200, 'y2': 400, 'floor': 1}]
    # Без поворота стол 100×140 у x=82 не задевает стену x=200
    assert not rect_overlaps_walls_rotated(82, 100, 100, 140, 0, walls, 1)
    # При 90° visual bbox шире — пересекает стену
    eff_x, eff_y, eff_w, eff_h = effective_rect_for_rotation(82, 100, 100, 140, 90)
    assert eff_w == 140 and eff_h == 100
    assert rect_overlaps_walls_rotated(82, 100, 100, 140, 90, walls, 1)


def test_rotated_desks_overlap_detection():
    """Пересечение столов учитывает rotation обоих объектов."""
    from internal.models.geometry import find_place_overlap

    layout = [
        {'code': 'T1', 'kind': 'desk', 'x': 100, 'y': 100, 'width': 100, 'height': 60, 'floor': 1, 'rotation': 0},
        {'code': 'T2', 'kind': 'desk', 'x': 160, 'y': 100, 'width': 100, 'height': 60, 'floor': 1, 'rotation': 90},
    ]
    err = find_place_overlap(layout, 'T3', 130, 100, 100, 60, 1, 'desk', rotation=0)
    assert err is not None


def test_move_wall_propagates_junctions(temp_layout):
    """Сдвиг вертикальной стены тянет примыкающие горизонтальные концы."""
    _, layout_file = temp_layout
    data = json.loads(layout_file.read_text(encoding='utf-8'))
    data['walls'] = [
        {'id': 1, 'x1': 100, 'y1': 0, 'x2': 100, 'y2': 200, 'floor': 1},
        {'id': 2, 'x1': 100, 'y1': 0, 'x2': 300, 'y2': 0, 'floor': 1},
        {'id': 3, 'x1': 100, 'y1': 200, 'x2': 300, 'y2': 200, 'floor': 1},
    ]
    layout_file.write_text(json.dumps(data), encoding='utf-8')
    models.reload_layout()

    models.move_wall(1, 120, 0, 120, 200)
    walls = {w['id']: w for w in models.load_walls()}
    assert walls[2]['x1'] == 120
    assert walls[3]['x1'] == 120


def test_split_room_drops_parent_container():
    """Внутренняя стена делит комнату — остаются только две отдельные, без большой «обёртки»."""
    from internal.utils.room_geometry import detect_all_wall_rooms

    walls = [
        {'x1': 100, 'y1': 100, 'x2': 500, 'y2': 100, 'floor': 1},
        {'x1': 100, 'y1': 400, 'x2': 500, 'y2': 400, 'floor': 1},
        {'x1': 100, 'y1': 100, 'x2': 100, 'y2': 400, 'floor': 1},
        {'x1': 500, 'y1': 100, 'x2': 500, 'y2': 400, 'floor': 1},
        {'x1': 300, 'y1': 100, 'x2': 300, 'y2': 400, 'floor': 1},
    ]
    rooms = detect_all_wall_rooms(walls, floor=1)
    assert len(rooms) == 2
    widths = sorted(r['width'] for r in rooms)
    assert widths == [200, 200]


def test_dismiss_draft_room_removes_exclusive_walls(tmp_path, monkeypatch):
    """Убрать левый черновик — удаляются только его стены, правая комната остаётся."""
    import json

    from internal.utils.room_geometry import detect_all_wall_rooms, dismiss_draft_room
    from internal.models.layout import load_walls, reload_layout

    layout_file = tmp_path / 'layout.json'
    layout_file.write_text(json.dumps({
        'places': [],
        'walls': [
            {'id': 1, 'x1': 100, 'y1': 100, 'x2': 500, 'y2': 100, 'floor': 1},
            {'id': 2, 'x1': 100, 'y1': 400, 'x2': 500, 'y2': 400, 'floor': 1},
            {'id': 3, 'x1': 100, 'y1': 100, 'x2': 100, 'y2': 400, 'floor': 1},
            {'id': 4, 'x1': 500, 'y1': 100, 'x2': 500, 'y2': 400, 'floor': 1},
            {'id': 5, 'x1': 300, 'y1': 100, 'x2': 300, 'y2': 400, 'floor': 1},
        ],
        'doors': [],
        'ignored_drafts': [],
    }, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr('internal.utils.paths.LAYOUT_PATH', str(layout_file))
    monkeypatch.setattr('internal.layout.store.LAYOUT_PATH', str(layout_file))
    reload_layout()

    rooms_before = detect_all_wall_rooms(load_walls(), floor=1)
    assert len(rooms_before) == 2

    result = dismiss_draft_room(100, 100, 200, 300, floor=1)
    assert result['walls_removed'] >= 1

    rooms_after = detect_all_wall_rooms(load_walls(), floor=1)
    assert len(rooms_after) == 1
    assert rooms_after[0]['x'] == 300


def test_api_dismiss_draft_hides_room(client, app, tmp_path, monkeypatch):
    """POST dismiss-draft убирает черновик с карты редактора."""
    import json
    from internal.models import User, db
    from internal.models.layout import reload_layout

    layout_file = tmp_path / 'layout.json'
    layout_file.write_text(json.dumps({
        'places': [],
        'walls': [
            {'id': 1, 'x1': 100, 'y1': 100, 'x2': 500, 'y2': 100, 'floor': 1},
            {'id': 2, 'x1': 100, 'y1': 400, 'x2': 500, 'y2': 400, 'floor': 1},
            {'id': 3, 'x1': 100, 'y1': 100, 'x2': 100, 'y2': 400, 'floor': 1},
            {'id': 4, 'x1': 500, 'y1': 100, 'x2': 500, 'y2': 400, 'floor': 1},
            {'id': 5, 'x1': 300, 'y1': 100, 'x2': 300, 'y2': 400, 'floor': 1},
        ],
        'doors': [],
        'ignored_drafts': [],
    }, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr('internal.utils.paths.LAYOUT_PATH', str(layout_file))
    monkeypatch.setattr('internal.layout.store.LAYOUT_PATH', str(layout_file))
    reload_layout()

    with app.app_context():
        admin = User.query.filter_by(email='admin@test.com').first()
        if not admin:
            admin = User(email='admin@test.com', username='Админ', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
        client.post('/login', data={'email': 'admin@test.com', 'password': 'admin123'}, follow_redirects=True)

        r = client.post('/api/admin/room/dismiss-draft', json={
            'x': 100, 'y': 100, 'width': 200, 'height': 300,
            'floor': 1, 'room_key': 'wall-100-100-200-300',
        })
        assert r.status_code == 200
        assert r.get_json()['success'] is True

        map_r = client.get('/api/admin/editor/map?floor=1')
        drafts = [rm for rm in map_r.get_json()['rooms'] if not rm['registered']]
        assert len(drafts) == 1
        assert drafts[0]['x'] == 300


def test_delete_wall_restores_suppressed_zone(tmp_path, monkeypatch):
    """Удаление стены на границе скрытой зоны снимает блокировку ignored_drafts."""
    import json

    from internal.models.layout import delete_wall, load_ignored_drafts, reload_layout
    from internal.utils.room_geometry import detect_all_wall_rooms

    layout_file = tmp_path / 'layout.json'
    layout_file.write_text(json.dumps({
        'places': [],
        'walls': [
            {'id': 1, 'x1': 100, 'y1': 100, 'x2': 500, 'y2': 100, 'floor': 1},
            {'id': 2, 'x1': 100, 'y1': 400, 'x2': 500, 'y2': 400, 'floor': 1},
            {'id': 3, 'x1': 100, 'y1': 100, 'x2': 100, 'y2': 400, 'floor': 1},
            {'id': 4, 'x1': 300, 'y1': 100, 'x2': 300, 'y2': 400, 'floor': 1},
            {'id': 5, 'x1': 500, 'y1': 100, 'x2': 500, 'y2': 400, 'floor': 1},
        ],
        'doors': [],
        'ignored_drafts': [{
            'x': 300, 'y': 100, 'width': 200, 'height': 300,
            'floor': 1, 'room_key': 'wall-300-100-200-300',
        }],
    }, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr('internal.utils.paths.LAYOUT_PATH', str(layout_file))
    monkeypatch.setattr('internal.layout.store.LAYOUT_PATH', str(layout_file))
    reload_layout()

    rooms_hidden = detect_all_wall_rooms(json.loads(layout_file.read_text(encoding='utf-8'))['walls'], 1)
    assert not any(r['x'] == 300 for r in rooms_hidden)

    delete_wall(4)

    assert load_ignored_drafts(1) == []
    rooms_visible = detect_all_wall_rooms(json.loads(layout_file.read_text(encoding='utf-8'))['walls'], 1)
    assert len(rooms_visible) == 1
    assert rooms_visible[0]['x'] == 100
    assert rooms_visible[0]['width'] == 400
