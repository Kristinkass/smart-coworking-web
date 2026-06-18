"""Place data access."""
from internal import models
from internal.models import Place, db


class PlaceRepository:
    @staticmethod
    def get_by_id(place_id):
        return Place.query.get(place_id)

    @staticmethod
    def get_or_404(place_id):
        return Place.query.get_or_404(place_id)

    @staticmethod
    def get_by_code(code):
        return Place.query.filter_by(code=code).first()

    @staticmethod
    def get_by_codes(codes):
        from sqlalchemy.orm import joinedload
        from internal.models.category import PlaceCategory
        from internal.models.coworking import Location

        unique = [c for c in dict.fromkeys(codes) if c]
        if not unique:
            return {}
        rows = (
            Place.query.options(
                joinedload(Place.category).joinedload(PlaceCategory.tariffs),
                joinedload(Place.location).joinedload(Location.zone_type),
                joinedload(Place.floor),
            )
            .filter(Place.code.in_(unique))
            .all()
        )
        return {p.code: p for p in rows}

    @staticmethod
    def get_active():
        return Place.query.filter_by(active=True).all()

    @staticmethod
    def sync_by_code(code):
        return models.sync_place_by_code(code)

    @staticmethod
    def resolve_id(value):
        return models.resolve_place_id(value)

    @staticmethod
    def generate_code(kind, location_code):
        return models.generate_place_code(kind, location_code)

    @staticmethod
    def save(place):
        db.session.add(place)
        db.session.commit()
        return place

    @staticmethod
    def deactivate_from_map(place):
        """Снять место с карты: active=False, убрать из layout.json. Запись в БД сохраняется для истории броней."""
        code = place.code
        place.active = False
        db.session.add(place)
        db.session.flush()
        try:
            from internal.layout.repository import LayoutRepository
            LayoutRepository.remove_place(code)
        except Exception:
            pass
        db.session.commit()
        return place

    @staticmethod
    def delete(place):
        """Устаревший hard-delete — используйте deactivate_from_map."""
        db.session.delete(place)
        db.session.commit()
