"""Tests for login by email and phone."""
import json

from internal.models import User, db


def test_login_by_email(client, app):
  with app.app_context():
    user = User.query.filter_by(email='client@test.com').first()
    assert user is not None

  r = client.post('/login', data={
    'login_mode': 'email',
    'identifier': 'client@test.com',
    'password': '123456',
  }, follow_redirects=True)
  assert r.status_code == 200
  assert 'Добро пожаловать' in r.get_data(as_text=True)


def test_login_by_phone(client, app):
  with app.app_context():
    user = User(
      email=None,
      username='Телефонный клиент',
      phone='+7 999 111 22 33',
      role='client',
      visitor_kind='tariff',
      active=True,
    )
    user.set_password('654321')
    db.session.add(user)
    db.session.commit()

  r = client.post('/login', data={
    'login_mode': 'phone',
    'identifier': '+7 999 111 22 33',
    'password': '654321',
  }, follow_redirects=True)
  assert r.status_code == 200
  assert 'Добро пожаловать' in r.get_data(as_text=True)


def test_quick_register_without_email(client, app):
  with app.app_context():
    admin = User(email='admin@test.com', username='Admin', role='admin', active=True)
    admin.set_password('admin123')
    db.session.add(admin)
    db.session.commit()

  client.post('/login', data={
    'login_mode': 'email',
    'identifier': 'admin@test.com',
    'password': 'admin123',
  }, follow_redirects=True)

  r = client.post('/api/admin/quick_register', json={
    'username': 'Быстрый клиент',
    'phone': '+7 999 222 33 44',
  })
  data = json.loads(r.data)
  assert data['success'] is True

  with app.app_context():
    user = User.query.filter_by(phone='+7 999 222 33 44').first()
    assert user is not None
    assert user.email is None

  r2 = client.post('/login', data={
    'login_mode': 'phone',
    'identifier': '+7 999 222 33 44',
    'password': data['temp_password'],
  }, follow_redirects=True)
  assert r2.status_code == 200
  assert 'Добро пожаловать' in r2.get_data(as_text=True)
