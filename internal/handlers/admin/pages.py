"""Admin panel HTML pages."""
from datetime import date, datetime, time, timedelta

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from internal.handlers.deps import (
    Booking, CoworkingSchedule, Notification, Place, Subscription, User,
    admin_required, booking_legacy_service, db, get_status_name, get_type_name, models,
    staff_required,
)
from internal.services.booking_service import booking_period_end
from internal.services import booking_service
from internal.utils.formatters import (
    REPORT_SECTIONS,
    build_report_stats,
    format_booking_duration_display,
    format_booking_subscription_name,
    format_booking_time_or_period,
    format_duration,
    format_place_code,
)
from internal.utils.stats import compute_desk_seat_capacity, compute_meeting_room_count
from internal.utils.phone import format_phone_display
from internal.utils.errors import user_error_message


def register_admin_pages_routes(app):
    @app.route('/admin/editor')
    @admin_required
    def admin_editor():
        """Отдельная страница-редактор планировки этажа."""
        ua = (request.headers.get('User-Agent') or '').lower()
        if any(token in ua for token in ('iphone', 'ipod', 'android', 'mobile')):
            return redirect(url_for('admin_dashboard'))
        return render_template('editor.html')



    @app.route('/admin')
    @admin_required
    def admin_dashboard():
        """Админ-панель"""
        try:
            # Общая статистика (только реальные рабочие места, без зон-контейнеров)
            total_users = models.User.query.count()
            total_desk_seats = compute_desk_seat_capacity()
            total_meeting_rooms = compute_meeting_room_count()
            active_bookings = models.Booking.query.filter_by(status='active').count()

            # Доход за сегодня: только завершённые бронирования за сегодняшний день.
            today = datetime.now().date()
            today_revenue_result = db.session.query(db.func.sum(models.Booking.total_price)).filter(
                models.Booking.booking_date == today,
                models.Booking.status == 'completed'
            ).first()
            today_revenue = today_revenue_result[0] if today_revenue_result[0] else 0.0

            # Последние бронирования
            recent_bookings = models.Booking.query.order_by(models.Booking.created_at.desc()).limit(10).all()

            return render_template('admin/admin.html',
                                   total_users=total_users,
                                   total_desk_seats=total_desk_seats,
                                   total_meeting_rooms=total_meeting_rooms,
                                   active_bookings=active_bookings,
                                   today_revenue=today_revenue,
                                   recent_bookings=recent_bookings)
        except Exception as e:
            flash(f'Ошибка при загрузке панели администратора: {user_error_message(e)}', 'error')
            return redirect(url_for('dashboard'))



    @app.route('/admin/users')
    @admin_required
    def admin_users():
        """Управление пользователями"""
        try:
            users = models.User.query.order_by(models.User.created_at.desc()).all()
            return render_template('admin/admin_users.html', users=users, format_phone=format_phone_display)
        except Exception as e:
            flash(f'Ошибка при загрузке пользователей: {user_error_message(e)}', 'error')
            return redirect(url_for('admin_dashboard'))



    @app.route('/manager/clients')
    @staff_required
    def manager_clients():
        """Список клиентов для менеджера"""
        try:
            users = models.User.query.filter_by(role='client').order_by(models.User.created_at.desc()).all()
            return render_template('manager_clients.html', users=users, format_phone=format_phone_display)
        except Exception as e:
            flash(f'Ошибка при загрузке клиентов: {user_error_message(e)}', 'error')
            return redirect(url_for('dashboard'))



    @app.route('/api/users')
    @staff_required
    def api_users():
        """Список пользователей (для менеджера: клиенты)"""
        try:
            role = request.args.get('role', 'client')
            search = request.args.get('search', '')
            query = models.User.query
            if role:
                query = query.filter_by(role=role)
            if search:
                query = query.filter(
                    db.or_(
                        models.User.username.ilike(f'%{search}%'),
                        models.User.email.ilike(f'%{search}%'),
                        models.User.phone.ilike(f'%{search}%')
                    )
                )
            users = query.order_by(models.User.username).all()
            return jsonify({
                'success': True,
                'users': [{
                    'id': u.id,
                    'username': u.username,
                    'email': u.email,
                    'phone': u.phone,
                    'role': u.role
                } for u in users]
            })
        except Exception as e:
            return jsonify({'success': False, 'error': user_error_message(e)}), 500



    @app.route('/admin/bookings')
    @staff_required
    def admin_bookings():
        """Управление бронированиями"""
        try:
            filter_type = request.args.get('filter', 'all')
            selected_booking_id = request.args.get('booking_id', type=int)

            # Базовый запрос с оптимизацией
            query = models.Booking.query.options(
                joinedload(models.Booking.user),
                joinedload(models.Booking.place),
            )

            if filter_type == 'active':
                bookings = query.filter_by(status='active').order_by(
                    models.Booking.booking_date.desc(),
                    models.Booking.start_time.desc()
                ).all()
            elif filter_type == 'completed':
                bookings = query.filter_by(status='completed').order_by(
                    models.Booking.booking_date.desc(),
                    models.Booking.start_time.desc()
                ).all()
            elif filter_type == 'cancelled':
                bookings = query.filter_by(status='cancelled').order_by(
                    models.Booking.booking_date.desc(),
                    models.Booking.start_time.desc()
                ).all()
            else:
                bookings = query.order_by(
                    models.Booking.booking_date.desc(),
                    models.Booking.start_time.desc()
                ).all()

            if selected_booking_id:
                selected = [b for b in bookings if b.id == selected_booking_id]
                rest = [b for b in bookings if b.id != selected_booking_id]
                bookings = selected + rest

            # Рассчитываем статистику
            active_count = models.Booking.query.filter_by(status='active').count()
            completed_count = models.Booking.query.filter_by(status='completed').count()
            cancelled_count = models.Booking.query.filter_by(status='cancelled').count()

            # Уникальные пользователи
            unique_users_result = db.session.query(db.func.count(db.distinct(models.Booking.user_id))).first()
            unique_users = unique_users_result[0] if unique_users_result else 0

            # Доход за сегодня (ДОБАВЛЕНО)
            today = datetime.now().date()
            today_revenue_result = db.session.query(db.func.sum(models.Booking.total_price)).filter(
                models.Booking.booking_date == today,
                models.Booking.status == 'active'
            ).first()
            today_revenue = today_revenue_result[0] if today_revenue_result[0] else 0

            # Бронирования, истекающие сегодня (ДОБАВЛЕНО)
            expiring_soon_count = models.Booking.query.filter(
                models.Booking.status == 'active',
                models.Booking.booking_date == today,
                models.Booking.end_time >= datetime.now().time()
            ).count()

            # Добавляем вычисляемые поля для каждого бронирования
            now = datetime.now()
            for booking in bookings:
                period_end = booking_period_end(booking)

                if booking.status == 'active':
                    booking_date = booking.booking_date

                    if booking.tariff_type in ('weekly', 'monthly'):
                        if period_end < now.date():
                            booking.status = 'completed'
                            booking.time_progress = 100
                            booking.time_remaining = 'Завершено'
                        elif booking.booking_date <= now.date() <= period_end:
                            total_days = (period_end - booking.booking_date).days + 1
                            elapsed_days = (now.date() - booking.booking_date).days + 1
                            booking.time_progress = min(100, (elapsed_days / total_days) * 100)
                            days_left = (period_end - now.date()).days
                            if days_left > 0:
                                booking.time_remaining = f'до {period_end.strftime("%d.%m.%Y")}'
                            else:
                                booking.time_remaining = 'Последний день периода'
                        else:
                            booking.time_progress = 0
                            days_left = (booking.booking_date - now.date()).days
                            booking.time_remaining = f'Через {days_left} дн.'
                        booking.is_expiring_soon = (
                            booking.booking_date <= now.date() <= period_end
                            and (period_end - now.date()).days <= 1
                        )
                    elif booking_date == now.date():
                        start_dt = datetime.combine(booking_date, booking.start_time)
                        end_dt = datetime.combine(booking_date, booking.end_time)
                        now_dt = datetime.now()

                        total_duration = (end_dt - start_dt).total_seconds()
                        elapsed = (now_dt - start_dt).total_seconds()

                        if total_duration > 0:
                            booking.time_progress = min(100, max(0, (elapsed / total_duration) * 100))
                        else:
                            booking.time_progress = 0

                        # Время до окончания
                        time_left = end_dt - now_dt
                        if time_left.total_seconds() > 0:
                            hours = int(time_left.total_seconds() // 3600)
                            minutes = int((time_left.total_seconds() % 3600) // 60)
                            if hours > 0:
                                booking.time_remaining = f"{hours}ч {minutes}м"
                            else:
                                booking.time_remaining = f"{minutes}м"
                        else:
                            booking.time_remaining = "Истекло"
                            booking.status = 'completed'  # Автоматически завершаем
                    else:
                        # Если дата бронирования в прошлом
                        if booking_date < now.date():
                            booking.status = 'completed'  # Автоматически завершаем
                            booking.time_progress = 100
                            booking.time_remaining = "Завершено"
                        else:
                            # Будущее бронирование
                            booking.time_progress = 0
                            days_left = (booking_date - now.date()).days
                            booking.time_remaining = f"Через {days_left} дней"

                    # Проверяем, истекает ли скоро (менее часа) – только почасовые
                    if booking.tariff_type == 'hourly' and booking_date == now.date():
                        end_dt = datetime.combine(booking_date, booking.end_time)
                        time_left = end_dt - datetime.now()
                        booking.is_expiring_soon = time_left.total_seconds() <= 3600  # 1 час
                    else:
                        booking.is_expiring_soon = False
                else:
                    booking.time_progress = 100 if booking.status == 'completed' else 0
                    booking.time_remaining = 'Завершено' if booking.status == 'completed' else 'Отменено'
                    booking.is_expiring_soon = False

            return render_template('admin/admin_bookings.html',
                                   bookings=bookings,
                                   current_filter=filter_type,
                                   active_count=active_count,
                                   completed_count=completed_count,
                                   cancelled_count=cancelled_count,
                                   unique_users=unique_users,
                                   today_revenue=today_revenue,  # ДОБАВЛЕНО
                                   expiring_soon_count=expiring_soon_count,  # ДОБАВЛЕНО
                                   active_bookings_count=active_count,
                                   selected_booking_id=selected_booking_id)
        except Exception as e:
            flash(f'Ошибка при загрузке бронирований: {user_error_message(e)}', 'error')
            return redirect(url_for('admin_dashboard'))



    @app.route('/admin/subscriptions')
    @staff_required
    def admin_subscriptions():
        """Управление абонементами"""
        try:
            from flask_login import current_user
            users = models.User.query.filter_by(role='client', active=True).order_by(
                models.User.phone,
            ).all()
            return render_template(
                'admin/subscriptions.html',
                users=users,
                is_admin=current_user.is_admin(),
                is_manager=current_user.is_manager(),
            )
        except Exception as e:
            flash(f'Ошибка при загрузке абонементов: {user_error_message(e)}', 'error')
            return redirect(url_for('admin_dashboard'))



    @app.route('/admin/location-zones')
    @admin_required
    def admin_location_zones():
        """Управление категориями зон локаций (A – столы, B – переговорные)."""
        return render_template('admin/location_zones.html')


    @app.route('/admin/categories')
    @admin_required
    def admin_categories():
        """Управление категориями мест"""
        try:
            categories = models.PlaceCategory.query.order_by(models.PlaceCategory.kind, models.PlaceCategory.capacity).all()
            return render_template('admin/categories.html', categories=categories)
        except Exception as e:
            flash(f'Ошибка загрузки категорий: {user_error_message(e)}', 'error')
            return redirect(url_for('admin_dashboard'))



    @app.route('/admin/tariffs')
    @staff_required
    def admin_tariffs():
        """Управление тарифами категорий"""
        try:
            categories = models.PlaceCategory.query.order_by(models.PlaceCategory.kind, models.PlaceCategory.capacity).all()
            return render_template('admin/tariffs.html', categories=categories)
        except Exception as e:
            flash(f'Ошибка загрузки тарифов: {user_error_message(e)}', 'error')
            return redirect(url_for('admin_dashboard' if current_user.is_admin() else 'dashboard'))



    @app.route('/admin/schedule')
    @admin_required
    def admin_schedule():
        """Управление расписанием коворкинга"""
        return render_template('admin/schedule.html')



    @app.route('/admin/floors')
    @admin_required
    def admin_floors():
        """Управление этажами коворкинга."""
        return render_template('admin/floors.html')



    @app.route('/api/admin/floors', methods=['GET'])
    @admin_required
    def admin_list_floors():
        from internal.models.coworking import Coworking
        cw = Coworking.get_singleton()
        floors = models.Floor.query.filter_by(coworking_id=cw.id).order_by(models.Floor.number).all()
        result = []
        for f in floors:
            places_count = Place.query.filter_by(floor_id=f.id, active=True).count()
            result.append({
                'id': f.id,
                'number': f.number,
                'name': f.name,
                'label': f.name or f'Этаж {f.number}',
                'places_count': places_count,
            })
        return jsonify({'success': True, 'floors': result})



    @app.route('/api/admin/floors', methods=['POST'])
    @admin_required
    def admin_create_floor():
        from internal.models.coworking import Coworking
        try:
            data = request.json or {}
            number = int(data.get('number', 0))
            name = (data.get('name') or '').strip() or None
            if number < 1:
                return jsonify({'success': False, 'error': 'Номер этажа должен быть ≥ 1'}), 400
            cw = Coworking.ensure_singleton()
            if models.Floor.query.filter_by(coworking_id=cw.id, number=number).first():
                return jsonify({'success': False, 'error': f'Этаж {number} уже существует'}), 400
            floor = models.Floor(coworking_id=cw.id, number=number, name=name)
            db.session.add(floor)
            db.session.commit()

            from internal.layout.repository import LayoutRepository
            from internal.models.location_zone import LocationZoneType, ensure_location_for_zone

            LayoutRepository.provision_new_floor_layout(number, name=name)
            for zt in LocationZoneType.query.filter_by(active=True).all():
                ensure_location_for_zone(number, zt.id_zone_type)

            return jsonify({
                'success': True,
                'floor': {
                    'id': floor.id,
                    'number': floor.number,
                    'name': floor.name,
                    'label': floor.name or f'Этаж {floor.number}',
                },
            })
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Укажите корректный номер этажа'}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': user_error_message(e)}), 500



    @app.route('/api/admin/floors/<int:floor_id>', methods=['PATCH'])
    @admin_required
    def admin_update_floor(floor_id):
        try:
            floor = models.Floor.query.get_or_404(floor_id)
            data = request.json or {}
            if 'name' in data:
                floor.name = (data.get('name') or '').strip() or None
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': user_error_message(e)}), 500



    @app.route('/api/admin/floors/<int:floor_id>', methods=['DELETE'])
    @admin_required
    def admin_delete_floor(floor_id):
        try:
            from internal.layout.repository import LayoutRepository

            floor = models.Floor.query.get_or_404(floor_id)
            places_count = Place.query.filter_by(floor_id=floor.id).count()
            if places_count:
                return jsonify({
                    'success': False,
                    'error': (
                        f'На этаже {floor.number} есть {places_count} '
                        f'{"место" if places_count == 1 else "места" if places_count < 5 else "мест"}. '
                        'Сначала удалите или перенесите их в редакторе.'
                    ),
                }), 400

            LayoutRepository.remove_floor_layout(floor.number)
            db.session.delete(floor)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': user_error_message(e)}), 500



    @app.route('/admin/notifications')
    @staff_required
    def admin_notifications_page():
        """Страница отправки уведомлений"""
        clients = User.query.filter_by(role='client', active=True).order_by(User.phone).all()
        return render_template(
            'admin/notifications_send.html',
            clients=clients,
        )



    @app.route('/admin/reports')
    @admin_required
    def admin_reports():
        """Отчеты и статистика"""
        try:
            from datetime import timedelta

            # Параметры фильтрации
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            report_type = request.args.get('type', 'all')

            # По умолчанию - за последний месяц
            if not start_date_str:
                end_date = datetime.now().date()
                start_date = end_date - timedelta(days=30)
            else:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

                # Дата окончания не может быть в будущем
                today = datetime.now().date()
                if end_date > today:
                    end_date = today
                    flash('Дата окончания скорректирована до сегодняшнего дня', 'warning')

            # Базовый запрос бронирований за период
            query = models.Booking.query.filter(
                models.Booking.booking_date >= start_date,
                models.Booking.booking_date <= end_date
            )

            if report_type == 'completed':
                query = query.filter_by(status='completed')
            elif report_type == 'active':
                query = query.filter_by(status='active')
            elif report_type == 'cancelled':
                query = query.filter_by(status='cancelled')

            bookings = query.options(
                joinedload(models.Booking.user),
                joinedload(models.Booking.place),
                joinedload(models.Booking.subscription),
            ).order_by(models.Booking.booking_date.desc()).all()

            stats, grouped = build_report_stats(bookings)

            return render_template('admin/reports.html',
                                   stats=stats,
                                   bookings=bookings,
                                   grouped_bookings=grouped,
                                   report_sections=REPORT_SECTIONS,
                                   start_date=start_date.strftime('%Y-%m-%d'),
                                   end_date=end_date.strftime('%Y-%m-%d'),
                                   report_type=report_type,
                                   get_type_name=get_type_name,
                                   get_status_name=get_status_name,
                                   format_booking_time_or_period=format_booking_time_or_period,
                                   format_booking_duration_display=format_booking_duration_display,
                                   format_booking_subscription_name=format_booking_subscription_name)
        except Exception as e:
            flash(f'Ошибка при загрузке отчетов: {user_error_message(e)}', 'error')
            return redirect(url_for('admin_dashboard'))



    @app.route('/admin/statistics')
    @admin_required
    def admin_statistics():
        """Расширенная статистика с графиками"""
        from datetime import timedelta
        from sqlalchemy import func

        period = request.args.get('period', 'month')
        end_date = datetime.now().date()

        if period == 'week':
            start_date = end_date - timedelta(days=7)
        elif period == 'quarter':
            start_date = end_date - timedelta(days=90)
        elif period == 'year':
            start_date = end_date - timedelta(days=365)
        else:
            start_date = end_date - timedelta(days=30)

        # Статистика за период
        base_query = models.Booking.query.filter(
            models.Booking.booking_date >= start_date,
            models.Booking.booking_date <= end_date
        )

        total_bookings = base_query.count()
        total_revenue = db.session.query(func.sum(models.Booking.total_price)).filter(
            models.Booking.booking_date >= start_date,
            models.Booking.booking_date <= end_date,
            models.Booking.status.in_(['completed', 'active'])
        ).scalar() or 0

        total_hours = db.session.query(func.sum(models.Booking.duration_hours)).filter(
            models.Booking.booking_date >= start_date,
            models.Booking.booking_date <= end_date,
            models.Booking.status.in_(['completed', 'active']),
            models.Booking.tariff_type == 'hourly',
        ).scalar() or 0

        total_people = db.session.query(func.sum(models.Booking.people_count)).filter(
            models.Booking.booking_date >= start_date,
            models.Booking.booking_date <= end_date,
            models.Booking.status.in_(['completed', 'active']),
        ).scalar() or 0

        stats = {
            'total_bookings': total_bookings,
            'total_revenue': int(round(total_revenue)),
            'total_hours': round(total_hours, 1),
            'total_hours_display': format_duration(total_hours),
            'total_people': int(total_people),
            'completed_bookings': base_query.filter_by(status='completed').count(),
            'active_bookings': base_query.filter_by(status='active').count(),
            'cancelled_bookings': base_query.filter_by(status='cancelled').count()
        }

        # График: число посетителей (people_count) по дням
        daily_stats = db.session.query(
            models.Booking.booking_date,
            func.sum(models.Booking.people_count),
        ).filter(
            models.Booking.booking_date >= start_date,
            models.Booking.booking_date <= end_date,
            models.Booking.status.in_(['completed', 'active']),
        ).group_by(models.Booking.booking_date).order_by(models.Booking.booking_date).all()

        daily_dict = {d[0]: d[1] for d in daily_stats}
        daily_labels = []
        daily_data = []
        for i in range((end_date - start_date).days + 1):
            date = start_date + timedelta(days=i)
            daily_labels.append(date.strftime('%d.%m'))
            daily_data.append(int(daily_dict.get(date, 0) or 0))

        # Данные для графика по категориям – только реальные места (desk, room),
        # без зон-контейнеров (space), которые не бронируются напрямую
        category_stats = db.session.query(
            models.Place.kind,
            func.count(models.Booking.id)
        ).join(models.Booking).filter(
            models.Booking.booking_date >= start_date,
            models.Booking.booking_date <= end_date,
            models.Booking.status.in_(['completed', 'active']),
            models.Place.kind.in_(['desk', 'room']),
        ).group_by(models.Place.kind).all()

        category_labels = [get_type_name(c[0]) for c in category_stats] if category_stats else ['Нет данных']
        category_data = [c[1] for c in category_stats] if category_stats else [0]

        # Данные для графика по часам (пиковые часы)
        hourly_stats = db.session.query(
            func.extract('hour', models.Booking.start_time),
            func.sum(models.Booking.people_count),
        ).filter(
            models.Booking.booking_date >= start_date,
            models.Booking.booking_date <= end_date,
            models.Booking.status.in_(['completed', 'active']),
        ).group_by(func.extract('hour', models.Booking.start_time)).order_by(
            func.extract('hour', models.Booking.start_time),
        ).all()

        hourly_dict = {int(h[0]): int(h[1] or 0) for h in hourly_stats if h[0]}
        coworking_id = booking_service.get_default_coworking_id()
        hour_from, hour_to = (8, 22)
        if coworking_id:
            hour_from, hour_to = booking_service.get_coworking_hour_range(coworking_id)
        hourly_labels = [f"{h:02d}:00" for h in range(hour_from, hour_to)]
        hourly_data = [hourly_dict.get(h, 0) for h in range(hour_from, hour_to)]

        # Топ популярных мест
        top_places_query = db.session.query(
            models.Place,
            func.count(models.Booking.id).label('bookings_count'),
            func.sum(models.Booking.duration_hours).label('total_hours'),
            func.sum(models.Booking.people_count).label('total_people'),
            func.sum(models.Booking.total_price).label('revenue')
        ).join(models.Booking).filter(
            models.Booking.booking_date >= start_date,
            models.Booking.booking_date <= end_date,
            models.Booking.status.in_(['completed', 'active']),
            models.Booking.tariff_type == 'hourly',
        ).group_by(models.Place.id).order_by(func.count(models.Booking.id).desc()).limit(10).all()

        top_places = []
        for place, bookings_count, total_hours_place, total_people_place, revenue in top_places_query:
            top_places.append({
                'code': format_place_code(place),
                'name': place.name,
                'type': get_type_name(place.kind),
                'bookings_count': bookings_count,
                'total_hours': round(total_hours_place or 0, 1),
                'total_hours_display': format_duration(total_hours_place or 0),
                'total_people': int(total_people_place or 0),
                'revenue': int(round(revenue or 0)),
            })

        return render_template('admin/admin_statistics.html',
                             stats=stats,
                             period=period,
                             daily_labels=daily_labels,
                             daily_data=daily_data,
                             category_labels=category_labels,
                             category_data=category_data,
                             hourly_labels=hourly_labels,
                             hourly_data=hourly_data,
                             top_places=top_places)


