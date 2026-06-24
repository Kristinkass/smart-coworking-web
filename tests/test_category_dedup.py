"""Tests for category deduplication."""
from types import SimpleNamespace

from internal.utils.category_dedup import (
    category_dedup_key,
    dedupe_category_dicts,
    dedupe_category_orm_list,
)


def _cat(kind='room', capacity=10, name='Переговорная 10 мест', active=True, cat_id=1, places=None, tariffs=None):
    return SimpleNamespace(
        kind=kind,
        capacity=capacity,
        name=name,
        active=active,
        id_category=cat_id,
        width_m=3.5,
        height_m=2.0,
        description='',
        places=places or [],
        tariffs=tariffs or [],
    )


def test_room_categories_dedupe_by_capacity():
    a = _cat(capacity=20, name='Переговорная 20 мест', cat_id=1)
    b = _cat(capacity=20, name='Переговорная 20 мест', cat_id=2)
    result = dedupe_category_orm_list([a, b])
    assert len(result) == 1
    assert result[0].id_category == 1


def test_room_dict_dedupe_keeps_category_with_places():
    cats = [
        {'id': 1, 'kind': 'room', 'capacity': 14, 'name': 'Переговорная 14 мест', 'width_m': 4.5, 'height_m': 2.5, 'active': True, 'places_count': 0},
        {'id': 2, 'kind': 'room', 'capacity': 14, 'name': 'Переговорная 14 мест', 'width_m': 4.5, 'height_m': 2.5, 'active': True, 'places_count': 3},
    ]
    result = dedupe_category_dicts(cats)
    assert len(result) == 1
    assert result[0]['id'] == 2


def test_dedup_key_room_uses_capacity_only():
    a = _cat(capacity=10, name='Переговорная 10 мест')
    b = _cat(capacity=10, name='Комната 10')
    assert category_dedup_key(a) == category_dedup_key(b)
