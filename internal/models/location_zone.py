"""Категории зон локаций (А — столы, Б — переговорные и т.д.)."""
from sqlalchemy.orm import synonym

from internal.models.db import db

DESK_ZONE_KIND = 'desk_zone'
ROOM_ZONE_KIND = 'room_zone'
AMENITY_ZONE_KINDS = frozenset({
    'amenity_zone',
    'lounge_zone',
    'kitchen_zone',
    'wc_zone',
})
ZONE_KIND_LABELS = {
    DESK_ZONE_KIND: 'Рабочие столы',
    ROOM_ZONE_KIND: 'Переговорные / помещения',
    'amenity_zone': 'Служебная зона',
    'lounge_zone': 'Зона отдыха',
    'kitchen_zone': 'Кухня',
    'wc_zone': 'Санузел',
}


DEFAULT_ZONE_TYPE_LETTERS = frozenset({'A', 'B', 'R', 'K', 'W'})

DEFAULT_ZONE_TYPES = (
    {'letter': 'A', 'name': 'Зона рабочих столов', 'kind': DESK_ZONE_KIND},
    {'letter': 'B', 'name': 'Зона переговорных', 'kind': ROOM_ZONE_KIND},
    {'letter': 'R', 'name': 'Зона отдыха', 'kind': 'lounge_zone'},
    {'letter': 'K', 'name': 'Кухня', 'kind': 'kitchen_zone'},
    {'letter': 'W', 'name': 'Санузлы', 'kind': 'wc_zone'},
)


def is_amenity_zone_kind(kind):
    return kind in AMENITY_ZONE_KINDS


def place_is_amenity(place):
    """Служебная зона — хранится в locations, не в places."""
    if not place or place.kind == 'desk':
        return False
    if place.location and place.location.zone_type:
        return is_amenity_zone_kind(place.location.zone_type.kind)
    return False


def layout_place_belongs_in_db(lp, location=None, zone_type=None):
    """Нужна ли запись в таблице places для объекта из layout.json."""
    kind = lp.get('kind', 'desk')
    if kind == 'desk':
        return True
    if kind not in ('space', 'room'):
        return False

    zt = zone_type
    if not zt and lp.get('zone_type_id'):
        zt = LocationZoneType.query.get(int(lp['zone_type_id']))
    if not zt and lp.get('location'):
        from internal.models.coworking import Location
        loc = location or Location.query.filter_by(code=lp['location']).first()
        if loc and loc.zone_type:
            zt = loc.zone_type
    if zt and is_amenity_zone_kind(zt.kind):
        return False
    if lp.get('bookable') is False and not lp.get('category_id'):
        return False
    return True


def zone_kind_allows_desks(kind):
    return kind == DESK_ZONE_KIND


def zone_kind_is_meeting(kind):
    return kind == ROOM_ZONE_KIND


class LocationZoneType(db.Model):
    """Тип зоны: буква + название. Код места: {этаж}{буква}-{номер}, напр. 1A-1."""

    __tablename__ = 'location_zone_types'

    id_zone_type = db.Column(db.Integer, primary_key=True)
    id = synonym('id_zone_type')
    letter = db.Column(db.String(4), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(40), nullable=False, default='desk_zone')
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)

    locations = db.relationship('Location', backref='zone_type', lazy=True)

    def to_dict(self):
        return {
            'id': self.id_zone_type,
            'letter': self.letter,
            'name': self.name,
            'kind': self.kind,
            'description': self.description,
            'active': self.active,
            'archived': not self.active,
            'code_example': f'1{self.letter}-1',
        }

    def __repr__(self):
        return f'<LocationZoneType {self.letter} {self.name}>'


def build_location_prefix(floor_num, zone_letter):
    """Префикс локации: 1 + A → 1A."""
    return f'{int(floor_num)}{str(zone_letter).strip()}'


def parse_location_prefix(code):
    """Из кода места 1A-4 или локации 1A извлечь (этаж, буква зоны)."""
    if not code:
        return 1, 'A'
    base = str(code).split('-')[0]
    floor = int(base[0]) if base and base[0].isdigit() else 1
    letter = base[1:] if len(base) > 1 else 'A'
    return floor, letter


def ensure_default_zone_types():
    """Создать стандартные типы зон (A/B/R/K/W); лишние — в архив."""
    changed = False
    for item in DEFAULT_ZONE_TYPES:
        existing = LocationZoneType.query.filter_by(letter=item['letter']).first()
        if existing:
            for key in ('name', 'kind'):
                if getattr(existing, key) != item[key]:
                    setattr(existing, key, item[key])
                    changed = True
            if not existing.active:
                existing.active = True
                changed = True
            continue
        db.session.add(LocationZoneType(**item, active=True))
        changed = True

    deprecated_c = LocationZoneType.query.filter_by(letter='C').first()
    if deprecated_c:
        from internal.models.coworking import Location
        for location in list(deprecated_c.locations):
            if not location.places:
                db.session.delete(location)
                changed = True
        db.session.flush()
        linked_locations = Location.query.filter_by(zone_type_id=deprecated_c.id_zone_type).count()
        if linked_locations == 0:
            db.session.delete(deprecated_c)
            changed = True
        elif deprecated_c.active:
            deprecated_c.active = False
            changed = True

    for extra in LocationZoneType.query.filter(
        ~LocationZoneType.letter.in_(DEFAULT_ZONE_TYPE_LETTERS)
    ).all():
        if extra.active:
            extra.active = False
            changed = True

    if changed:
        db.session.commit()
    return changed


def ensure_location_for_zone(floor_num, zone_type_id):
    """Найти или создать Location для этажа и типа зоны (код 1A, 2B …)."""
    from internal.models.coworking import Floor, Location

    zone = LocationZoneType.query.get(zone_type_id)
    if not zone:
        return None

    floor = Floor.query.filter_by(number=int(floor_num)).first()
    if not floor:
        return None

    loc_code = build_location_prefix(floor_num, zone.letter)
    location = Location.query.filter_by(code=loc_code).first()
    if location:
        if location.zone_type_id != zone.id_zone_type:
            location.zone_type_id = zone.id_zone_type
            location.name = zone.name
            location.kind = zone.kind
            db.session.commit()
        return location

    location = Location(
        floor_id=floor.id_floor,
        code=loc_code,
        name=zone.name,
        kind=zone.kind,
        zone_type_id=zone.id_zone_type,
    )
    db.session.add(location)
    db.session.commit()
    return location
