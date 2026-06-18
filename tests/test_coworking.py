"""Tests for Coworking singleton."""
from internal.models import Coworking, CoworkingSchedule, Floor, db


def test_ensure_singleton_creates_one(app):
    with app.app_context():
        assert Coworking.query.count() == 1
        cw = Coworking.ensure_singleton()
        assert Coworking.query.count() == 1
        assert cw.name == 'Тестовый коворкинг'


def test_ensure_singleton_merges_duplicates(app):
    with app.app_context():
        primary = Coworking.get_singleton()
        extra = Coworking(name='Лишний', address='Адрес 2')
        db.session.add(extra)
        db.session.flush()
        fl = Floor(coworking_id=extra.id, number=99, name='99 этаж')
        db.session.add(fl)
        db.session.commit()

        result = Coworking.ensure_singleton()
        assert Coworking.query.count() == 1
        assert result.id == primary.id
        assert Floor.query.filter_by(number=99).first().coworking_id == primary.id
