"""Tests for Location ↔ Floor binding."""
from internal.models import Floor, Location, infer_floor_from_location_code


def test_infer_floor_from_code():
    assert infer_floor_from_location_code('1Б') == 1
    assert infer_floor_from_location_code('2А') == 2
    assert infer_floor_from_location_code('3В') == 3
    assert infer_floor_from_location_code('1A-1') == 1
    assert infer_floor_from_location_code('2A-4') == 2


def test_locations_on_correct_floors(app):
    with app.app_context():
        loc1 = Location.query.filter_by(code='1Б').first()
        loc2 = Location.query.filter_by(code='2А').first()
        assert loc1.floor.number == 1
        assert loc2.floor.number == 2


def test_place_floor_matches_layout_floor(app):
    with app.app_context():
        from internal.models import Place
        place = Place.query.filter_by(code='1Б-T01').first()
        assert place.floor.number == 1
