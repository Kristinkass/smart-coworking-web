from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    username = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20))
    role = db.Column(db.String(20), default='client')  # 'client', 'admin'
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == 'admin'

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'username': self.username,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<User {self.email}>'

class PlaceType(db.Model):
    __tablename__ = 'place_types'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)   # desk, room, office, openspace
    display_name = db.Column(db.String(80), nullable=False)        # "Рабочий стол", "Переговорная" и т.д.
    default_price = db.Column(db.Float, default=150.0)
    default_capacity = db.Column(db.Integer, default=1)

    def __repr__(self):
        return f'<PlaceType {self.name}>'

class Place(db.Model):
    __tablename__ = 'places'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type_id = db.Column(db.Integer, db.ForeignKey('place_types.id'), nullable=False)
    type = db.relationship('PlaceType', backref='places')

    description = db.Column(db.Text)
    x = db.Column(db.Integer, nullable=False)
    y = db.Column(db.Integer, nullable=False)
    width = db.Column(db.Integer, default=1)
    height = db.Column(db.Integer, default=1)
    status = db.Column(db.String(20), default='free')
    price_per_hour = db.Column(db.Float, default=150.0)
    rating = db.Column(db.Float, default=0.0)
    rating_count = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)
    # Вместимость (для openspace — максимум одновременных бронирований)
    capacity = db.Column(db.Integer, default=1)
    # Флаг обслуживания (выставляется администратором вручную)
    maintenance = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Place {self.name}>'

    def get_current_booking(self):
        now = datetime.now()
        today = now.date()
        current_time = now.time()
        return Booking.query.filter(
            Booking.place_id == self.id,
            Booking.status == 'active',
            Booking.booking_date == today,
            Booking.start_time <= current_time,
            Booking.end_time > current_time
        ).first()

    def get_current_occupancy(self):
        """Количество активных бронирований прямо сейчас (для openspace)"""
        now = datetime.now()
        today = now.date()
        current_time = now.time()
        return Booking.query.filter(
            Booking.place_id == self.id,
            Booking.status == 'active',
            Booking.booking_date == today,
            Booking.start_time <= current_time,
            Booking.end_time > current_time
        ).count()

    def get_occupancy_at(self, booking_date, start_time, end_time):
        """Максимальное количество одновременных бронирований в заданном интервале"""
        return Booking.query.filter(
            Booking.place_id == self.id,
            Booking.booking_date == booking_date,
            Booking.status == 'active',
            Booking.start_time < end_time,
            Booking.end_time > start_time
        ).count()

    def to_dict(self):
        now = datetime.now()
        today = now.date()
        current_time = now.time()

        # Если место на обслуживании — всегда maintenance
        if self.maintenance:
            return {
                'id': self.id,
                'name': self.name,
                'type': self.type.name if self.type else None,
                'x': self.x,
                'y': self.y,
                'width': self.width,
                'height': self.height,
                'status': 'maintenance',
                'price_per_hour': self.price_per_hour,
                'rating': round(self.rating, 1) if self.rating else 0.0,
                'rating_count': self.rating_count,
                'active': self.active,
                'capacity': self.capacity,
                'maintenance': True,
                'current_occupancy': 0,
                'occupied_until': None
            }

        is_openspace = self.type and self.type.name == 'openspace'
        current_occupancy = self.get_current_occupancy()

        if is_openspace:
            is_occupied_now = current_occupancy >= self.capacity
        else:
            current_booking = self.get_current_booking()
            is_occupied_now = current_booking is not None

        new_status = 'occupied' if is_occupied_now else 'free'
        if self.status != new_status:
            self.status = new_status
            try:
                db.session.commit()
            except:
                db.session.rollback()

        occupied_until = None
        if is_occupied_now and not is_openspace:
            current_booking = self.get_current_booking()
            if current_booking:
                occupied_until = current_booking.end_time.strftime('%H:%M')

        return {
            'id': self.id,
            'name': self.name,
            'type': self.type.name if self.type else None,
            'x': self.x,
            'y': self.y,
            'width': self.width,
            'height': self.height,
            'status': self.status,
            'price_per_hour': self.price_per_hour,
            'rating': round(self.rating, 1) if self.rating else 0.0,
            'rating_count': self.rating_count,
            'active': self.active,
            'capacity': self.capacity,
            'maintenance': self.maintenance,
            'current_occupancy': current_occupancy,
            'occupied_until': occupied_until
        }

    def update_rating(self, new_rating):
        try:
            current_total = self.rating * self.rating_count
            self.rating_count += 1
            self.rating = (current_total + new_rating) / self.rating_count
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка обновления рейтинга: {e}")
            return False


