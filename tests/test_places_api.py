"""Tests for /api/places and parent linking."""
from internal.models import ensure_place_parent_links, reload_layout


def test_api_places_returns_json(client, app):
    with app.app_context():
        reload_layout()
        ensure_place_parent_links()
    r = client.get('/api/places')
    assert r.status_code == 200
    data = r.get_json()
    assert 'places' in data
    assert isinstance(data['places'], list)
    if data['places']:
        p = data['places'][0]
        assert 'code' in p
        assert 'kind' in p
        assert 'floor' in p


def test_api_places_response_time(client, app):
    """Карта: /api/places должен отвечать без заметных задержек."""
    import time
    with app.app_context():
        reload_layout()
        ensure_place_parent_links()
    started = time.perf_counter()
    r = client.get('/api/places')
    elapsed = time.perf_counter() - started
    assert r.status_code == 200
    assert elapsed < 2.0, f'/api/places слишком медленный: {elapsed:.2f}s'
    assert 'places' in r.get_json()


def test_spaces_have_children_count(client, app):
    with app.app_context():
        reload_layout()
        ensure_place_parent_links()
    r = client.get('/api/places')
    spaces = [p for p in r.get_json()['places'] if p['kind'] in ('space', 'room') and not p.get('container_code')]
    for sp in spaces:
        assert 'children_count' in sp
        assert sp['children_count'] >= 0
