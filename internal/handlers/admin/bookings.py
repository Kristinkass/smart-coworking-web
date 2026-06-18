"""Admin booking and user actions."""
from datetime import datetime, time, timedelta

from flask import flash, jsonify, redirect, render_template, request, url_for

from internal.handlers.deps import (
    Booking, User, admin_required, booking_legacy_service, db, models,
    BookingRepository, staff_required, UserRepository,
)
from internal.services import booking_service
from internal.utils.errors import user_error_message


def register_admin_booking_routes(app):
    @app.route('/admin/booking/<int:booking_id>/cancel', methods=['POST'])
    @staff_required
    def admin_cancel_booking(booking_id):
        """Отменить бронирование (админ)"""
        try:
            booking = BookingRepository.get_or_404(booking_id)

            if booking.status != 'active':
                flash('Бронирование уже отменено или завершено', 'error')
                return redirect(url_for('admin_bookings'))

            booking.status = 'cancelled'
            booking_service.refund_subscription_hours_on_cancel(booking)

            db.session.commit()

            flash('Бронирование успешно отменено', 'success')
            return redirect(url_for('admin_bookings'))

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при отмене бронирования: {user_error_message(e)}', 'error')
            return redirect(url_for('admin_bookings'))



    @app.route('/admin/booking/<int:booking_id>/complete', methods=['POST'])
    @admin_required
    def admin_complete_booking(booking_id):
        """Завершить бронирование (админ)"""
        try:
            booking = BookingRepository.get_or_404(booking_id)

            if booking.status != 'active':
                flash('Бронирование не активно', 'error')
                return redirect(url_for('admin_bookings'))

            booking.status = 'completed'

            db.session.commit()

            flash('Бронирование успешно завершено', 'success')
            return redirect(url_for('admin_bookings'))

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при завершении бронирования: {user_error_message(e)}', 'error')
            return redirect(url_for('admin_bookings'))



    @app.route('/admin/user/<int:user_id>/toggle_status', methods=['POST'])
    @admin_required
    def admin_toggle_user_status(user_id):
        """Активировать/деактивировать пользователя"""
        try:
            user = UserRepository.get_or_404(user_id)
            user.active = not user.active

            db.session.commit()

            status = "активирован" if user.active else "деактивирован"
            flash(f'Пользователь {user.email} {status}', 'success')

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при изменении статуса: {user_error_message(e)}', 'error')

        return redirect(url_for('admin_users'))



    @app.route('/admin/user/<int:user_id>/make_admin', methods=['POST'])
    @admin_required
    def admin_make_admin(user_id):
        """Сделать пользователя администратором"""
        try:
            user = UserRepository.get_or_404(user_id)
            user.role = 'admin' if user.role != 'admin' else 'client'

            db.session.commit()

            role = "администратором" if user.role == 'admin' else "пользователем"
            flash(f'Пользователь {user.email} теперь {role}', 'success')

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при изменении роли: {user_error_message(e)}', 'error')

        return redirect(url_for('admin_users'))



    @app.route('/admin/user/<int:user_id>/set_role/<role>', methods=['POST'])
    @admin_required
    def admin_set_user_role(user_id, role):
        try:
            if role not in ('admin', 'manager', 'client'):
                flash('Некорректная роль пользователя', 'error')
                return redirect(url_for('admin_users'))

            user = UserRepository.get_or_404(user_id)
            user.role = role
            db.session.commit()

            role_names = {
                'admin': 'администратором',
                'manager': 'менеджером',
                'client': 'клиентом',
            }
            flash(f'Пользователь {user.email} теперь {role_names[role]}', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при изменении роли: {user_error_message(e)}', 'error')

        return redirect(url_for('admin_users'))



    @app.route('/admin/booking/<int:booking_id>/extend', methods=['POST'])
    @staff_required
    def admin_extend_booking(booking_id):
        """Продлить бронирование"""
        try:
            booking = BookingRepository.get_or_404(booking_id)
            data = request.json or {}
            hours = int(data.get('hours', 1))

            ok, err, payload = booking_service.extend_booking_hours(booking, hours)
            if not ok:
                return jsonify({'success': False, 'error': err}), 400

            db.session.commit()
            return jsonify({
                'success': True,
                'message': payload.get('message', 'Бронирование успешно продлено'),
                'new_end_time': payload.get('new_end_time'),
                'new_total_price': payload.get('new_total_price'),
                'additional_cost': payload.get('additional_cost', 0),
            })

        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': user_error_message(e)}), 500



    @app.route('/admin/booking/<int:booking_id>/restore', methods=['POST'])
    @staff_required
    def admin_restore_booking(booking_id):
        """Восстановить отмененное бронирование"""
        try:
            booking = BookingRepository.get_or_404(booking_id)

            if booking.status != 'cancelled':
                return jsonify({'success': False, 'error': 'Можно восстанавливать только отмененные бронирования'}), 400

            # Проверяем, не прошло ли время бронирования (с учётом недельного/месячного периода)
            now = datetime.now()
            if booking.effective_end_datetime() < now:
                return jsonify({'success': False, 'error': 'Нельзя восстановить истекшее бронирование'}), 400

            # Проверяем, не занято ли место на это время сейчас
            conflicts = models.Booking.query.filter(
                models.Booking.place_id == booking.place_id,
                models.Booking.booking_date == booking.booking_date,
                models.Booking.status == 'active',
                db.or_(
                    db.and_(
                        models.Booking.start_time <= booking.start_time,
                        models.Booking.end_time > booking.start_time
                    ),
                    db.and_(
                        models.Booking.start_time < booking.end_time,
                        models.Booking.end_time >= booking.end_time
                    ),
                    db.and_(
                        models.Booking.start_time >= booking.start_time,
                        models.Booking.end_time <= booking.end_time
                    )
                )
            ).first()

            if conflicts:
                return jsonify({
                    'success': False,
                    'error': 'Нельзя восстановить бронирование - место занято на это время'
                }), 400

            booking.status = 'active'
            db.session.commit()

            return jsonify({
                'success': True,
                'message': 'Бронирование успешно восстановлено'
            })

        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': user_error_message(e)}), 500



    @app.route('/admin/user/<int:user_id>/notify', methods=['POST'])
    @admin_required
    def admin_notify_user(user_id):
        """Отправить уведомление пользователю"""
        try:
            user = UserRepository.get_or_404(user_id)
            data = request.json
            message = data.get('message')

            if not message:
                return jsonify({'success': False, 'error': 'Сообщение не может быть пустым'}), 400

            # Здесь можно добавить логику отправки email или push
            print(f"Отправка уведомления пользователю {user.email}: {message}")

            return jsonify({
                'success': True,
                'message': f'Уведомление отправлено пользователю {user.username}'
            })

        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': user_error_message(e)}), 500


