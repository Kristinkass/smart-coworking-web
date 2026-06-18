"""Smoke-тесты ключевых маршрутов после рефакторинга handlers."""
import importlib
import pkgutil

import internal.handlers as handlers_pkg


def _import_all_handler_modules():
    """Импорт всех модулей handlers — ловит NameError на уровне модуля."""
    for mod in pkgutil.walk_packages(handlers_pkg.__path__, handlers_pkg.__name__ + '.'):
        if mod.name.endswith('.deps'):
            continue
        importlib.import_module(mod.name)


def test_handler_modules_import(client, app):
    """Все handler-модули импортируются без NameError."""
    with app.app_context():
        _import_all_handler_modules()


def test_api_places_includes_full_code(client, app):
    with app.app_context():
        r = client.get('/api/places')
    assert r.status_code == 200
    data = r.get_json()
    assert 'places' in data
    if data['places']:
        assert 'full_code' in data['places'][0]


def test_dashboard_requires_login(client):
    r = client.get('/dashboard', follow_redirects=False)
    assert r.status_code in (302, 401)


def test_dashboard_authenticated(auth_client, app):
    with app.app_context():
        r = auth_client.get('/dashboard')
    assert r.status_code == 200
    assert 'dashboard-container' in r.get_data(as_text=True)


def test_map_page_authenticated(auth_client, app):
    with app.app_context():
        r = auth_client.get('/mapp')
    assert r.status_code == 200


def test_my_subscriptions_api(auth_client, app):
    with app.app_context():
        r = auth_client.get('/api/my/subscriptions')
    assert r.status_code == 200
    assert r.get_json().get('success') is True


def test_subscription_templates_api(auth_client, app):
    with app.app_context():
        r = auth_client.get('/api/subscription-templates')
    assert r.status_code == 200
    assert r.get_json().get('success') is True


def test_admin_users_page(app, admin_client):
    with app.app_context():
        r = admin_client.get('/admin/users')
    assert r.status_code == 200
    assert 'Управление пользователями' in r.get_data(as_text=True)
