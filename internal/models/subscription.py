"""Subscriptions."""
from datetime import datetime

from sqlalchemy.orm import synonym

from internal.models.db import db

class Subscription(db.Model):
    __tablename__ = 'subscriptions'
    id_subscription = db.Column(db.Integer, primary_key=True)
    id = synonym('id_subscription')
    user_id = db.Column(db.Integer, db.ForeignKey('users.id_user', ondelete='CASCADE'), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    # Шаблон для самостоятельного оформления (без привязки к пользователю)
    is_template = db.Column(db.Boolean, default=False)
    duration_days = db.Column(db.Integer, nullable=True)
    # Типы мест, на которые действует абонемент (desk, room)
    place_kinds = db.Column(db.String(200))  # JSON массив: ["desk", "room"]
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    # Количество часов/посещений (null = безлимит)
    hours_limit = db.Column(db.Integer, nullable=True)
    hours_used = db.Column(db.Integer, default=0)
    price = db.Column(db.Float, nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='subscriptions')

    @property
    def hours_remaining(self):
        """Оставшиеся часы по абонементу"""
        if self.hours_limit is None:
            return None
        return self.hours_limit - self.hours_used

    @property
    def is_active(self):
        """Активен ли абонемент сейчас"""
        return self.is_valid()

    def _expiry_info(self):
        today = datetime.now().date()
        if not self.end_date:
            return None, '—'
        days = (self.end_date - today).days
        if not self.active:
            label = 'Неактивен'
        elif self.start_date and today < self.start_date:
            label = f'С {self.start_date.strftime("%d.%m.%Y")}'
        elif days < 0:
            label = f'Истёк {abs(days)} дн. назад'
        elif days == 0:
            label = 'Истекает сегодня'
        elif days <= 7:
            label = f'Через {days} дн.'
        else:
            label = f'до {self.end_date.strftime("%d.%m.%Y")}'
        return days, label

    def to_dict(self):
        import json
        days_until_end, expires_label = self._expiry_info()
        data = {
            'id': self.id_subscription,
            'user_id': self.user_id,
            'user_email': self.user.login_label if self.user else None,
            'user_username': self.user.username if self.user else None,
            'name': self.name,
            'is_template': bool(self.is_template),
            'duration_days': self.duration_days,
            'place_kinds': json.loads(self.place_kinds) if self.place_kinds else [],
            'start_date': self.start_date.strftime('%Y-%m-%d') if self.start_date else None,
            'end_date': self.end_date.strftime('%Y-%m-%d') if self.end_date else None,
            'hours_limit': self.hours_limit,
            'hours_used': self.hours_used,
            'hours_remaining': self.hours_limit - self.hours_used if self.hours_limit else None,
            'price': self.price,
            'active': self.active,
            'is_valid': self.is_valid(),
            'days_until_end': days_until_end,
            'expires_label': expires_label,
            'created_at': self.created_at.strftime('%d.%m.%Y %H:%M')
        }
        if self.is_template:
            data['is_archived'] = not self.active
            data['status_label'] = 'Активен' if self.active else 'Архив'
        return data

    def is_valid(self):
        """Проверка, действителен ли абонемент сейчас"""
        if not self.active:
            return False
        now = datetime.now().date()
        if now < self.start_date or now > self.end_date:
            return False
        if self.hours_limit and self.hours_used >= self.hours_limit:
            return False
        return True

    def can_book_place(self, place_kind):
        """Проверка, можно ли забронировать место данного типа по абонементу"""
        if not self.is_valid():
            return False
        import json
        from internal.utils.formatters import normalize_place_kind
        kinds = json.loads(self.place_kinds) if self.place_kinds else []
        nk = normalize_place_kind(place_kind)
        if nk in kinds:
            return True
        # Закрытая зона столов (kind=space) — абонемент на столы
        if nk == 'space' and 'desk' in kinds:
            return True
        return False
