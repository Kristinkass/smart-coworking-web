import os
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta, time, date
import json
from functools import wraps
from dotenv import load_dotenv

import models
from models import db, User, Place, Booking, Rating, Tariff, init_db
# Загружаем переменные окружения

# Загружаем переменные окружения
load_dotenv()

app = Flask(__name__)

# Конфигурация
app.config.from_object('config.Config')
# === КОНФИГУРАЦИЯ БД (только MySQL) ===
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'pool_recycle': 3600,
    'pool_pre_ping': True  # важно для MySQL
}
db.init_app(app)

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите для доступа к этой странице'
login_manager.login_message_category = 'warning'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# функции
def get_type_name(type_code):
    """Получить человекочитаемое название типа места"""
    type_names = {
        'desk': 'Рабочий стол',
        'room': 'Переговорная',
        'office': 'Приватный офис'
    }
    return type_names.get(type_code, type_code)


def get_status_name(status_code):
    status_names = {
        'free': 'Свободно',
        'occupied': 'Занято сейчас',
        'reserved': 'Забронировано',
        'maintenance': 'На обслуживании'
    }
    return status_names.get(status_code, status_code)


def render_stars(rating):
    if not rating:
        return '<span style="color: #d1d5db;">☆☆☆☆☆</span>'

    full_stars = int(rating)
    half_star = rating % 1 >= 0.5
    empty_stars = 5 - full_stars - (1 if half_star else 0)

    stars_html = '★' * full_stars
    if half_star:
        stars_html += '½'
    stars_html += '☆' * empty_stars

    return f'<span style="color: #F59E0B;">{stars_html}</span>'

def is_time_slot_available(place_id, booking_date, start_time, end_time, exclude_booking_id=None):
    # Проверка свободен слот для бронирования
    try:
        # Конвертируем строки в объекты
        if isinstance(start_time, str):
            start_time = datetime.strptime(start_time, '%H:%M').time()
        if isinstance(end_time, str):
            end_time = datetime.strptime(end_time, '%H:%M').time()
        if isinstance(booking_date, str):
            booking_date = datetime.strptime(booking_date, '%Y-%m-%d').date()

        place = models.Place.query.get(place_id)
        if not place:
            return False, "Место не найдено"

        # Проверка флага обслуживания
        if place.maintenance:
            return False, "Место находится на обслуживании"

        # Проверка времени пройденного
        now = datetime.now()
        if booking_date < now.date():
            return False, "Нельзя бронировать на прошедшую дату"

        if booking_date == now.date() and start_time < now.time():
            return False, "Нельзя бронировать на прошедшее время"

        # Проверка корректности времени
        if start_time >= end_time:
            return False, "Время окончания должно быть позже времени начала"

        work_start = datetime.strptime('08:00', '%H:%M').time()
        work_end = datetime.strptime('22:00', '%H:%M').time()

        if start_time < work_start or end_time > work_end:
            return False, "Бронирование возможно только с 8:00 до 22:00"

        start_dt = datetime.combine(date.today(), start_time)
        end_dt = datetime.combine(date.today(), end_time)
        duration_hours = (end_dt - start_dt).seconds / 3600

        if duration_hours < 0.5:
            return False, "Минимальная продолжительность бронирования - 30 минут"

        if duration_hours > 8:
            return False, "Максимальная продолжительность бронирования - 8 часов"

        is_openspace = place.type and place.type.name == 'openspace'

        if is_openspace:
            # Для openspace проверяем вместимость: считаем пересекающиеся брони
            query = models.Booking.query.filter(
                models.Booking.place_id == place_id,
                models.Booking.booking_date == booking_date,
                models.Booking.status == 'active',
                models.Booking.start_time < end_time,
                models.Booking.end_time > start_time
            )
            if exclude_booking_id:
                query = query.filter(models.Booking.id != exclude_booking_id)

            concurrent_count = query.count()
            if concurrent_count >= place.capacity:
                return False, f"Open Space заполнен ({concurrent_count}/{place.capacity} мест занято на это время)"

            return True, f"Время доступно ({concurrent_count}/{place.capacity} мест занято)"
        else:
            # Для обычных мест — стандартная проверка пересечений
            query = models.Booking.query.filter(
                models.Booking.place_id == place_id,
                models.Booking.booking_date == booking_date,
                models.Booking.status == 'active',
                db.or_(
                    db.and_(
                        models.Booking.start_time <= start_time,
                        models.Booking.end_time > start_time
                    ),
                    db.and_(
                        models.Booking.start_time < end_time,
                        models.Booking.end_time >= end_time
                    ),
                    db.and_(
                        models.Booking.start_time >= start_time,
                        models.Booking.end_time <= end_time
                    )
                )
            )

            if exclude_booking_id:
                query = query.filter(models.Booking.id != exclude_booking_id)

            conflicting_booking = query.first()
            if conflicting_booking:
                return False, f"Место уже забронировано с {conflicting_booking.start_time.strftime('%H:%M')} до {conflicting_booking.end_time.strftime('%H:%M')}"

            return True, "Время доступно"
    except Exception as e:
        return False, f"Ошибка проверки: {str(e)}"


