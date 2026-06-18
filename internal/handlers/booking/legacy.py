"""Legacy booking API."""
from datetime import date, datetime, time, timedelta

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from internal.handlers.deps import (
    Booking, Place, Subscription, User, booking_legacy_service, db, models,
    BookingRepository, PlaceRepository, UserRepository,
)
from internal.services import booking_service
from internal.utils.errors import user_error_message


def register_booking_legacy_routes(app):
    @app.route('/api/check_booking_legacy', methods=['POST'])
    @login_required
    def check_booking_legacy():
        """Проверить доступность времени (старая версия)"""
        try:
            data = request.json
            required_fields = ['place_id', 'date', 'start_time', 'end_time']

            for field in required_fields:
                if field not in data:
                    return jsonify({'success': False, 'error': f'Отсутствует поле: {field}'}), 400

            place = PlaceRepository.get_by_id(data['place_id'])
            if not place:
                return jsonify({'success': False, 'error': 'Место не найдено'}), 404

            # Получаем количество человек
            people_count = data.get('people_count', 1)
            try:
                people_count = int(people_count)
                if people_count < 1:
                    people_count = 1
                if people_count > place.capacity:
                    people_count = place.capacity
            except (TypeError, ValueError):
                people_count = 1

            is_available, message = booking_legacy_service.is_time_slot_available(
                data['place_id'],
                data['date'],
                data['start_time'],
                data['end_time'],
                people_count=people_count,
            )

            start_dt = datetime.strptime(data['start_time'], '%H:%M')
            end_dt = datetime.strptime(data['end_time'], '%H:%M')
            duration_hours = (end_dt - start_dt).seconds / 3600

            if is_available:
                return jsonify({
                    'success': True,
                    'is_available': True,
                    'duration_hours': round(duration_hours, 2),
                    'people_count': people_count,
                    'message': message
                })
            else:
                return jsonify({
                    'success': True,
                    'is_available': False,
                    'message': message
                })

        except Exception as e:
            return jsonify({'success': False, 'error': user_error_message(e)}), 500



    @app.route('/api/create_booking_legacy', methods=['POST'])
    @login_required
    def create_booking_legacy():
        """Создать одно бронирование (старая версия)"""
        try:
            data = request.json

            required_fields = ['place_id', 'date', 'start_time', 'end_time']
            for field in required_fields:
                if field not in data:
                    return jsonify({'error': f'Отсутствует поле: {field}'}), 400

            place = PlaceRepository.get_by_id(data['place_id'])
            if not place:
                return jsonify({'error': 'Место не найдено'}), 404

            # Определяем целевого пользователя (только менеджер может бронировать за клиента)
            target_user_id = current_user.id
            if data.get('user_id') and current_user.is_manager():
                target_user = UserRepository.get_by_id(data['user_id'])
                if target_user and target_user.role == 'client':
                    target_user_id = target_user.id

            # Получаем количество человек (по умолчанию 1)
            people_count = data.get('people_count', 1)
            try:
                people_count = int(people_count)
                if people_count < 1:
                    people_count = 1
                if people_count > place.capacity:
                    people_count = place.capacity
            except (TypeError, ValueError):
                people_count = 1

            # Получаем тип тарифа из запроса (по умолчанию hourly)
            tariff_type = data.get('tariff_type', 'hourly')

            start_dt = datetime.strptime(data['start_time'], '%H:%M')
            end_dt = datetime.strptime(data['end_time'], '%H:%M')
            duration_hours = (end_dt - start_dt).seconds / 3600

            # Проверяем доступность времени с учётом people_count и тарифа
            is_available, message = booking_legacy_service.is_time_slot_available(
                data['place_id'],
                data['date'],
                data['start_time'],
                data['end_time'],
                people_count=people_count,
                user_id=target_user_id,
                tariff_type=tariff_type,
            )

            if not is_available:
                return jsonify({'error': message}), 400

            # Рассчитываем цену на основе тарифа
            total_price = 0
            category_tariff_id = None

            if place.category:
                tariff = place.category.get_tariff(tariff_type)
                if tariff:
                    category_tariff_id = tariff.id
                    price_per_person = tariff.price / place.capacity
                    if tariff_type == 'hourly':
                        total_price = duration_hours * price_per_person * people_count
                    else:
                        total_price = price_per_person * people_count
                else:
                    # Если тариф не найден, используем hourly по умолчанию с ценой 0
                    tariff_type = 'hourly'
            else:
                return jsonify({'error': 'У места не назначена категория'}), 400

            booking_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            start_time = datetime.strptime(data['start_time'], '%H:%M').time()
            end_time = datetime.strptime(data['end_time'], '%H:%M').time()

            if tariff_type in ('weekly', 'monthly'):
                days = 7 if tariff_type == 'weekly' else 30
                day_hours = (
                    datetime.combine(date.today(), end_time) - datetime.combine(date.today(), start_time)
                ).seconds / 3600
                duration_hours = day_hours * days
                end_date = booking_date + timedelta(days=days - 1)
                check_date = booking_date
                while check_date <= end_date:
                    ok, msg = booking_legacy_service.is_time_slot_available(
                        data['place_id'],
                        check_date.strftime('%Y-%m-%d'),
                        data['start_time'],
                        data['end_time'],
                        people_count=people_count,
                        user_id=target_user_id,
                        tariff_type=tariff_type,
                    )
                    if not ok:
                        return jsonify({'error': msg}), 400
                    check_date += timedelta(days=1)
            else:
                end_time = datetime.strptime(data['end_time'], '%H:%M').time()

            booking = models.Booking(
                user_id=target_user_id,
                place_id=data['place_id'],
                booking_date=booking_date,
                start_time=start_time,
                end_time=end_time,
                people_count=people_count,
                tariff_type=tariff_type,
                duration_hours=duration_hours,
                total_price=round(total_price, 2),
                category_tariff_id=category_tariff_id,
                status='active',
            )

            db.session.add(booking)
            db.session.commit()

            people_msg = f' для {people_count} чел.' if people_count > 1 else ''
            if tariff_type == 'weekly':
                period_msg = ' на неделю'
            elif tariff_type == 'monthly':
                period_msg = ' на месяц'
            else:
                period_msg = ''

            return jsonify({
                'success': True,
                'booking_id': booking.id,
                'total_price': round(total_price, 2),
                'people_count': people_count,
                'message': f'Бронирование создано{people_msg}{period_msg}'
            }), 201

        except Exception as e:
            db.session.rollback()
            return jsonify({'error': user_error_message(e)}), 500



    @app.route('/api/subscription/book', methods=['POST'])
    @login_required
    def book_with_subscription():
        """Создать бронирование по абонементу (списание часов)."""
        try:
            data = request.json
            required = ['subscription_id', 'place_id', 'date', 'start_time', 'end_time']
            for field in required:
                if field not in data:
                    return jsonify({'success': False, 'error': f'Отсутствует поле: {field}'}), 400

            subscription = Subscription.query.get(data['subscription_id'])
            if not subscription:
                return jsonify({'success': False, 'error': 'Абонемент не найден'}), 404

            target_user_id = current_user.id
            if data.get('user_id') and (current_user.is_manager() or current_user.is_admin()):
                target_user = UserRepository.get_by_id(data['user_id'])
                if target_user and target_user.role == 'client':
                    target_user_id = target_user.id

            if subscription.user_id != target_user_id:
                return jsonify({'success': False, 'error': 'Абонемент не принадлежит этому клиенту'}), 403

            if not subscription.is_valid():
                return jsonify({'success': False, 'error': 'Абонемент не действителен'}), 400

            place = PlaceRepository.get_by_id(data['place_id'])
            if not place:
                return jsonify({'success': False, 'error': 'Место не найдено'}), 404
            if place.is_on_maintenance():
                return jsonify({'success': False, 'error': 'Место находится на обслуживании'}), 400

            if not subscription.can_book_place(place.kind):
                return jsonify({'success': False, 'error': 'Абонемент не распространяется на этот тип места'}), 400

            people_count = int(data.get('people_count', 1))
            if people_count != 1:
                return jsonify({
                    'success': False,
                    'error': 'По абонементу можно бронировать только на 1 человека',
                }), 400

            booking_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            start_time = datetime.strptime(data['start_time'], '%H:%M').time()
            end_dt = datetime.strptime(data['end_time'], '%H:%M')
            start_dt = datetime.strptime(data['start_time'], '%H:%M')
            duration_hours = (end_dt - start_dt).seconds / 3600
            end_time = end_dt.time()

            if subscription.hours_limit is not None and subscription.hours_remaining < duration_hours:
                return jsonify({
                    'success': False,
                    'error': f'Недостаточно часов в абонементе. Осталось: {subscription.hours_remaining} ч'
                }), 400

            is_available, message = booking_legacy_service.is_time_slot_available(
                data['place_id'],
                data['date'],
                data['start_time'],
                data['end_time'],
                user_id=target_user_id,
                tariff_type='hourly',
            )
            if not is_available:
                return jsonify({'success': False, 'error': message}), 400

            booking = models.Booking(
                user_id=target_user_id,
                place_id=data['place_id'],
                booking_date=booking_date,
                start_time=start_time,
                end_time=end_time,
                tariff_type='hourly',
                duration_hours=duration_hours,
                total_price=0,
                people_count=1,
                status='active',
                subscription_id=subscription.id,
            )

            subscription.hours_used += duration_hours

            db.session.add(booking)
            db.session.commit()

            return jsonify({
                'success': True,
                'booking_id': booking.id,
                'hours_used': duration_hours,
                'hours_remaining': subscription.hours_remaining,
                'total_price': 0,
                'message': (
                    f'Бронирование создано по абонементу. '
                    f'Использовано {duration_hours} ч, осталось {subscription.hours_remaining} ч'
                ),
            }), 201

        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': user_error_message(e)}), 500



    # ================== НОВЫЕ API ДЛЯ ЛИЧНОГО КАБИНЕТА ==================


    @app.route('/api/extend_booking', methods=['POST'])
    @login_required
    def extend_booking():
        """Продлить бронирование на выбранное количество часов."""
        try:
            data = request.get_json(silent=True) or {}
            booking_id = data.get('booking_id')
            hours = int(data.get('hours', 1) or 1)

            if not booking_id:
                return jsonify({'success': False, 'error': 'ID бронирования не указан'}), 400

            booking = BookingRepository.get_by_id(booking_id)
            if not booking:
                return jsonify({'success': False, 'error': 'Бронирование не найдено'}), 404

            if booking.user_id != current_user.id and not current_user.is_admin() and not current_user.is_manager():
                return jsonify({'success': False, 'error': 'Нет доступа к этому бронированию'}), 403

            ok, err, payload = booking_service.extend_booking_hours(booking, hours)
            if not ok:
                return jsonify({'success': False, 'error': err}), 400

            db.session.commit()
            return jsonify({'success': True, **payload})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': user_error_message(e)}), 500


