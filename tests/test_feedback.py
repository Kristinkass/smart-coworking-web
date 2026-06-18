"""Client feedback / appeals to staff."""
import json

from internal.models import Notification, User


def test_client_feedback_to_manager(auth_client, app):
    with app.app_context():
        res = auth_client.post(
            '/api/feedback',
            data=json.dumps({
                'recipient': 'manager',
                'title': 'Не работает розетка',
                'message': 'На столе нет питания, прошу помочь',
            }),
            content_type='application/json',
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True

        note = Notification.query.order_by(Notification.id.desc()).first()
        assert note is not None
        assert note.target_audience == 'managers'
        assert note.sender_id == User.query.filter_by(email='client@test.com').first().id


def test_client_feedback_to_admin_with_booking(auth_client, app, sample_booking):
    with app.app_context():
        res = auth_client.post(
            '/api/feedback',
            data=json.dumps({
                'recipient': 'admin',
                'message': 'Переговорная занята посторонними людьми',
                'booking_id': sample_booking,
            }),
            content_type='application/json',
        )
        assert res.status_code == 200
        note = Notification.query.order_by(Notification.id.desc()).first()
        assert note.target_audience == 'admins'
        assert note.booking_id == sample_booking
        assert '№' not in note.message
        assert 'занята посторонними' in note.message


def test_feedback_requires_min_length(auth_client):
    res = auth_client.post(
        '/api/feedback',
        data=json.dumps({'recipient': 'manager', 'message': 'коротко'}),
        content_type='application/json',
    )
    assert res.status_code == 400


def test_manager_cannot_submit_feedback(client, app):
    with app.app_context():
        manager = User(
            email='mgr@test.com', username='Менеджер',
            role='manager', visitor_kind='tariff',
        )
        manager.set_password('123456')
        from internal.models import db
        db.session.add(manager)
        db.session.commit()
        client.post('/login', data={'email': manager.email, 'password': '123456'}, follow_redirects=True)

    res = client.post(
        '/api/feedback',
        data=json.dumps({'recipient': 'manager', 'message': 'Попытка отправить от имени менеджера'}),
        content_type='application/json',
    )
    assert res.status_code == 403


def test_feedback_visible_in_notifications_api(auth_client, client, app):
    """Клиент видит sent_feedback, менеджер — входящие обращения."""
    with app.app_context():
        manager = User(
            email='mgr2@test.com', username='Менеджер2',
            role='manager', visitor_kind='tariff',
        )
        manager.set_password('123456')
        from internal.models import db
        db.session.add(manager)
        db.session.commit()

    res = auth_client.post(
        '/api/feedback',
        data=json.dumps({
            'recipient': 'manager',
            'title': 'Тестовое обращение',
            'message': 'Проверка отображения обращения в личном кабинете',
        }),
        content_type='application/json',
    )
    assert res.status_code == 200

    client_res = auth_client.get('/api/notifications')
    assert client_res.status_code == 200
    client_data = client_res.get_json()
    assert len(client_data.get('sent_feedback') or []) >= 1
    assert any('Тестовое обращение' in (n.get('title') or '') for n in client_data['sent_feedback'])

    auth_client.get('/logout', follow_redirects=True)
    client.post('/login', data={'email': 'mgr2@test.com', 'password': '123456'}, follow_redirects=True)
    mgr_res = client.get('/api/notifications')
    assert mgr_res.status_code == 200
    mgr_data = mgr_res.get_json()
    assert len(mgr_data.get('feedback') or []) >= 1
    assert any('Тестовое обращение' in (n.get('title') or '') for n in mgr_data['feedback'])


def test_feedback_booking_has_location_details(auth_client, app, sample_booking):
    auth_client.post(
        '/api/feedback',
        data=json.dumps({
            'recipient': 'manager',
            'title': 'Проблема со столом',
            'message': 'Стол шатается, прошу проверить',
            'booking_id': sample_booking,
        }),
        content_type='application/json',
    )
    res = auth_client.get('/api/notifications')
    data = res.get_json()
    sent = data.get('sent_feedback') or []
    assert sent
    booking = sent[0].get('booking') or {}
    assert booking.get('detail_lines')
    assert booking.get('location', {}).get('place_code')
    assert any('Этаж' in line for line in booking['detail_lines'])
    assert any('Место:' in line for line in booking['detail_lines'])


def test_client_can_delete_own_feedback(auth_client, app):
    auth_client.post(
        '/api/feedback',
        data=json.dumps({
            'recipient': 'manager',
            'title': 'На удаление',
            'message': 'Тестовое обращение для удаления клиентом',
        }),
        content_type='application/json',
    )
    listing = auth_client.get('/api/notifications').get_json()
    note_id = listing['sent_feedback'][0]['id']
    delete_res = auth_client.delete(f'/api/notifications/{note_id}')
    assert delete_res.status_code == 200
    assert delete_res.get_json()['success'] is True
    after = auth_client.get('/api/notifications').get_json()
    assert not any(n['id'] == note_id for n in after.get('sent_feedback') or [])


def test_manager_can_delete_incoming_feedback(auth_client, client, app):
    with app.app_context():
        manager = User(
            email='mgr3@test.com', username='Менеджер3',
            role='manager', visitor_kind='tariff',
        )
        manager.set_password('123456')
        from internal.models import db
        db.session.add(manager)
        db.session.commit()

    auth_client.post(
        '/api/feedback',
        data=json.dumps({
            'recipient': 'manager',
            'title': 'Удалить менеджером',
            'message': 'Обращение для проверки удаления менеджером',
        }),
        content_type='application/json',
    )
    auth_client.get('/logout', follow_redirects=True)
    client.post('/login', data={'email': 'mgr3@test.com', 'password': '123456'}, follow_redirects=True)
    note_id = client.get('/api/notifications').get_json()['feedback'][0]['id']
    delete_res = client.delete(f'/api/notifications/{note_id}')
    assert delete_res.status_code == 200
    after = client.get('/api/notifications').get_json()
    assert not any(n['id'] == note_id for n in after.get('feedback') or [])