def add_hours_to_time(time_obj, hours):
    dummy_date = datetime(2000, 1, 1)
    combined = datetime.combine(dummy_date, time_obj)
    new_time = combined + timedelta(hours=hours)
    return new_time.time()


def update_booking_statuses():
    # обновлять статусы бронирований
    try:
        now = datetime.now()
        today = now.date()
        current_time = now.time()

        # активные бронирования которые надо завершить
        bookings_to_complete = models.Booking.query.filter(
            models.Booking.status == 'active',
            db.or_(
                models.Booking.booking_date < today,
                db.and_(
                    models.Booking.booking_date == today,
                    models.Booking.end_time <= current_time
                )
            )
        ).all()

        for booking in bookings_to_complete:
            booking.status = 'completed'

        if bookings_to_complete:
            db.session.commit()
            print(f"Обновлено {len(bookings_to_complete)} бронирований")
            return len(bookings_to_complete)

    except Exception as e:
        print(f"Ошибка обновления статусов: {e}")
        db.session.rollback()

    return 0


def get_time_slots(start_time="08:00", end_time="22:00", interval_minutes=30):
    # временные слоты
    slots = []
    current = datetime.strptime(start_time, "%H:%M")
    end = datetime.strptime(end_time, "%H:%M")

    while current < end:
        next_time = current + timedelta(minutes=interval_minutes)
        if next_time <= end:
            slots.append({
                'start': current.strftime("%H:%M"),
                'end': next_time.strftime("%H:%M"),
                'label': f"{current.strftime('%H:%M')} - {next_time.strftime('%H:%M')}"
            })
        current = next_time

    return slots


def get_occupied_times_for_date(place_id, date_obj):
    # занятые времена места на конкретную дату
    bookings = models.Booking.query.filter(
        models.Booking.place_id == place_id,
        models.Booking.booking_date == date_obj,
        models.Booking.status == 'active'
    ).order_by(models.Booking.start_time).all()

    occupied_times = []
    for booking in bookings:
        occupied_times.append({
            'start': booking.start_time.strftime('%H:%M'),
            'end': booking.end_time.strftime('%H:%M')
        })

    return occupied_times


# Декоратор для проверки прав администратора
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Доступ запрещен. Требуются права администратора.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)

    return decorated_function


