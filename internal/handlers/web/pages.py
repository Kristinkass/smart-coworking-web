"""Public and user-facing pages."""
from datetime import date, datetime, time, timedelta

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from internal.handlers.deps import Booking, Place, User, db, models
from internal.utils.formatters import (
    format_booking_location,
    format_duration,
    format_duration_mins,
    get_status_name,
    get_type_name,
    render_stars,
)
from internal.utils.phone import format_phone_display
from internal.utils.errors import user_error_message


def register_pages_routes(app):
    @app.route('/api/public/stats')
    def public_stats():
        """Публичная сводка для главной страницы (без авторизации)."""
        from internal.utils.stats import compute_desk_seat_capacity, compute_meeting_room_count
        today = datetime.now().date()
        total_desk_seats = compute_desk_seat_capacity()
        total_meeting_rooms = compute_meeting_room_count()
        total_users = User.query.filter_by(role='client', active=True).count()
        today_bookings = Booking.query.filter(
            Booking.booking_date == today,
            Booking.status.in_(('active', 'completed')),
        ).count()
        return jsonify({
            'total_places': total_desk_seats,
            'total_desk_seats': total_desk_seats,
            'total_meeting_rooms': total_meeting_rooms,
            'total_users': total_users,
            'today_bookings': today_bookings,
        })

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        return render_template('index.html')



    @app.route('/dashboard')
    @login_required
    def dashboard():
        """Личный кабинет с вкладками"""
        # Получаем фильтры из параметров запроса
        period_filter = request.args.get('period', 'all')  # all, today, week, half_month, month

        today = datetime.now().date()

        # Определяем диапазон дат на основе периода
        date_start = None
        date_end = None

        if period_filter == 'today':
            date_start = today
            date_end = today
        elif period_filter == 'week':
            date_start = today - timedelta(days=7)
            date_end = today
        elif period_filter == 'half_month':
            date_start = today - timedelta(days=15)
            date_end = today
        elif period_filter == 'month':
            date_start = today.replace(day=1)
            date_end = today

        # Активные бронирования (всегда показываем активные отдельно)
        active_bookings = models.Booking.query.filter_by(
            user_id=current_user.id,
            status='active'
        ).order_by(models.Booking.booking_date, models.Booking.start_time).all()
        for booking in active_bookings:
            booking.location_label = format_booking_location(booking.place)

        # История бронирований (завершённые и отменённые)
        history_per_page = 10
        history_page = request.args.get('history_page', 1, type=int) or 1
        history_query = models.Booking.query.filter(
            models.Booking.user_id == current_user.id,
            models.Booking.status.in_(['completed', 'cancelled'])
        )
        if date_start and date_end:
            history_query = history_query.filter(
                models.Booking.booking_date >= date_start,
                models.Booking.booking_date <= date_end
            )
        history_total = history_query.count()
        history_pages = max(1, (history_total + history_per_page - 1) // history_per_page)
        if history_page < 1:
            history_page = 1
        elif history_page > history_pages:
            history_page = history_pages
        history_bookings = (
            history_query
            .order_by(models.Booking.created_at.desc())
            .offset((history_page - 1) * history_per_page)
            .limit(history_per_page)
            .all()
        )
        for booking in history_bookings:
            booking.location_label = format_booking_location(booking.place)

        # Общая статистика пользователя (разделенная по статусам)
        total_bookings_all = models.Booking.query.filter_by(user_id=current_user.id).count()
        total_bookings_completed = models.Booking.query.filter_by(user_id=current_user.id, status='completed').count()
        total_bookings_cancelled = models.Booking.query.filter_by(user_id=current_user.id, status='cancelled').count()
        total_bookings_active = models.Booking.query.filter_by(user_id=current_user.id, status='active').count()

        # Общий расход — только завершённые бронирования за всё время
        total_spent = db.session.query(db.func.sum(models.Booking.total_price)).filter(
            models.Booking.user_id == current_user.id,
            models.Booking.status == 'completed',
        ).scalar() or 0

        # Доход за сегодня (только завершенные бронирования сегодня, не отмененные)
        today_income = db.session.query(db.func.sum(models.Booking.total_price)).filter(
            models.Booking.user_id == current_user.id,
            models.Booking.status == 'completed',
            models.Booking.booking_date == today
        ).scalar() or 0

        user_subscriptions = models.Subscription.query.filter_by(
            user_id=current_user.id, is_template=False,
        ).all()
        subscription_templates = models.Subscription.query.filter_by(
            is_template=True, active=True,
        ).order_by(models.Subscription.price).all()

        cancel_cutoff = datetime.now() + timedelta(hours=1)
        cancellable_ids = {
            b.id for b in active_bookings
            if datetime.combine(b.booking_date, b.start_time) > cancel_cutoff
        }

        feedback_bookings = models.Booking.query.filter(
            models.Booking.user_id == current_user.id,
            models.Booking.status.in_(['active', 'completed']),
        ).order_by(
            models.Booking.booking_date.desc(),
            models.Booking.start_time.desc(),
        ).limit(30).all()

        return render_template('dashboard.html',
                               active_bookings=active_bookings,
                               history_bookings=history_bookings,
                               history_page=history_page,
                               history_pages=history_pages,
                               history_total=history_total,
                               feedback_bookings=feedback_bookings,
                               total_bookings=total_bookings_all,
                               total_bookings_completed=total_bookings_completed,
                               total_bookings_cancelled=total_bookings_cancelled,
                               total_bookings_active=total_bookings_active,
                               total_spent=total_spent,
                               today_income=today_income,
                               user_subscriptions=user_subscriptions,
                               subscription_templates=subscription_templates,
                               period_filter=period_filter,
                               get_type_name=get_type_name,
                               get_status_name=get_status_name,
                               render_stars=render_stars,
                               format_duration=format_duration,
                               format_duration_mins=format_duration_mins,
                               format_booking_location=format_booking_location,
                               format_phone=format_phone_display,
                               today=today,
                               cancellable_ids=cancellable_ids)



    @app.route('/mapp')
    @login_required
    def map_view():
        """Карта пространства с бронированием"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')

            return render_template('mapp.html',
                                   today=today,
                                   is_admin=current_user.is_admin(),
                                   is_manager=current_user.is_manager(),
                                   get_type_name=get_type_name,
                                   get_status_name=get_status_name)
        except Exception as e:
            flash(f'Ошибка при загрузке карты: {user_error_message(e)}', 'error')
            return redirect(url_for('dashboard'))


    # ================== API ДЛЯ КАРТЫ И БРОНИРОВАНИЯ ==================

