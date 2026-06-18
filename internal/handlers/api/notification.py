"""Notification API."""
from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from internal.handlers.deps import Booking, Notification, User, admin_required, db, models, staff_required

AUDIENCE_LABELS = {
    'all': 'Все пользователи',
    'clients': 'Клиенты',
    'managers': 'Менеджеры',
    'admins': 'Администраторы',
}


def register_notification_routes(app):
    def _feedback_query_options():
        from internal.models.place import Place
        from internal.models.coworking import Location

        return (
            joinedload(models.Notification.sender),
            joinedload(models.Notification.booking)
            .joinedload(Booking.place)
            .joinedload(Place.location)
            .joinedload(Location.zone_type),
            joinedload(models.Notification.booking)
            .joinedload(Booking.place)
            .joinedload(Place.floor),
        )

    def _can_delete_notification(notification):
        if not notification.is_feedback():
            return False, 'Можно удалять только обращения клиентов'
        if current_user.role == 'client':
            if notification.sender_id != current_user.id:
                return False, 'Недостаточно прав'
            return True, None
        if current_user.is_admin():
            return True, None
        if current_user.role == 'manager':
            if notification.target_audience != 'managers':
                return False, 'Обращение адресовано не менеджерам'
            return True, None
        return False, 'Недостаточно прав'

    def _client_feedback_query():
        """Обращения клиентов (sender – client, получатель – staff)."""
        return models.Notification.query.filter(
            models.Notification.sender_id.isnot(None),
            models.Notification.target_audience.in_(['managers', 'admins']),
        ).join(User, models.Notification.sender_id == User.id_user).filter(
            User.role == 'client'
        )

    @app.route('/api/notifications', methods=['GET'])
    @login_required
    def get_notifications():
        """Получить уведомления текущего пользователя"""
        try:
            query = models.Notification.query
            if current_user.role == 'client':
                query = query.filter(
                    db.or_(
                        models.Notification.target_audience == 'all',
                        models.Notification.target_audience == 'clients',
                        models.Notification.user_id == current_user.id
                    )
                )
            elif current_user.role == 'manager':
                query = query.filter(
                    db.or_(
                        models.Notification.target_audience == 'all',
                        models.Notification.target_audience == 'managers',
                        models.Notification.user_id == current_user.id
                    )
                )
            else:
                query = query.filter(
                    db.or_(
                        models.Notification.target_audience == 'all',
                        models.Notification.target_audience == 'managers',
                        models.Notification.target_audience == 'admins',
                        models.Notification.user_id == current_user.id
                    )
                )
            notifications = query.order_by(models.Notification.created_at.desc()).limit(50).all()
            payload = [n.to_dict() for n in notifications]
            system = [n for n in payload if n['kind'] == 'system']

            sent_feedback = []
            feedback = []
            if current_user.role == 'client':
                sent = models.Notification.query.options(
                    *_feedback_query_options()
                ).filter(
                    models.Notification.sender_id == current_user.id,
                    models.Notification.target_audience.in_(['managers', 'admins']),
                ).order_by(models.Notification.created_at.desc()).limit(20).all()
                sent_feedback = [n.to_dict() for n in sent]
            elif current_user.role == 'manager':
                incoming = _client_feedback_query().options(
                    *_feedback_query_options()
                ).filter(
                    models.Notification.target_audience == 'managers',
                ).order_by(models.Notification.created_at.desc()).limit(50).all()
                feedback = [n.to_dict() for n in incoming]
            else:
                incoming = _client_feedback_query().options(
                    *_feedback_query_options()
                ).filter(
                    models.Notification.target_audience == 'admins',
                ).order_by(models.Notification.created_at.desc()).limit(50).all()
                feedback = [n.to_dict() for n in incoming]

            return jsonify({
                'system': system,
                'feedback': feedback,
                'sent_feedback': sent_feedback,
                'notifications': payload,
                'unread_count': sum(1 for n in payload if not n['is_read']),
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
    @login_required
    def mark_notification_read(notification_id):
        """Отметить уведомление как прочитанное."""
        try:
            notification = Notification.query.get_or_404(notification_id)
            notification.is_read = True
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/notifications/<int:notification_id>', methods=['DELETE'])
    @login_required
    def delete_notification(notification_id):
        """Удалить обращение из истории (клиент – свои, staff – входящие)."""
        try:
            notification = Notification.query.get_or_404(notification_id)
            ok, err = _can_delete_notification(notification)
            if not ok:
                return jsonify({'success': False, 'error': err}), 403
            db.session.delete(notification)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Обращение удалено'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/feedback', methods=['POST'])
    @login_required
    def submit_feedback():
        """Клиент направляет обращение менеджеру или администратору."""
        if current_user.role != 'client':
            return jsonify({'success': False, 'error': 'Обращения доступны только клиентам'}), 403

        try:
            data = request.json or {}
            message = (data.get('message') or '').strip()
            recipient = (data.get('recipient') or 'manager').strip().lower()
            title = (data.get('title') or '').strip() or 'Обращение клиента'
            booking_id = data.get('booking_id')

            if len(message) < 10:
                return jsonify({
                    'success': False,
                    'error': 'Опишите проблему не короче 10 символов',
                }), 400

            if recipient not in ('manager', 'admin'):
                return jsonify({'success': False, 'error': 'Укажите получателя: manager или admin'}), 400

            target_audience = 'managers' if recipient == 'manager' else 'admins'
            linked_booking_id = None

            if booking_id:
                booking = Booking.query.get(booking_id)
                if not booking or booking.user_id != current_user.id:
                    return jsonify({'success': False, 'error': 'Бронирование не найдено'}), 404
                if booking.status not in ('active', 'completed'):
                    return jsonify({
                        'success': False,
                        'error': 'Можно указать только активное или завершённое бронирование',
                    }), 400
                linked_booking_id = booking.id

            notification = models.Notification(
                title=title,
                message=message,
                target_audience=target_audience,
                sender_id=current_user.id,
                booking_id=linked_booking_id,
            )
            db.session.add(notification)
            db.session.commit()

            return jsonify({
                'success': True,
                'message': 'Обращение отправлено. Сотрудник получит его в служебном интерфейсе.',
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/admin/notifications', methods=['POST'])
    @staff_required
    def send_notification():
        """Отправить уведомление группе пользователей"""
        try:
            data = request.json
            title = data.get('title', '').strip()
            message = data.get('message', '').strip()
            target = data.get('target_audience', 'all')
            user_id = data.get('user_id')

            if not title or not message:
                return jsonify({'error': 'Заголовок и текст обязательны'}), 400

            sender_id = current_user.id if current_user.is_authenticated else None

            if user_id:
                notification = models.Notification(
                    title=title,
                    message=message,
                    target_audience='all',
                    user_id=int(user_id),
                    sender_id=sender_id,
                )
                db.session.add(notification)
            else:
                notification = models.Notification(
                    title=title,
                    message=message,
                    target_audience=target,
                    sender_id=sender_id,
                )
                db.session.add(notification)

            db.session.commit()
            return jsonify({'success': True, 'message': 'Уведомление отправлено'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/admin/notifications/history', methods=['GET'])
    @staff_required
    def notification_history():
        """История отправленных уведомлений для менеджеров и админов."""
        try:
            limit = int(request.args.get('limit', 100))
            sent = models.Notification.query.order_by(
                models.Notification.created_at.desc()
            ).limit(limit).all()

            result = []
            for n in sent:
                entry = n.to_dict()
                if n.user_id and n.user:
                    entry['audience_label'] = n.user.username
                elif n.sender_id and n.sender and n.sender.role == 'client':
                    recipient = AUDIENCE_LABELS.get(n.target_audience, n.target_audience)
                    entry['audience_label'] = f'Обращение → {recipient}'
                else:
                    entry['audience_label'] = AUDIENCE_LABELS.get(n.target_audience, n.target_audience)
                result.append(entry)

            return jsonify({'success': True, 'history': result})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