# ================== ОСНОВНЫЕ МАРШРУТЫ ==================

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False

        user = models.User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            if not user.active:
                flash('Ваш аккаунт деактивирован. Свяжитесь с администратором.', 'error')
                return redirect(url_for('login'))

            login_user(user, remember=remember)
            user.last_login = datetime.utcnow()
            db.session.commit()

            flash(f'Добро пожаловать, {user.username}!', 'success')

            if user.is_admin():
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Неверный email или пароль. Попробуйте снова.', 'error')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        username = request.form.get('username')
        password = request.form.get('password')
        phone = request.form.get('phone')

        if not email or not username or not password:
            flash('Все обязательные поля должны быть заполнены', 'error')
            return redirect(url_for('register'))

        if models.User.query.filter_by(email=email).first():
            flash('Пользователь с таким email уже существует', 'error')
            return redirect(url_for('register'))

        user = models.User(
            email=email,
            username=username,
            phone=phone,
            active=True
        )
        user.set_password(password)

        try:
            db.session.add(user)
            db.session.commit()

            flash('Регистрация успешна! Теперь вы можете войти.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при регистрации: {str(e)}', 'error')

    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы успешно вышли из системы', 'success')
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    """Личный кабинет с вкладками"""
    # Активные бронирования
    active_bookings = models.Booking.query.filter_by(
        user_id=current_user.id,
        status='active'
    ).order_by(models.Booking.booking_date, models.Booking.start_time).all()

    # История бронирований (последние 20)
    history_bookings = models.Booking.query.filter(
        models.Booking.user_id == current_user.id,
        models.Booking.status.in_(['completed', 'cancelled'])
    ).order_by(models.Booking.created_at.desc()).limit(20).all()

    # Общая статистика пользователя
    total_bookings = models.Booking.query.filter_by(user_id=current_user.id).count()

    # Общий доход (только завершенные бронирования)
    total_spent = db.session.query(db.func.sum(models.Booking.total_price)).filter(
        models.Booking.user_id == current_user.id,
        models.Booking.status == 'completed'
    ).scalar() or 0

    # Доход за сегодня (только завершенные бронирования сегодня)
    today = datetime.now().date()
    today_income = db.session.query(db.func.sum(models.Booking.total_price)).filter(
        models.Booking.user_id == current_user.id,
        models.Booking.status == 'completed',
        models.Booking.booking_date == today
    ).scalar() or 0

    return render_template('dashboard.html',
                           active_bookings=active_bookings,
                           history_bookings=history_bookings,
                           total_bookings=total_bookings,
                           total_spent=total_spent,
                           today_income=today_income,
                           get_type_name=get_type_name,
                           get_status_name=get_status_name,
                           render_stars=render_stars)


@app.route('/mapp')
@login_required
def map_view():
    """Карта пространства с бронированием"""
    try:
        places = models.Place.query.filter_by(active=True).all()
        places_data = [place.to_dict() for place in places]

        # Передаем сегодняшнюю дату для календаря
        today = datetime.now().strftime('%Y-%m-%d')

        # Генерируем временные слоты для выбора времени
        time_slots = get_time_slots()

        return render_template('mapp.html',
                               places=json.dumps(places_data),
                               today=today,
                               time_slots=time_slots,
                               is_admin=current_user.is_admin(),
                               get_type_name=get_type_name,
                               get_status_name=get_status_name)
    except Exception as e:
        flash(f'Ошибка при загрузке карты: {str(e)}', 'error')
        return redirect(url_for('dashboard'))


# ================== API ДЛЯ КАРТЫ И БРОНИРОВАНИЯ ==================

@app.route('/api/places', methods=['GET'])
def get_places():
    try:
        places = models.Place.query.filter_by(active=True).all()
        return jsonify([place.to_dict() for place in places])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/available_times/<int:place_id>', methods=['GET'])
