"""Place model."""
from datetime import datetime

from sqlalchemy.orm import synonym

from internal.models.booking import Booking
from internal.models.db import db
from internal.models.layout import get_layout_place_meta, get_place_geometry

class Place(db.Model):
    __tablename__ = 'places'

    id_place = db.Column(db.Integer, primary_key=True)
    id = synonym('id_place')
    code = db.Column(db.String(32), unique=True, nullable=False)   # 1А-01, OS-01 ...
    name = db.Column(db.String(100), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id_location', ondelete='CASCADE'), nullable=False)
    floor_id = db.Column(db.Integer, db.ForeignKey('floors.id_floor', ondelete='SET NULL'), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('place_categories.id_category', ondelete='SET NULL'), nullable=True)
    # desk | space (space = локация-контейнер по стенам; desk = рабочее место)
    kind = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text)
    # Стол → код локации-контейнера (переговорная / закрытая зона). Не FK: локация ≠ место.
    container_code = db.Column(db.String(32), nullable=True)
    # Закрытое помещение (со стенами) — на карте этажа показывается как контейнер
    enclosed = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='free')
    rating = db.Column(db.Float, default=0.0)
    rating_count = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)
    maintenance = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Геометрия хранится только в layout.json, в БД не дублируется

    # ---- Совместимость со старым кодом ----
    @property
    def type(self):
        """Раньше Place.type было relationship на PlaceType с .name.
        Сейчас kind хранится строкой — отдаём её напрямую."""
        return self.kind

    @property
    def capacity(self):
        """Вместимость берется из категории."""
        if self.category:
            return self.category.capacity
        return 1

    def get_price(self, tariff_type='hourly'):
        """Получить цену для указанного типа тарифа из категории."""
        if self.category:
            return self.category.get_price(tariff_type)
        return None

    def __repr__(self):
        return f'<Place {self.code} {self.name}>'

    # ---- Бронирования ----
    def get_current_booking(self):
        now = datetime.now()
        return Booking.query.filter(
            Booking.place_id == self.id,
            Booking.status == 'active',
            Booking.booking_date == now.date(),
            Booking.start_time <= now.time(),
            Booking.end_time > now.time()
        ).first()

    def get_current_occupancy(self):
        """Возвращает сумму people_count для текущих активных бронирований"""
        now = datetime.now()
        result = db.session.query(db.func.sum(Booking.people_count)).filter(
            Booking.place_id == self.id,
            Booking.status == 'active',
            Booking.booking_date == now.date(),
            Booking.start_time <= now.time(),
            Booking.end_time > now.time()
        ).scalar()
        return result or 0

    def get_occupancy_at(self, booking_date, start_time, end_time):
        """Возвращает сумму people_count для бронирований на указанное время"""
        result = db.session.query(db.func.sum(Booking.people_count)).filter(
            Booking.place_id == self.id,
            Booking.booking_date == booking_date,
            Booking.status == 'active',
            Booking.start_time < end_time,
            Booking.end_time > start_time
        ).scalar()
        return result or 0

    def get_seats_status_at(self, booking_date, start_time, end_time):
        """Какие места заняты на пересекающемся интервале.

        Возвращает: {
          'taken_seats': [int, ...],     # занятые конкретные места (seat_number)
          'whole_table_taken': bool,      # есть ли бронь стола целиком
        }
        """
        overlapping = Booking.query.filter(
            Booking.place_id == self.id,
            Booking.booking_date == booking_date,
            Booking.status == 'active',
            Booking.start_time < end_time,
            Booking.end_time > start_time,
        ).all()
        taken = []
        cap = self.capacity if self.capacity else 1
        whole = any((b.people_count or 0) >= cap for b in overlapping)
        return {'taken_seats': taken, 'whole_table_taken': whole}

    def get_seats_status_now(self):
        """Какие места заняты прямо сейчас."""
        now = datetime.now()
        return self.get_seats_status_at(now.date(), now.time(), now.time())

    def get_child_places(self):
        """Рабочие места (столы) внутри локации-контейнера."""
        if not self.is_container():
            return []
        return Place.query.filter_by(
            container_code=self.code, kind='desk', active=True,
        ).all()

    def is_container(self):
        """Локация-контейнер: комната по стенам, открытая или закрытая зона."""
        return self.kind in ('room', 'space')

    def is_desk(self):
        return self.kind == 'desk'

    def get_container_place(self):
        """Локация, в которой стоит стол."""
        if not self.container_code or not self.is_desk():
            return None
        return Place.query.filter_by(code=self.container_code).first()

    def is_on_maintenance(self):
        """Собственный флаг или обслуживание родительской зоны."""
        if self.maintenance:
            return True
        parent = self.get_container_place()
        return bool(parent and parent.maintenance)

    def apply_maintenance(self, maintenance):
        """Установить обслуживание; для зоны — каскад на все столы внутри."""
        self.maintenance = maintenance
        self.status = 'maintenance' if maintenance else 'free'
        if self.is_container():
            for child in Place.query.filter_by(container_code=self.code, kind='desk').all():
                child.maintenance = maintenance
                child.status = 'maintenance' if maintenance else 'free'

    def location_path(self):
        """Читаемый путь «где находится место»: этаж · зона/помещение · место.

        Пример: «Этаж 1 · Закрытая зона рабочих столов · Стол на 8 мест».
        Считается на лету по этажу и контейнеру, поэтому всегда актуален."""
        parts = []
        floor_num = self.floor.number if self.floor else None
        if floor_num:
            parts.append(f'Этаж {floor_num}')
        container = self.get_container_place()
        if container and container.name:
            parts.append(container.name)
        if self.name:
            parts.append(self.name)
        return ' · '.join(parts)

    def allows_child_desks(self):
        from internal.models.sync import place_allows_child_desks
        return place_allows_child_desks(self)

    def is_meeting_room(self):
        if not self.is_container():
            return False
        from internal.models.location_zone import ROOM_ZONE_KIND, is_amenity_zone_kind
        if self.location and self.location.zone_type:
            if is_amenity_zone_kind(self.location.zone_type.kind):
                return False
            return self.location.zone_type.kind == ROOM_ZONE_KIND
        return bool(self.category and self.category.kind == 'room')

    def compute_container_status(self):
        """Статус закрытого помещения по дочерним столам и целой брони комнаты."""
        if self.is_on_maintenance():
            return self.compute_live_status()

        children = self.get_child_places()
        if not children:
            return self.compute_live_status()

        own = self.compute_live_status()
        if own['current_occupancy'] > 0:
            return own

        total_cap = sum(c.capacity for c in children)
        total_occ = sum(c.get_current_occupancy() for c in children)

        if total_occ == 0:
            status = 'free'
        elif total_cap > 1 and total_occ < total_cap:
            status = 'partial'
        else:
            status = 'occupied'

        partial_occupancy = None
        if total_cap > 1 and 0 < total_occ < total_cap:
            partial_occupancy = {
                'occupied': total_occ,
                'capacity': total_cap,
                'available': total_cap - total_occ,
            }

        return {
            'status': status,
            'current_occupancy': total_occ,
            'occupied_until': own.get('occupied_until'),
            'partial_occupancy': partial_occupancy,
            'taken_seats': [],
            'whole_table_taken': status == 'occupied',
        }

    def get_display_status(self):
        """Статус для отображения на карте (контейнер или обычное место)."""
        if self.is_on_maintenance():
            return self.compute_live_status()
        if self.is_container() and self.get_child_places():
            return self.compute_container_status()
        return self.compute_live_status()

    def compute_live_status(self):
        """Актуальный статус места (free / partial / occupied / maintenance)."""
        effective_capacity = self.capacity if self.capacity else 1

        if self.is_on_maintenance():
            return {
                'status': 'maintenance',
                'current_occupancy': 0,
                'occupied_until': None,
                'partial_occupancy': None,
                'taken_seats': [],
                'whole_table_taken': False,
            }

        current_occupancy = self.get_current_occupancy()
        seats_status = self.get_seats_status_now()

        if current_occupancy == 0:
            status = 'free'
        elif effective_capacity > 1 and current_occupancy < effective_capacity:
            status = 'partial'
        else:
            status = 'occupied'

        occupied_until = None
        if current_occupancy > 0:
            cur = self.get_current_booking()
            if cur:
                occupied_until = cur.end_time.strftime('%H:%M')

        partial_occupancy = None
        if effective_capacity > 1 and 0 < current_occupancy < effective_capacity:
            partial_occupancy = {
                'occupied': current_occupancy,
                'capacity': effective_capacity,
                'available': effective_capacity - current_occupancy,
            }

        return {
            'status': status,
            'current_occupancy': current_occupancy,
            'occupied_until': occupied_until,
            'partial_occupancy': partial_occupancy,
            'taken_seats': seats_status['taken_seats'],
            'whole_table_taken': seats_status['whole_table_taken'],
        }

    def to_dict(self):
        # Геометрия из layout.json
        geometry = get_place_geometry(self.code) or {
            'x': 0, 'y': 0, 'width': 100, 'height': 100, 'rotation': 0, 'floor': 1,
        }

        # Вместимость из категории
        effective_capacity = 1
        category_info = None
        tariffs_info = []
        if self.category:
            effective_capacity = self.category.capacity
            tariffs_info = [t.to_dict() for t in self.category.tariffs] if self.category.tariffs else []
            category_info = {
                'id': self.category.id,
                'name': self.category.name,
                'capacity': self.category.capacity,
                'width_m': self.category.width_m,
                'height_m': self.category.height_m,
                'width_px': self.category.get_width_px(),
                'height_px': self.category.get_height_px(),
                'tariffs': tariffs_info,
            }

        if self.is_on_maintenance():
            return {
                'id': self.id, 'code': self.code, 'name': self.name,
                'type': self.kind, 'kind': self.kind,
                'location_id': self.location_id,
                'location_code': self.location.code if self.location else None,
                'floor_id': self.floor_id,
                'floor': self.floor.number if self.floor else (geometry['floor'] if 'floor' in geometry else 1),
                'category': category_info,
                'x': geometry['x'], 'y': geometry['y'],
                'width': geometry['width'], 'height': geometry['height'],
                'rotation': geometry['rotation'],
                'status': 'maintenance',
                'rating': round(self.rating, 1) if self.rating else 0.0,
                'rating_count': self.rating_count,
                'active': self.active, 'capacity': effective_capacity,
                'maintenance': True,
                'location_path': self.location_path(),
                'current_occupancy': 0, 'occupied_until': None,
                'taken_seats': [], 'whole_table_taken': False,
                'tariffs': tariffs_info,
            }

        live = self.get_display_status()
        new_status = live['status']
        if self.status != new_status:
            self.status = new_status
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        return {
            'id': self.id, 'code': self.code, 'name': self.name,
            'type': self.kind, 'kind': self.kind,
            'location_id': self.location_id,
            'location_code': self.location.code if self.location else None,
            'floor_id': self.floor_id,
            'floor': self.floor.number if self.floor else (geometry['floor'] if 'floor' in geometry else 1),
            'category': category_info,
            'x': geometry['x'], 'y': geometry['y'],
            'width': geometry['width'], 'height': geometry['height'],
            'rotation': geometry['rotation'],
            'status': self.status,
            'rating': round(self.rating, 1) if self.rating else 0.0,
            'rating_count': self.rating_count,
            'active': self.active, 'capacity': effective_capacity,
            'maintenance': self.is_on_maintenance(),
            'container_code': self.container_code or get_layout_place_meta(self.code).get('container_code'),
            'location_path': self.location_path(),
            'enclosed': self.enclosed,
            'is_container': self.is_container(),
            'children_count': len(self.get_child_places()),
            'current_occupancy': live['current_occupancy'],
            'occupied_until': live['occupied_until'],
            'taken_seats': live['taken_seats'],
            'whole_table_taken': live['whole_table_taken'],
            'partial_occupancy': live['partial_occupancy'],
            'tariffs': tariffs_info,
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

