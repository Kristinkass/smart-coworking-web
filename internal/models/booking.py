"""Booking and ratings."""
from datetime import datetime, timedelta

from sqlalchemy.orm import synonym

from internal.models.db import db

class Booking(db.Model):
    __tablename__ = 'bookings'

    id_booking = db.Column(db.Integer, primary_key=True)
    id = synonym('id_booking')
    user_id = db.Column(db.Integer, db.ForeignKey('users.id_user', ondelete='RESTRICT'), nullable=False)
    place_id = db.Column(db.Integer, db.ForeignKey('places.id_place', ondelete='RESTRICT'), nullable=False)
    category_tariff_id = db.Column(db.Integer, db.ForeignKey('category_tariffs.id_tariff', ondelete='SET NULL'), nullable=True)

    # Количество человек для многоместных столов (по умолчанию 1)
    people_count = db.Column(db.Integer, default=1)

    # Тип тарифа: hourly | weekly | monthly
    tariff_type = db.Column(db.String(20), default='hourly')

    booking_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    duration_hours = db.Column(db.Float, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='active')
    user_rating = db.Column(db.Float)
    subscription_id = db.Column(
        db.Integer,
        db.ForeignKey('subscriptions.id_subscription', ondelete='SET NULL'),
        nullable=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='bookings', lazy='joined')
    place = db.relationship('Place', backref='bookings', lazy='joined')
    category_tariff = db.relationship('CategoryTariff', backref='bookings', lazy='joined')
    subscription = db.relationship('Subscription', backref='bookings', lazy='select', foreign_keys=[subscription_id])

    @property
    def display_place_label(self):
        from internal.utils.formatters import format_place_code
        if self.place:
            code = format_place_code(self.place)
            return f'{self.place.name} ({code})'
        return 'Место удалено'

    @property
    def period_end_date(self):
        if self.tariff_type == 'weekly':
            return self.booking_date + timedelta(days=6)
        if self.tariff_type == 'monthly':
            return self.booking_date + timedelta(days=29)
        return self.booking_date

    def effective_end_datetime(self):
        return datetime.combine(self.period_end_date, self.end_time)

    @property
    def can_restore(self):
        """Восстановление только для отменённых броней, срок которых ещё не истёк."""
        if self.status != 'cancelled':
            return False
        return self.effective_end_datetime() >= datetime.now()

    def to_dict(self):
        return {
            'id': self.id_booking,
            'place_id': self.place_id,
            'place_name': self.place.name if self.place else None,
            'place_code': self.place.code if self.place else None,
            'place_label': self.display_place_label,
            'place_location_path': self.place.location_path() if self.place else None,
            'people_count': self.people_count,
            'tariff_type': self.tariff_type,
            'category_tariff': self.category_tariff.to_dict() if self.category_tariff else None,
            'booking_date': self.booking_date.strftime('%Y-%m-%d') if self.booking_date else None,
            'start_time': self.start_time.strftime('%H:%M') if self.start_time else None,
            'end_time': self.end_time.strftime('%H:%M') if self.end_time else None,
            'duration_hours': self.duration_hours,
            'total_price': self.total_price,
            'status': self.status,
            'user_rating': self.user_rating,
            'created_at': self.created_at.strftime('%d.%m.%Y %H:%M'),
        }


class Rating(db.Model):
    __tablename__ = 'ratings'
    id_rating = db.Column(db.Integer, primary_key=True)
    id = synonym('id_rating')
    user_id = db.Column(db.Integer, db.ForeignKey('users.id_user', ondelete='RESTRICT'), nullable=False)
    place_id = db.Column(db.Integer, db.ForeignKey('places.id_place', ondelete='RESTRICT'), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id_booking', ondelete='CASCADE'))
    score = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