@login_required
def get_available_times(place_id):
    """Получить доступное время для места на выбранную дату"""
    try:
        date_str = request.args.get('date')
        if not date_str:
            return jsonify({'error': 'Дата не указана'}), 400

        booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        place = models.Place.query.get_or_404(place_id)

        # Получаем все бронирования на эту дату
        bookings = models.Booking.query.filter(
            models.Booking.place_id == place_id,
            models.Booking.booking_date == booking_date,
            models.Booking.status == 'active'
        ).order_by(models.Booking.start_time).all()

        # Получаем информацию о текущем бронировании (если есть)
        now = datetime.now()
        today = now.date()
        current_time = now.time()

        current_booking = None
        if booking_date == today:
            current_booking = models.Booking.query.filter(
                models.Booking.place_id == place_id,
                models.Booking.status == 'active',
                models.Booking.booking_date == today,
                models.Booking.start_time <= current_time,
                models.Booking.end_time > current_time
            ).first()

        # Рабочие часы коворкинга (8:00 - 22:00)
        work_start = datetime.strptime('08:00', '%H:%M').time()
        work_end = datetime.strptime('22:00', '%H:%M').time()

        # Генерируем доступные часовые слоты (по 30 минут)
        available_slots = []
        all_slots = []
        current_time_slot = work_start

        # Функция для проверки доступности слота
        def is_slot_available(slot_start, slot_end):
            # Проверяем, не прошло ли уже время (для сегодняшней даты)
            if booking_date == today and slot_start < current_time:
                return False

            is_openspace = place.type and place.type.name == 'openspace'

            if is_openspace:
                # Для openspace считаем количество пересекающихся броней
                count = models.Booking.query.filter(
                    models.Booking.place_id == place_id,
                    models.Booking.booking_date == booking_date,
                    models.Booking.status == 'active',
                    models.Booking.start_time < slot_end,
                    models.Booking.end_time > slot_start
                ).count()
                return count < place.capacity
            else:
                # Проверяем, не пересекается ли слот с существующими бронированиями
                for booking in bookings:
                    booking_start = booking.start_time
                    booking_end = booking.end_time
                    if not (slot_end <= booking_start or slot_start >= booking_end):
                        return False
                return True

        while current_time_slot < work_end:
            slot_end = add_hours_to_time(current_time_slot, 0.5)  # 30 минут

            is_available = is_slot_available(current_time_slot, slot_end)

            all_slots.append({
                'start': current_time_slot.strftime('%H:%M'),
                'end': slot_end.strftime('%H:%M'),
                'available': is_available
            })

            if is_available:
                available_slots.append({
                    'start': current_time_slot.strftime('%H:%M'),
                    'end': slot_end.strftime('%H:%M'),
                    'label': f"{current_time_slot.strftime('%H:%M')} - {slot_end.strftime('%H:%M')}"
                })

            current_time_slot = slot_end

        # Группируем слоты в интервалы для удобства выбора
        grouped_slots = []
        temp_slot = None

        for slot in available_slots:
            if not temp_slot:
                temp_slot = slot.copy()
            elif slot['start'] == temp_slot['end']:
                # Продолжаем интервал
                temp_slot['end'] = slot['end']
                temp_slot['label'] = f"{temp_slot['start']} - {slot['end']}"
            else:
                # Сохраняем текущий интервал и начинаем новый
                grouped_slots.append(temp_slot)
                temp_slot = slot.copy()

        if temp_slot:
            grouped_slots.append(temp_slot)

        # Формируем информацию о текущей занятости
        current_occupation_info = None
        if current_booking:
            current_occupation_info = {
                'start': current_booking.start_time.strftime('%H:%M'),
                'end': current_booking.end_time.strftime('%H:%M'),
                'occupied_until': current_booking.end_time.strftime('%H:%M')
            }

        return jsonify({
            'place': place.to_dict(),
            'date': date_str,
            'available_slots': grouped_slots,
            'all_slots': all_slots,
            'is_openspace': place.type and place.type.name == 'openspace',
            'capacity': place.capacity,
            'bookings': [{
                'start': b.start_time.strftime('%H:%M'),
                'end': b.end_time.strftime('%H:%M')
            } for b in bookings],
            'current_occupation': current_occupation_info
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/check_booking', methods=['POST'])
@login_required
def check_booking():
    """Проверить доступность времени перед созданием бронирования"""
    try:
        data = request.json
        required_fields = ['place_id', 'date', 'start_time', 'end_time']

        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Отсутствует поле: {field}'}), 400

        is_available, message = is_time_slot_available(
            data['place_id'],
            data['date'],
            data['start_time'],
            data['end_time']
        )

        if is_available:
            place = models.Place.query.get(data['place_id'])
            start_dt = datetime.strptime(data['start_time'], '%H:%M')
            end_dt = datetime.strptime(data['end_time'], '%H:%M')
            duration_hours = (end_dt - start_dt).seconds / 3600
            total_price = duration_hours * place.price_per_hour

            return jsonify({
                'success': True,
                'is_available': True,
                'duration_hours': round(duration_hours, 2),
                'total_price': round(total_price, 2),
                'message': message
            })
        else:
            return jsonify({
                'success': True,
                'is_available': False,
                'message': message
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/create_booking', methods=['POST'])
@login_required
def create_booking():
    """Создать одно бронирование"""
    try:
        data = request.json

        required_fields = ['place_id', 'date', 'start_time', 'end_time']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Отсутствует поле: {field}'}), 400

        place = models.Place.query.get(data['place_id'])
        if not place:
            return jsonify({'error': 'Место не найдено'}), 404

        # Проверяем доступность времени (теперь можно бронировать даже занятые места на другое время)
        is_available, message = is_time_slot_available(
            data['place_id'],
            data['date'],
            data['start_time'],
            data['end_time']
        )

        if not is_available:
            return jsonify({'error': message}), 400

        start_dt = datetime.strptime(data['start_time'], '%H:%M')
        end_dt = datetime.strptime(data['end_time'], '%H:%M')
        duration_hours = (end_dt - start_dt).seconds / 3600
        total_price = duration_hours * place.price_per_hour

        booking = models.Booking(
            user_id=current_user.id,
            place_id=data['place_id'],
            booking_date=datetime.strptime(data['date'], '%Y-%m-%d').date(),
            start_time=datetime.strptime(data['start_time'], '%H:%M').time(),
            end_time=datetime.strptime(data['end_time'], '%H:%M').time(),
            duration_hours=duration_hours,
            total_price=total_price,
            status='active'
        )

        db.session.add(booking)
        db.session.commit()

        return jsonify({
            'success': True,
            'booking_id': booking.id,
            'total_price': total_price,
            'message': f'Бронирование успешно создано на {data["date"]} с {data["start_time"]} до {data["end_time"]}'
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/cancel_booking/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    """Отменить бронирование"""
    try:
        booking = models.Booking.query.get_or_404(booking_id)

        # Проверяем права
        if booking.user_id != current_user.id and not current_user.is_admin():
            return jsonify({'error': 'Недостаточно прав'}), 403

        if booking.status != 'active':
            return jsonify({'error': 'Бронирование уже отменено или завершено'}), 400

        # Отменяем бронирование
        booking.status = 'cancelled'
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Бронирование успешно отменено'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ================== НОВЫЕ API ДЛЯ ЛИЧНОГО КАБИНЕТА ==================

@app.route('/api/extend_booking', methods=['POST'])
@login_required
def extend_booking():
    """Продлить бронирование пользователем (на 1 час)"""
    try:
        data = request.json
        booking_id = data.get('booking_id')

        if not booking_id:
            return jsonify({'success': False, 'error': 'ID бронирования не указан'}), 400

        # Находим бронирование
        booking = models.Booking.query.get(booking_id)
        if not booking:
            return jsonify({'success': False, 'error': 'Бронирование не найдено'}), 404

        # Проверяем, что бронирование принадлежит текущему пользователю
        if booking.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Нет доступа к этому бронированию'}), 403

        # Проверяем, что бронирование активно
        if booking.status != 'active':
            return jsonify({'success': False, 'error': 'Можно продлевать только активные бронирования'}), 400

        # Проверяем, что бронирование на сегодня
        today = datetime.now().date()
        if booking.booking_date != today:
            return jsonify({'success': False, 'error': 'Можно продлевать только бронирования на сегодня'}), 400

        # Проверяем, что бронирование еще не закончилось
        now_time = datetime.now().time()
        if booking.end_time < now_time:
            return jsonify({'success': False, 'error': 'Бронирование уже завершено'}), 400

        # Вычисляем новое время окончания (плюс 1 час)
        new_end_time = add_hours_to_time(booking.end_time, 1)

        # Проверяем рабочее время (до 22:00)
        work_end = datetime.strptime('22:00', '%H:%M').time()
        if new_end_time > work_end:
            return jsonify({'success': False, 'error': 'Нельзя продлить после 22:00'}), 400

        # Проверяем, что место свободно на дополнительный час
        conflicts = models.Booking.query.filter(
            models.Booking.place_id == booking.place_id,
            models.Booking.booking_date == today,
            models.Booking.status == 'active',
            models.Booking.id != booking.id,
            db.and_(
                models.Booking.start_time < new_end_time,
                models.Booking.end_time > booking.end_time
            )
        ).first()

        if conflicts:
            return jsonify({
                'success': False,
                'error': 'Место занято на это время. Невозможно продлить'
            }), 400

        # Проверяем максимальную продолжительность (8 часов)
        start_dt = datetime.combine(date.today(), booking.start_time)
        new_end_dt = datetime.combine(date.today(), new_end_time)
        new_duration_hours = (new_end_dt - start_dt).seconds / 3600

        if new_duration_hours > 8:
            return jsonify({'success': False, 'error': 'Максимальная продолжительность бронирования - 8 часов'}), 400

        # Обновляем время окончания, продолжительность и стоимость
        old_end_time = booking.end_time
        booking.end_time = new_end_time
        booking.duration_hours = new_duration_hours

        # Пересчитываем стоимость
        booking.total_price = new_duration_hours * booking.place.price_per_hour

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Бронирование продлено до {new_end_time.strftime("%H:%M")}',
            'new_end_time': booking.end_time.strftime('%H:%M'),
            'new_duration': round(booking.duration_hours, 1),
            'new_total_price': booking.total_price,
            'additional_cost': booking.place.price_per_hour
        })

    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при продлении бронирования: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
        booking = models.Booking.query.get(booking_id)
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
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/update_profile', methods=['POST'])
@login_required
def update_profile():
    """Обновить профиль пользователя"""
    try:
        data = request.json
        username = data.get('username')
        phone = data.get('phone')

        if not username:
            return jsonify({'success': False, 'error': 'Имя пользователя обязательно'}), 400

        # Обновляем данные пользователя
        current_user.username = username
        current_user.phone = phone

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Профиль успешно обновлен'
        })

    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при обновлении профиля: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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

        # Устанавливаем новый пароль
        current_user.set_password(new_password)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Пароль успешно изменен'
        })

    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при смене пароля: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
        return jsonify({'error': str(e)}), 500

