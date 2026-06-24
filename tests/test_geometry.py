"""Тесты геометрии планировки: пересечения, стены, скольжение."""

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    'layout_geometry',
    _ROOT / 'internal' / 'layout' / 'geometry.py',
)
geometry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(geometry)

_room_spec = importlib.util.spec_from_file_location(
    'room_geometry',
    _ROOT / 'internal' / 'utils' / 'room_geometry.py',
)
room_geometry = importlib.util.module_from_spec(_room_spec)
_room_spec.loader.exec_module(room_geometry)

adjust_rect_from_walls = geometry.adjust_rect_from_walls
desks_overlap_each_other = geometry.desks_overlap_each_other
find_place_overlap = geometry.find_place_overlap
rect_overlaps_walls = geometry.rect_overlaps_walls
rects_overlap = geometry.rects_overlap
detect_all_wall_rooms = room_geometry.detect_all_wall_rooms


class TestRectsOverlap:
    def test_flush_touch_not_overlap(self):
        assert not rects_overlap(0, 0, 100, 80, 100, 0, 100, 80, gap=0)

    def test_one_pixel_overlap(self):
        assert rects_overlap(0, 0, 100, 80, 99, 0, 100, 80, gap=0)

    def test_gap_allows_near_touch(self):
        assert not rects_overlap(0, 0, 100, 80, 98, 0, 100, 80, gap=2)
        assert rects_overlap(0, 0, 100, 80, 98, 0, 100, 80, gap=0)

    def test_separated_no_overlap(self):
        assert not rects_overlap(0, 0, 50, 50, 60, 0, 50, 50, gap=0)


class TestDeskOverlap:
    def _desk(self, code, x, y, w=100, h=80):
        return {'code': code, 'kind': 'desk', 'floor': 1, 'x': x, 'y': y, 'width': w, 'height': h}

    def test_find_overlap_detects_penetration(self):
        places = [self._desk('A', 0, 0), self._desk('B', 50, 0)]
        err = find_place_overlap(places, 'A', 0, 0, 100, 80, 1, 'desk')
        assert err is not None
        assert 'B' in err

    def test_find_overlap_allows_flush(self):
        places = [self._desk('A', 0, 0), self._desk('B', 100, 0)]
        err = find_place_overlap(places, 'A', 0, 0, 100, 80, 1, 'desk')
        assert err is None

    def test_desks_overlap_each_other_batch(self):
        desks = [self._desk('A', 0, 0), self._desk('B', 10, 0)]
        assert desks_overlap_each_other(desks, gap=0)
        desks[1]['x'] = 100
        assert not desks_overlap_each_other(desks, gap=0)


class TestWalls:
    def _vwall(self, x, y1, y2):
        return {'id': 1, 'x1': x, 'y1': y1, 'x2': x, 'y2': y2, 'floor': 1}

    def test_rect_on_wall_detected(self):
        walls = [self._vwall(200, 0, 400)]
        assert rect_overlaps_walls(192, 100, 100, 80, walls, 1)

    def test_rect_flush_outside_wall_ok(self):
        walls = [self._vwall(200, 0, 400)]
        assert not rect_overlaps_walls(216, 100, 100, 80, walls, 1)

    def test_adjust_rect_from_walls_snaps_flush(self):
        walls = [self._vwall(200, 0, 400)]
        x, y = adjust_rect_from_walls(190, 100, 100, 80, walls, 1)
        assert x == 208
        assert not rect_overlaps_walls(x, y, 100, 80, walls, 1)

    def test_room_detected_when_wall_is_extended_in_segments(self):
        walls = [
            {'id': 1, 'x1': 0, 'y1': 0, 'x2': 800, 'y2': 0, 'floor': 1},
            {'id': 2, 'x1': 0, 'y1': 500, 'x2': 800, 'y2': 500, 'floor': 1},
            {'id': 3, 'x1': 0, 'y1': 0, 'x2': 0, 'y2': 500, 'floor': 1},
            # Правая стена как на карте: верх уже был границей соседней комнаты,
            # нижнюю часть пользователь дорисовал отдельно.
            {'id': 4, 'x1': 800, 'y1': 0, 'x2': 800, 'y2': 300, 'floor': 1},
            {'id': 5, 'x1': 800, 'y1': 300, 'x2': 800, 'y2': 500, 'floor': 1},
        ]

        rooms = detect_all_wall_rooms(walls, floor=1, apply_ignored=False)

        assert any(
            room['x'] == 0 and room['y'] == 0
            and room['width'] == 800 and room['height'] == 500
            for room in rooms
        )
