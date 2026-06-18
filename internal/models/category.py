"""Place categories and tariffs."""
from datetime import datetime

from sqlalchemy.orm import synonym

from internal.models.db import db

class PlaceCategory(db.Model):
    __tablename__ = 'place_categories'

    id_category = db.Column(db.Integer, primary_key=True)
    id = synonym('id_category')
    name = db.Column(db.String(100), nullable=False)  # "Стол складной", "Стол на 4", "Переговорная №1"
    kind = db.Column(db.String(20), nullable=False)   # desk | room
    capacity = db.Column(db.Integer, default=1)        # вместимость (1, 4, 6, 8, 10)
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Размеры в метрах (для шаблонов редактора)
    width_m = db.Column(db.Float, nullable=False, default=1.0)
    height_m = db.Column(db.Float, nullable=False, default=0.75)

    # Связь с местами
    places = db.relationship('Place', backref='category', lazy=True)

    # Связь с тарифами
    tariffs = db.relationship('CategoryTariff', backref='category', cascade='all, delete-orphan', lazy=True)

    # Коэффициент масштаба: 1 метр = 100 пикселей на карте
    SCALE_FACTOR = 100

    def to_dict(self):
        return {
            'id': self.id_category,
            'name': self.name,
            'kind': self.kind,
            'capacity': self.capacity,
            'description': self.description,
            'active': self.active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'width_m': self.width_m,
            'height_m': self.height_m,
            'width_px': self.get_width_px(),
            'height_px': self.get_height_px(),
            'tariffs': [t.to_dict() for t in self.tariffs] if self.tariffs else [],
        }

    def get_width_px(self):
        return int(self.width_m * self.SCALE_FACTOR)

    def get_height_px(self):
        return int(self.height_m * self.SCALE_FACTOR)

    def get_tariff(self, tariff_type='hourly'):
        """Получить тариф указанного типа для этой категории"""
        for tariff in self.tariffs:
            if tariff.tariff_type == tariff_type and tariff.active:
                return tariff
        return None

    def get_price(self, tariff_type='hourly'):
        """Получить цену для указанного типа тарифа"""
        tariff = self.get_tariff(tariff_type)
        return tariff.price if tariff else None

    def __repr__(self):
        return f'<PlaceCategory {self.name} ({self.capacity} мест)>'


def is_auto_zone_category(cat) -> bool:
    """Автосгенерированные категории закрытых зон — не шаблоны столов."""
    if isinstance(cat, dict):
        name = (cat.get('name') or '').strip()
        desc = (cat.get('description') or '').strip()
        w_m = float(cat.get('width_m') or 0)
        h_m = float(cat.get('height_m') or 0)
    else:
        name = (cat.name or '').strip()
        desc = (cat.description or '').strip()
        w_m = float(cat.width_m or 0)
        h_m = float(cat.height_m or 0)
    if name.startswith('Закрытая зона '):
        return True
    if desc.startswith('Зона на ') and 'рабочих мест' in desc:
        return True
    if w_m >= 3.5 and h_m >= 2.5:
        return True
    return False


def is_desk_template_category(cat) -> bool:
    """Категория подходит как шаблон отдельного стола в вариантах размещения."""
    kind = cat.get('kind') if isinstance(cat, dict) else cat.kind
    if kind != 'desk':
        return False
    return not is_auto_zone_category(cat)


class CategoryTariff(db.Model):
    __tablename__ = 'category_tariffs'

    id_tariff = db.Column(db.Integer, primary_key=True)
    id = synonym('id_tariff')
    category_id = db.Column(db.Integer, db.ForeignKey('place_categories.id_category', ondelete='CASCADE'), nullable=False)
    tariff_type = db.Column(db.String(20), nullable=False)  # hourly | weekly | monthly
    price = db.Column(db.Float, nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id_tariff,
            'category_id': self.category_id,
            'tariff_type': self.tariff_type,
            'tariff_type_label': self.tariff_type_label,
            'price': self.price,
            'active': self.active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @property
    def tariff_type_label(self):
        labels = {
            'hourly': 'Часовой',
            'weekly': 'Недельный',
            'monthly': 'Месячный'
        }
        return labels.get(self.tariff_type, self.tariff_type)

    def __repr__(self):
        return f'<CategoryTariff {self.category.name} - {self.tariff_type_label}: {self.price}>'
