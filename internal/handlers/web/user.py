"""User profile and stats API."""
from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from internal.handlers.deps import Booking, Place, User, db, models, BookingRepository
from internal.utils.phone import normalize_phone, digits_only
from internal.utils.errors import user_error_message


def register_user_routes(app):
    @app.route('/api/submit_rating', methods=['POST'])
    @login_required
    def submit_rating():
        """Отправить оценку для завершенного бронирования"""
        try:
            data = request.json
            booking_id = data.get('booking_id')
            rating = data.get('rating')

            if not booking_id or not rating:
                return jsonify({'success': False, 'error': 'Не все данные предоставлены'}), 400

            # Проверяем, что оценка от 1 до 5
            if not (1 <= rating <= 5):
                return jsonify({'success': False, 'error': 'Оценка должна быть от 1 до 5'}), 400

            # Находим бронирование
            booking = BookingRepository.get_by_id(booking_id)
            if not booking:
                return jsonify({'success': False, 'error': 'Бронирование не найдено'}), 404

            # Проверяем, что бронирование принадлежит текущему пользователю
            if booking.user_id != current_user.id:
                return jsonify({'success': False, 'error': 'Нет доступа к этому бронированию'}), 403

            # Проверяем, что бронирование завершено
            if booking.status != 'completed':
                return jsonify({'success': False, 'error': 'Можно оценивать только завершенные бронирования'}), 400

            # Проверяем, что оценка еще не ставилась
            if booking.user_rating:
                return jsonify({'success': False, 'error': 'Вы уже оценили это бронирование'}), 400

            # Обновляем оценку в бронировании
            booking.user_rating = rating

            # Создаем запись в таблице оценок
            new_rating = models.Rating(
                user_id=current_user.id,
                place_id=booking.place_id,
                booking_id=booking_id,
                score=rating
            )
            db.session.add(new_rating)

            # Обновляем рейтинг места
            place = booking.place
            if place and place.update_rating(rating):
                db.session.commit()
                return jsonify({
                    'success': True,
                    'message': 'Спасибо за вашу оценку!',
                    'place_rating': round(place.rating, 1)
                })
            else:
                db.session.rollback()
                return jsonify({'success': False, 'error': 'Ошибка обновления рейтинга места'}), 500

        except Exception as e:
            db.session.rollback()
            print(f"Ошибка при отправке оценки: {e}")
            return jsonify({'success': False, 'error': user_error_message(e)}), 500



    @app.route('/api/update_profile', methods=['POST'])
    @login_required
    def update_profile():
        """Обновить профиль (имя и телефон; email неизменяем)"""
        try:
            data = request.json
            username = data.get('username')
            phone = data.get('phone')

            if not username:
                return jsonify({'success': False, 'error': 'Имя пользователя обязательно'}), 400

            if data.get('email') and data.get('email') != current_user.email:
                return jsonify({'success': False, 'error': 'Изменить email нельзя'}), 400

            current_user.username = username
            if phone is not None:
                stripped = phone.strip()
                if stripped:
                    normalized = normalize_phone(stripped)
                    digits = digits_only(normalized or stripped)
                    if len(digits) != 11 or not digits.startswith('7'):
                        return jsonify({'success': False, 'error': 'Введите корректный номер телефона'}), 400
                    current_user.phone = normalized
                else:
                    current_user.phone = None

            db.session.commit()

            return jsonify({
                'success': True,
                'message': 'Профиль успешно обновлен'
            })

        except Exception as e:
            db.session.rollback()
            print(f"Ошибка при обновлении профиля: {e}")
            return jsonify({'success': False, 'error': user_error_message(e)}), 500



    @app.route('/api/change_password', methods=['POST'])
    @login_required
    def change_password():
        """Изменить пароль пользователя"""
        try:
            data = request.json
            current_password = data.get('current_password')
            new_password = data.get('new_password')

            if not current_password or not new_password:
                return jsonify({'success': False, 'error': 'Все поля обязательны'}), 400

            # Проверяем текущий пароль
            if not current_user.check_password(current_password):
                return jsonify({'success': False, 'error': 'Текущий пароль неверен'}), 400

            current_user.set_password(new_password)
            db.session.commit()

            return jsonify({
                'success': True,
                'message': 'Пароль успешно изменен'
            })

        except Exception as e:
            db.session.rollback()
            print(f"Ошибка при смене пароля: {e}")
            return jsonify({'success': False, 'error': user_error_message(e)}), 500



    @app.route('/api/user_stats', methods=['GET'])
    @login_required
    def user_stats():
        """Получить статистику пользователя для dashboard"""
        try:
            # Общее количество бронирований
            total_bookings = models.Booking.query.filter_by(user_id=current_user.id).count()

            # Активные бронирования
            active_bookings = models.Booking.query.filter_by(
                user_id=current_user.id,
                status='active'
            ).count()

            # Завершенные бронирования
            completed_bookings = models.Booking.query.filter_by(
                user_id=current_user.id,
                status='completed'
            ).count()

            # Общая сумма потраченная
            total_spent = db.session.query(db.func.sum(models.Booking.total_price)).filter(
                models.Booking.user_id == current_user.id,
                models.Booking.status == 'completed'
            ).scalar() or 0

            # Средняя оценка пользователя
            avg_rating_result = db.session.query(db.func.avg(models.Booking.user_rating)).filter(
                models.Booking.user_id == current_user.id,
                models.Booking.user_rating.isnot(None)
            ).first()
            avg_user_rating = round(avg_rating_result[0], 1) if avg_rating_result[0] else "Нет оценок"

            # Часто бронируемые места (топ 5)
            from sqlalchemy import func

            frequent_places = db.session.query(
                models.Place.name,
                func.count(models.Booking.id).label('count')
            ).join(
                models.Booking, models.Booking.place_id == models.Place.id
            ).filter(
                models.Booking.user_id == current_user.id
            ).group_by(
                models.Place.id
            ).order_by(
                func.count(models.Booking.id).desc()
            ).limit(5).all()

            frequent_places_list = [
                {'name': place.name, 'count': count}
                for place, count in frequent_places
            ]

            return jsonify({
                'total_bookings': total_bookings,
                'active_bookings': active_bookings,
                'completed_bookings': completed_bookings,
                'total_spent': round(total_spent, 2),
                'avg_user_rating': avg_user_rating,
                'frequent_places': frequent_places_list
            })

        except Exception as e:
            print(f"Ошибка при получении статистики: {e}")
            return jsonify({'error': user_error_message(e)}), 500

    # ================== АДМИН ПАНЕЛЬ ==================

