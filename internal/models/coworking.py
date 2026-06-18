"""Coworking, Floor, Location."""
import json
from datetime import datetime

from sqlalchemy.orm import synonym

from internal.models.db import db
from internal.models.layout import load_layout

class Coworking(db.Model):
    __tablename__ = 'coworkings'
    id_coworking = db.Column(db.Integer, primary_key=True)
    id = synonym('id_coworking')
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    floors = db.relationship('Floor', backref='coworking', cascade='all, delete-orphan')

    @staticmethod
    def get_singleton():
        """Единственный экземпляр коворкинга (или None)."""
        return Coworking.query.order_by(Coworking.id_coworking).first()

    @staticmethod
    def ensure_singleton(name=None, address=None):
        """Гарантировать ровно один коворкинг в системе."""
        existing = Coworking.query.order_by(Coworking.id_coworking).all()
        if not existing:
            layout = load_layout()
            cw_data = layout.get('coworking', {})
            cw = Coworking(
                name=name or cw_data.get('name', 'Коворкинг'),
                address=address or cw_data.get('address', ''),
            )
            db.session.add(cw)
            db.session.commit()
            return cw

        primary = existing[0]
        for extra in existing[1:]:
            from internal.models.schedule import CoworkingSchedule
            Floor.query.filter_by(coworking_id=extra.id_coworking).update({'coworking_id': primary.id_coworking})
            CoworkingSchedule.query.filter_by(id_coworking=extra.id_coworking).update({'id_coworking': primary.id_coworking})
            db.session.delete(extra)
        db.session.commit()
        return primary


class Floor(db.Model):
    __tablename__ = 'floors'
    id_floor = db.Column(db.Integer, primary_key=True)
    id = synonym('id_floor')
    coworking_id = db.Column(db.Integer, db.ForeignKey('coworkings.id_coworking', ondelete='CASCADE'), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(80))
    locations = db.relationship('Location', backref='floor', cascade='all, delete-orphan')
    places = db.relationship('Place', backref='floor', lazy=True)


class Location(db.Model):
    __tablename__ = 'locations'
    id_location = db.Column(db.Integer, primary_key=True)
    id = synonym('id_location')
    floor_id = db.Column(db.Integer, db.ForeignKey('floors.id_floor', ondelete='CASCADE'), nullable=False)
    zone_type_id = db.Column(db.Integer, db.ForeignKey('location_zone_types.id_zone_type', ondelete='SET NULL'), nullable=True)
    code = db.Column(db.String(16), unique=True, nullable=False)   # 1A, 1B, 2A …
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(40), nullable=False)                # desk_zone / room_zone
    places = db.relationship('Place', backref='location', cascade='all, delete-orphan')

    def to_dict(self):
        zt = self.zone_type
        return {
            'id': self.id_location,
            'code': self.code,
            'name': self.name,
            'kind': self.kind,
            'floor_id': self.floor_id,
            'floor_number': self.floor.number if self.floor else None,
            'zone_type': zt.to_dict() if zt else None,
        }

    def __repr__(self):
        return f'<Location {self.code} {self.name}>'