class Booking(db.Model):
    __tablename__ = 'bookings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    place_id = db.Column(db.Integer, db.ForeignKey('places.id', ondelete='CASCADE'), nullable=False)
    booking_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    duration_hours = db.Column(db.Float, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='active')
    user_rating = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='bookings', lazy='joined')
    place = db.relationship('Place', backref='bookings', lazy='joined')

    def to_dict(self):
        return {
            'id': self.id,
            'place_id': self.place_id,
            'place_name': self.place.name if self.place else 'Unknown',
            'booking_date': self.booking_date.strftime('%Y-%m-%d') if self.booking_date else None,
            'start_time': self.start_time.strftime('%H:%M') if self.start_time else None,
            'end_time': self.end_time.strftime('%H:%M') if self.end_time else None,
            'duration_hours': self.duration_hours,
            'total_price': self.total_price,
            'status': self.status,
            'user_rating': self.user_rating,
            'created_at': self.created_at.strftime('%d.%m.%Y %H:%M')
        }


class Rating(db.Model):
    __tablename__ = 'ratings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    place_id = db.Column(db.Integer, db.ForeignKey('places.id', ondelete='CASCADE'), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id', ondelete='CASCADE'))
    score = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Rating {self.score} for place {self.place_id}>'


class Tariff(db.Model):
    __tablename__ = 'tariffs'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False)
    duration_hours = db.Column(db.Integer)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)



