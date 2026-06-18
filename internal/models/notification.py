"""Notifications."""
import re
from datetime import datetime

from sqlalchemy.orm import synonym

from internal.models.db import db
from internal.utils.formatters import format_local_datetime

_LEGACY_BOOKING_PREFIX = re.compile(
    r'^Бронирование №(\d+): (.+?), (\d{2}\.\d{2}\.\d{4}) (\d{2}:\d{2})–(\d{2}:\d{2})\n\n',
    re.DOTALL,
)


def _split_legacy_feedback_message(message):
    match = _LEGACY_BOOKING_PREFIX.match(message or '')
    if not match:
        return None, message
    booking_id, place_name, date, start, end = match.groups()
    return {
        'id': int(booking_id),
        'place_name': place_name,
        'date': date,
        'time': f'{start}–{end}',
        'label': f'№{booking_id}: {place_name}, {date} {start}–{end}',
    }, message[match.end():]


class Notification(db.Model):
    __tablename__ = 'notifications'
    id_notification = db.Column(db.Integer, primary_key=True)
    id = synonym('id_notification')
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    target_audience = db.Column(db.String(20), default='all')
    user_id = db.Column(db.Integer, db.ForeignKey('users.id_user', ondelete='CASCADE'), nullable=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id_booking', ondelete='SET NULL'), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id_user', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship(
        'User',
        foreign_keys='Notification.user_id',
        backref='notifications',
        lazy='select',
    )
    sender = db.relationship(
        'User',
        foreign_keys='Notification.sender_id',
        lazy='select',
    )
    booking = db.relationship('Booking', foreign_keys=[booking_id], lazy='select')

    def is_feedback(self):
        return (
            self.sender_id is not None
            and self.sender is not None
            and self.sender.role == 'client'
            and self.target_audience in ('managers', 'admins')
        )

    def _booking_payload(self):
        if self.booking_id and self.booking:
            place = self.booking.place
            loc = place.location if place else None
            zt = loc.zone_type if loc else None
            container = place.get_container_place() if place else None
            date_str = self.booking.booking_date.strftime('%d.%m.%Y')
            start = self.booking.start_time.strftime('%H:%M')
            end = self.booking.end_time.strftime('%H:%M')
            place_name = place.name if place else 'Место'

            location = {
                'floor': place.floor.number if place and place.floor else None,
                'floor_name': place.floor.name if place and place.floor else None,
                'location_code': loc.code if loc else None,
                'location_name': loc.name if loc else None,
                'zone_letter': zt.letter if zt else None,
                'zone_type_name': zt.name if zt else None,
                'place_code': place.code if place else None,
                'place_name': place_name,
                'container_code': (
                    (container.code if container else place.container_code) if place else None
                ),
                'container_name': container.name if container else None,
                'path': place.location_path() if place else None,
            }

            detail_lines = []
            if location['floor'] is not None:
                floor_line = f"Этаж {location['floor']}"
                if location['floor_name']:
                    floor_line += f" · {location['floor_name']}"
                detail_lines.append(floor_line)
            if location['zone_letter'] or location['location_code']:
                zone_title = location['zone_type_name'] or location['location_name'] or 'Зона'
                zone_code = location['zone_letter'] or location['location_code'] or '–'
                detail_lines.append(f"Зона: {zone_title} · код {zone_code}")
            elif location['location_name']:
                detail_lines.append(
                    f"Локация: {location['location_name']} ({location['location_code'] or '–'})"
                )
            if location['container_name']:
                detail_lines.append(
                    f"Помещение: {location['container_name']} ({location['container_code'] or '–'})"
                )
            if location['place_name']:
                detail_lines.append(
                    f"Место: {location['place_name']} · код {location['place_code'] or '–'}"
                )
            detail_lines.append(f"Бронь №{self.booking_id}: {date_str} {start}–{end}")

            return {
                'id': self.booking_id,
                'place_name': place_name,
                'date': date_str,
                'time': f'{start}–{end}',
                'label': f'№{self.booking_id}: {place_name}, {date_str} {start}–{end}',
                'location': location,
                'detail_lines': detail_lines,
            }
        legacy_booking, _ = _split_legacy_feedback_message(self.message)
        if legacy_booking:
            legacy_booking.setdefault(
                'detail_lines',
                [legacy_booking.get('label', 'Привязанное бронирование')],
            )
        return legacy_booking

    def feedback_message(self):
        if self.booking_id:
            return self.message
        _, body = _split_legacy_feedback_message(self.message)
        return body

    def to_dict(self):
        message = self.feedback_message() if self.is_feedback() else self.message
        data = {
            'id': self.id_notification,
            'title': self.title,
            'message': message,
            'target_audience': self.target_audience,
            'user_id': self.user_id,
            'booking_id': self.booking_id,
            'is_read': self.is_read,
            'sender_id': self.sender_id,
            'sender_name': self.sender.username if self.sender else None,
            'kind': 'feedback' if self.is_feedback() else 'system',
            'created_at': format_local_datetime(self.created_at),
        }
        if self.is_feedback():
            data['booking'] = self._booking_payload()
            data['recipient_label'] = (
                'Менеджеру' if self.target_audience == 'managers' else 'Администратору'
            )
        return data

    def __repr__(self):
        return f'<Notification {self.title} ({self.target_audience})>'
