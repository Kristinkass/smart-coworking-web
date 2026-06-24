"""Дедупликация категорий мест (переговорные с одинаковой вместимостью и т.п.)."""
from __future__ import annotations

from typing import Any

from internal.models.category import PlaceCategory, is_auto_zone_category


def category_dedup_key(cat) -> tuple:
    """Ключ группировки дублей: для room — вместимость, для desk — размер + имя."""
    if isinstance(cat, dict):
        kind = cat.get('kind') or ''
        capacity = int(cat.get('capacity') or 0)
        name = (cat.get('name') or '').strip().lower()
        width_m = round(float(cat.get('width_m') or 0), 2)
        height_m = round(float(cat.get('height_m') or 0), 2)
    else:
        kind = cat.kind or ''
        capacity = int(cat.capacity or 0)
        name = (cat.name or '').strip().lower()
        width_m = round(float(cat.width_m or 0), 2)
        height_m = round(float(cat.height_m or 0), 2)

    if kind == 'room':
        return ('room', capacity)
    return ('desk', capacity, width_m, height_m, name)


def category_priority_score(cat, *, places_count: int | None = None) -> tuple:
    """Чем выше кортеж — тем предпочтительнее оставить категорию."""
    if isinstance(cat, dict):
        active = 1 if cat.get('active', True) else 0
        tariffs = sum(
            1 for t in (cat.get('tariffs') or []) if t.get('active', True)
        )
        places = int(cat.get('places_count') or 0)
        cat_id = int(cat.get('id') or 0)
    else:
        active = 1 if cat.active else 0
        tariffs = sum(1 for t in (cat.tariffs or []) if t.active)
        places = places_count if places_count is not None else len(cat.places or [])
        cat_id = int(cat.id_category or 0)
    return (places, tariffs, active, -cat_id)


def dedupe_category_orm_list(categories: list) -> list:
    """Оставить по одной категории на ключ дедупликации."""
    best: dict[tuple, Any] = {}
    for cat in categories:
        if is_auto_zone_category(cat):
            continue
        key = category_dedup_key(cat)
        prev = best.get(key)
        if prev is None or category_priority_score(cat) > category_priority_score(prev):
            best[key] = cat
    ordered = list(best.values())
    ordered.sort(key=lambda c: (c.kind or '', c.capacity or 0, c.name or ''))
    return ordered


def dedupe_category_dicts(categories: list[dict]) -> list[dict]:
    best: dict[tuple, dict] = {}
    for cat in categories:
        key = category_dedup_key(cat)
        prev = best.get(key)
        if prev is None or category_priority_score(cat) > category_priority_score(prev):
            best[key] = cat
    ordered = list(best.values())
    ordered.sort(key=lambda c: (c.get('kind', ''), c.get('capacity', 0), c.get('name', '')))
    return ordered


def find_duplicate_groups(categories: list) -> dict[tuple, list]:
    groups: dict[tuple, list] = {}
    for cat in categories:
        if is_auto_zone_category(cat):
            continue
        key = category_dedup_key(cat)
        groups.setdefault(key, []).append(cat)
    return {k: v for k, v in groups.items() if len(v) > 1}


def merge_duplicate_categories(db_session) -> dict:
    """
    Объединить дубли в БД: места и тарифы переносятся на «лучшую» категорию,
    лишние деактивируются.
    """
    from internal.models import CategoryTariff, Place
    from internal.layout.repository import LayoutRepository

    all_cats = PlaceCategory.query.all()
    groups = find_duplicate_groups(all_cats)
    deactivated = []

    for _key, group in groups.items():
        group.sort(key=lambda c: category_priority_score(c), reverse=True)
        keeper, *losers = group
        keeper_places = Place.query.filter_by(category_id=keeper.id_category).count()

        for loser in losers:
            for place in Place.query.filter_by(category_id=loser.id_category).all():
                place.category_id = keeper.id_category
                try:
                    LayoutRepository.save_place_category(place.code, keeper.id_category)
                except Exception:
                    pass

            for tariff in CategoryTariff.query.filter_by(category_id=loser.id_category).all():
                existing = CategoryTariff.query.filter_by(
                    category_id=keeper.id_category,
                    tariff_type=tariff.tariff_type,
                ).first()
                if existing:
                    db_session.delete(tariff)
                else:
                    tariff.category_id = keeper.id_category

            loser.active = False
            deactivated.append({
                'id': loser.id_category,
                'name': loser.name,
                'kept_id': keeper.id_category,
                'kept_name': keeper.name,
            })

        keeper_places = Place.query.filter_by(category_id=keeper.id_category).count()
        keeper.active = True

    db_session.commit()
    return {
        'merged_groups': len(groups),
        'deactivated': deactivated,
    }