def create_sample_data():
    """Создание тестовых данных"""
    print("Создание тестовых данных...")
    try:
        # === Создаём типы мест ===
        if PlaceType.query.count() == 0:
            types = [
                {'name': 'desk', 'display_name': 'Рабочий стол', 'default_price': 150, 'default_capacity': 1},
                {'name': 'room', 'display_name': 'Переговорная', 'default_price': 500, 'default_capacity': 6},
                {'name': 'office', 'display_name': 'Приватный офис', 'default_price': 800, 'default_capacity': 8},
                {'name': 'openspace', 'display_name': 'Open Space', 'default_price': 150, 'default_capacity': 10},
            ]
            for t in types:
                place_type = PlaceType(**t)
                db.session.add(place_type)
            db.session.commit()
            print("✓ Типы мест созданы")

        # === Создаём администратора ===
        if User.query.filter_by(role='admin').count() == 0:
            admin = User(
                email='admin@coworking.com',
                username='Администратор',
                phone='+79990001122',
                role='admin',
                active=True
            )
            admin.set_password('123456')
            db.session.add(admin)
            db.session.commit()
            print("✓ Админ создан")

        # === Создаём места (самое важное) ===
        if Place.query.count() == 0:
            desk_type = PlaceType.query.filter_by(name='desk').first()
            room_type = PlaceType.query.filter_by(name='room').first()
            office_type = PlaceType.query.filter_by(name='office').first()
            openspace_type = PlaceType.query.filter_by(name='openspace').first()

            if not all([desk_type, room_type, office_type, openspace_type]):
                print("❌ Не найдены типы мест!")
                return

            places = [
                # Левый верх (офисы и столы)
                Place(name='Офис 1', type_id=office_type.id, x=220, y=5, width=625, height=400, price_per_hour=800),
                Place(name='Стол 1', type_id=desk_type.id, x=20, y=5, width=200, height=310, price_per_hour=250),

                # Верхний ряд переговорок
                Place(name='Стол 2', type_id=desk_type.id, x=845, y=5, width=222, height=240,
                      price_per_hour=250),
                Place(name='Стол 3', type_id=desk_type.id, x=1065, y=5, width=220, height=240,
                      price_per_hour=250),
                Place(name='Стол 4', type_id=desk_type.id, x=1285, y=5, width=220, height=240,
                      price_per_hour=250),
                Place(name='Стол 5', type_id=desk_type.id, x=1505, y=5, width=220, height=240,
                      price_per_hour=250),
                Place(name='Стол 6', type_id=desk_type.id, x=1725, y=5, width=220, height=240,
                      price_per_hour=250),

                # Правый столбец
                Place(name='Стол 7', type_id=room_type.id, x=1945, y=5, width=265, height=345, price_per_hour=250),
                Place(name='Стол 8', type_id=room_type.id, x=1945, y=350, width=265, height=220, price_per_hour=250),
                Place(name='Стол 9', type_id=room_type.id, x=1945, y=570, width=265, height=220, price_per_hour=250),
                Place(name='Стол 10', type_id=room_type.id, x=1945, y=790, width=265, height=150, price_per_hour=250),

                # Нижний ряд
                Place(name='Стол 11', type_id=room_type.id, x=855, y=995, width=223, height=210, price_per_hour=250),
                Place(name='Стол 12', type_id=room_type.id, x=630, y=995, width=225, height=210, price_per_hour=250),

                # Большая переговорная
                Place(name='Переговорная 1', type_id=room_type.id, x=1078, y=945, width=500, height=260,
                      price_per_hour=500),
                Place(name='Переговорная 2', type_id=room_type.id, x=1707, y=945, width=502, height=260,
                      price_per_hour=500),

                # Open Space внизу
                Place(name='Open Space', type_id=openspace_type.id, x=20, y=787, width=610, height=418,
                      price_per_hour=150, capacity=10),
            ]

            for place in places:
                db.session.add(place)

            db.session.commit()
            print(f"✓ Создано {len(places)} мест на карте")

        else:
            print(f"✓ В базе уже {Place.query.count()} мест")

        db.session.commit()
        print("Тестовые данные успешно загружены!")

    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при создании тестовых данных: {e}")
        import traceback
        traceback.print_exc()


def update_booking_statuses():
    """Автоматически обновлять статусы бронирований"""
    try:
        now = datetime.now()
        today = now.date()
        current_time = now.time()

        bookings_to_complete = Booking.query.filter(
            Booking.status == 'active',
            db.or_(
                Booking.booking_date < today,
                db.and_(
                    Booking.booking_date == today,
                    Booking.end_time <= current_time
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
        db.session.rollback()
        print(f"Ошибка обновления статусов: {e}")
    return 0


def init_db(app):
    with app.app_context():
        print("Создание/проверка таблиц базы данных...")
        db.create_all()
        print("Таблицы базы данных готовы")

        # Миграция: обновляем capacity у существующего Open Space если он = 1 (дефолт)
        try:
            openspace_type = PlaceType.query.filter_by(name='openspace').first()
            if openspace_type:
                wrong_capacity = Place.query.filter(
                    Place.type_id == openspace_type.id,
                    Place.capacity == 1
                ).all()
                for p in wrong_capacity:
                    p.capacity = 10
                    print(f"✓ Обновлена вместимость '{p.name}': capacity=10")
                if wrong_capacity:
                    db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка миграции capacity: {e}")

        create_sample_data()
        completed = update_booking_statuses()
        if completed > 0:
            print(f"Автоматически завершено {completed} бронирований")