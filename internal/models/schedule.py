"""Coworking schedule."""
from datetime import datetime, time

from sqlalchemy.orm import synonym

from internal.models.db import db


def time_to_minutes(t: time) -> int:
    """Минуты от полуночи."""
    return t.hour * 60 + t.minute


def minutes_to_time(total_minutes: int) -> time:
    """time из минут (0..1439)."""
    total_minutes %= 24 * 60
    return time(total_minutes // 60, total_minutes % 60)


def effective_close_minutes(open_time: time, close_time: time) -> int:
    """Минуты закрытия; 00:00 при open > 00:00 означает 24:00 (конец дня)."""
    open_m = time_to_minutes(open_time)
    close_m = time_to_minutes(close_time)
    if close_m == 0 and open_m > 0:
        return 24 * 60
    if close_m <= open_m and close_m != 0:
        return close_m + 24 * 60
    return close_m


def format_close_time(open_time: time, close_time: time) -> str:
    """Отображение времени закрытия: 00:00 → 24:00."""
    if close_time and open_time and time_to_minutes(close_time) == 0 and time_to_minutes(open_time) > 0:
        return '24:00'
    return close_time.strftime('%H:%M') if close_time else None


def parse_schedule_time(value: str, *, as_close=False, open_time: time = None) -> time:
    """Разбор HH:MM; для закрытия 24:00 сохраняется как 00:00."""
    raw = str(value or '').strip()
    if as_close and raw in ('24:00', '24:00:00'):
        return time(0, 0)
    return datetime.strptime(raw, '%H:%M').time()


class CoworkingSchedule(db.Model):
    __tablename__ = 'coworking_schedules'

    id_schedule = db.Column(db.Integer, primary_key=True)
    id = synonym('id_schedule')
    # Связь с коворкингом (каскадное обновление)
    id_coworking = db.Column(db.Integer, db.ForeignKey('coworkings.id_coworking', onupdate='CASCADE'), nullable=False, default=1)
    coworking = db.relationship('Coworking', backref=db.backref('schedules', lazy=True))
    # День недели: 0=понедельник, 6=воскресенье
    day_of_week = db.Column(db.Integer, nullable=False)
    # Время открытия и закрытия
    open_time = db.Column(db.Time, nullable=False, default='08:00')
    close_time = db.Column(db.Time, nullable=False, default='22:00')
    # Активен ли этот день (или выходной)
    is_active = db.Column(db.Boolean, default=True)
    # Можно ли бронировать в этот день
    is_bookable = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id_schedule,
            'id_coworking': self.id_coworking,
            'coworking_name': self.coworking.name if self.coworking else None,
            'day_of_week': self.day_of_week,
            'day_name': self.get_day_name(),
            'open_time': self.open_time.strftime('%H:%M') if self.open_time else None,
            'close_time': format_close_time(self.open_time, self.close_time),
            'close_time_raw': self.close_time.strftime('%H:%M') if self.close_time else None,
            'is_active': self.is_active,
            'is_bookable': self.is_bookable
        }

    def get_day_name(self):
        days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
        return days[self.day_of_week] if 0 <= self.day_of_week <= 6 else 'Unknown'

    @staticmethod
    def init_default_schedule(coworking_id=1):
        """Создать расписание по умолчанию для коворкинга: Пн-Пт 8:00-22:00, Сб-Вс 10:00-18:00"""
        default_hours = [
            (0, '08:00', '22:00', True, True),   # Пн
            (1, '08:00', '22:00', True, True),   # Вт
            (2, '08:00', '22:00', True, True),   # Ср
            (3, '08:00', '22:00', True, True),   # Чт
            (4, '08:00', '22:00', True, True),   # Пт
            (5, '10:00', '18:00', True, True),   # Сб
            (6, '10:00', '18:00', True, True),   # Вс
        ]
        for day, open_t, close_t, active, bookable in default_hours:
            from datetime import datetime
            open_time = datetime.strptime(open_t, '%H:%M').time()
            close_time = datetime.strptime(close_t, '%H:%M').time()
            # Проверяем существование расписания для этого коворкинга и дня
            existing = CoworkingSchedule.query.filter_by(
                id_coworking=coworking_id, 
                day_of_week=day
            ).first()
            if not existing:
                db.session.add(CoworkingSchedule(
                    id_coworking=coworking_id,
                    day_of_week=day,
                    open_time=open_time,
                    close_time=close_time,
                    is_active=active,
                    is_bookable=bookable
                ))
        db.session.commit()

    def __repr__(self):
        return f'<CoworkingSchedule {self.get_day_name()} {self.open_time}-{self.close_time}>'