# ================== АДМИН ПАНЕЛЬ ==================

@app.route('/admin')
@admin_required
def admin_dashboard():
    """Админ-панель"""
    try:
        # Общая статистика
        total_users = models.User.query.count()
        total_places = models.Place.query.count()
        active_bookings = models.Booking.query.filter_by(status='active').count()

        # Доход за сегодня (ИСПРАВЛЕНО)
        today = datetime.now().date()
        today_revenue_result = db.session.query(db.func.sum(models.Booking.total_price)).filter(
            models.Booking.booking_date == today,
            models.Booking.status == 'active'
        ).first()
        today_revenue = today_revenue_result[0] if today_revenue_result[0] else 0.0

        # Последние бронирования
        recent_bookings = models.Booking.query.order_by(models.Booking.created_at.desc()).limit(10).all()

        return render_template('admin/admin.html',
                               total_users=total_users,
                               total_places=total_places,
                               active_bookings=active_bookings,
                               today_revenue=today_revenue,
                               recent_bookings=recent_bookings)
    except Exception as e:
        flash(f'Ошибка при загрузке панели администратора: {str(e)}', 'error')
        return redirect(url_for('dashboard'))


@app.route('/admin/users')
@admin_required
def admin_users():
    """Управление пользователями"""
    try:
        users = models.User.query.order_by(models.User.created_at.desc()).all()
        return render_template('admin/admin_users.html', users=users)
    except Exception as e:
        flash(f'Ошибка при загрузке пользователей: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))


@app.route('/admin/bookings')
@admin_required
def admin_bookings():
    """Управление бронированиями"""
    try:
        filter_type = request.args.get('filter', 'all')

        # Базовый запрос с оптимизацией
        query = models.Booking.query.options(
            db.joinedload(models.Booking.user),
            db.joinedload(models.Booking.place)
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
        for booking in bookings:
            # Вычисляем прогресс времени для активных бронирований
            if booking.status == 'active':
                now = datetime.now()
                booking_date = booking.booking_date

                # Если бронирование сегодня
                if booking_date == now.date():
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

                # Проверяем, истекает ли скоро (менее часа)
                if booking_date == now.date():
                    end_dt = datetime.combine(booking_date, booking.end_time)
                    time_left = end_dt - datetime.now()
                    booking.is_expiring_soon = time_left.total_seconds() <= 3600  # 1 час
                else:
                    booking.is_expiring_soon = False
            else:
                booking.time_progress = 100 if booking.status == 'completed' else 0
                booking.time_remaining = "Завершено" if booking.status == 'completed' else "Отменено"
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
                               active_bookings_count=active_count)
    except Exception as e:
        flash(f'Ошибка при загрузке бронирований: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))


@app.route('/admin/booking/<int:booking_id>/cancel', methods=['POST'])
@admin_required
def admin_cancel_booking(booking_id):
    """Отменить бронирование (админ)"""
    try:
        booking = models.Booking.query.get_or_404(booking_id)

        if booking.status != 'active':
            flash('Бронирование уже отменено или завершено', 'error')
            return redirect(url_for('admin_bookings'))

        booking.status = 'cancelled'

        db.session.commit()

        flash('Бронирование успешно отменено', 'success')
        return redirect(url_for('admin_bookings'))

    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при отмене бронирования: {str(e)}', 'error')
        return redirect(url_for('admin_bookings'))


@app.route('/admin/booking/<int:booking_id>/complete', methods=['POST'])
@admin_required
def admin_complete_booking(booking_id):
    """Завершить бронирование (админ)"""
    try:
        booking = models.Booking.query.get_or_404(booking_id)

        if booking.status != 'active':
            flash('Бронирование не активно', 'error')
            return redirect(url_for('admin_bookings'))

        booking.status = 'completed'

        db.session.commit()

        flash('Бронирование успешно завершено', 'success')
        return redirect(url_for('admin_bookings'))

    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при завершении бронирования: {str(e)}', 'error')
        return redirect(url_for('admin_bookings'))


@app.route('/admin/user/<int:user_id>/toggle_status', methods=['POST'])
@admin_required
def admin_toggle_user_status(user_id):
    """Активировать/деактивировать пользователя"""
    try:
        user = models.User.query.get_or_404(user_id)
        user.active = not user.active

        db.session.commit()

        status = "активирован" if user.active else "деактивирован"
        flash(f'Пользователь {user.email} {status}', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при изменении статуса: {str(e)}', 'error')

    return redirect(url_for('admin_users'))


@app.route('/admin/user/<int:user_id>/make_admin', methods=['POST'])
@admin_required
def admin_make_admin(user_id):
    """Сделать пользователя администратором"""
    try:
        user = models.User.query.get_or_404(user_id)
        user.role = 'admin' if user.role != 'admin' else 'client'

        db.session.commit()

        role = "администратором" if user.role == 'admin' else "пользователем"
        flash(f'Пользователь {user.email} теперь {role}', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при изменении роли: {str(e)}', 'error')

    return redirect(url_for('admin_users'))


@app.route('/admin/booking/<int:booking_id>/extend', methods=['POST'])
@admin_required
def admin_extend_booking(booking_id):
    """Продлить бронирование"""
    try:
        booking = models.Booking.query.get_or_404(booking_id)

        if booking.status != 'active':
            return jsonify({'success': False, 'error': 'Можно продлевать только активные бронирования'}), 400

        data = request.json
        hours = data.get('hours', 1)

        # Проверяем, что место свободно на дополнительное время
        new_end_time = (datetime.combine(date.today(), booking.end_time) + timedelta(hours=hours)).time()

        conflicts = models.Booking.query.filter(
            models.Booking.place_id == booking.place_id,
            models.Booking.booking_date == booking.booking_date,
            models.Booking.status == 'active',
            models.Booking.id != booking.id,
            db.and_(
                models.Booking.start_time < new_end_time,
                models.Booking.end_time > booking.end_time
            )
        ).first()

        if conflicts:
            return jsonify({
                'success': False,
                'error': 'Нельзя продлить бронирование - время пересекается с другим бронированием'
            }), 400

        # Обновляем время окончания, продолжительность и стоимость
        booking.end_time = new_end_time
        booking.duration_hours += hours
        booking.total_price += hours * booking.place.price_per_hour

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Бронирование успешно продлено',
            'new_end_time': booking.end_time.strftime('%H:%M'),
            'new_total_price': booking.total_price
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/admin/booking/<int:booking_id>/restore', methods=['POST'])
@admin_required
def admin_restore_booking(booking_id):
    """Восстановить отмененное бронирование"""
    try:
        booking = models.Booking.query.get_or_404(booking_id)

        if booking.status != 'cancelled':
            return jsonify({'success': False, 'error': 'Можно восстанавливать только отмененные бронирования'}), 400

        # Проверяем, не прошло ли время бронирования
        now = datetime.now()
        booking_datetime = datetime.combine(booking.booking_date, booking.end_time)

        if booking_datetime < now:
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
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/admin/user/<int:user_id>/notify', methods=['POST'])
@admin_required
def admin_notify_user(user_id):
    """Отправить уведомление пользователю"""
    try:
        user = models.User.query.get_or_404(user_id)
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
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/admin/places')
@admin_required
def admin_places():
    """Управление местами"""
    try:
        places = models.Place.query.order_by(models.Place.created_at.desc()).all()
        return render_template('admin/admin_places.html',
                               places=places,
                               get_type_name=get_type_name,
                               get_status_name=get_status_name)
    except Exception as e:
        flash(f'Ошибка при загрузке мест: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))


@app.route('/api/admin/place/<int:place_id>/toggle_maintenance', methods=['POST'])
@admin_required
def admin_toggle_maintenance(place_id):
    """Переключить флаг обслуживания для места (только для администраторов)"""
    try:
        place = models.Place.query.get_or_404(place_id)
        place.maintenance = not place.maintenance

        # Если ставим на обслуживание — принудительно обновляем статус
        if place.maintenance:
            place.status = 'maintenance'
        else:
            place.status = 'free'

        db.session.commit()

        return jsonify({
            'success': True,
            'maintenance': place.maintenance,
            'status': place.status,
            'message': f'Место "{place.name}" {"переведено на обслуживание" if place.maintenance else "снято с обслуживания"}'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/admin/place/<int:place_id>/toggle_status', methods=['POST'])
@admin_required
def admin_toggle_place_status(place_id):
    """Активировать/деактивировать место"""
    try:
        place = models.Place.query.get_or_404(place_id)
        place.active = not place.active

        db.session.commit()

        status = "активировано" if place.active else "деактивировано"
        flash(f'Место {place.name} {status}', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при изменении статуса места: {str(e)}', 'error')

    return redirect(url_for('admin_places'))

# ================== ЗАПУСК ПРИЛОЖЕНИЯ ==================
if __name__ == '__main__':
    init_db(app)
    print("СИСТЕМА БРОНИРОВАНИЯ КОВОРКИНГА")
    print("=" * 60)
    print("Сервер запущен: http://0.0.0.0:5000")
    print("С телефона: http://ТВОЙ_IP:5000")
    print("Админ: admin@coworking.com / 123456")

    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)