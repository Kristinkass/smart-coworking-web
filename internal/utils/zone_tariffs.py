"""Тарифы закрытой зоны: сумма цен столов внутри, тип — только если он есть у каждого стола."""
from internal.models.place import Place

ZONE_TARIFF_TYPES = ('hourly', 'weekly', 'monthly')


def _layout_visual_only_desk_codes(space_code, layout_places):
    return {
        lp.get('code')
        for lp in layout_places
        if lp.get('container_code') == space_code
        and lp.get('kind') == 'desk'
        and lp.get('visual_only')
        and lp.get('code')
    }


def zone_bookable_desks(space_code, layout_places=None):
    """Активные столы зоны (без visual_only из layout)."""
    if layout_places is None:
        from internal.layout.store import load_layout
        layout_places = load_layout().get('places', [])

    skip_codes = _layout_visual_only_desk_codes(space_code, layout_places)
    desks = Place.query.filter_by(
        container_code=space_code,
        kind='desk',
        active=True,
    ).all()
    return [d for d in desks if d.code not in skip_codes]


def compute_zone_tariffs(space_code, layout_places=None):
    """Суммарные тарифы зоны: {tariff_type: price}.

    Тип включается только если активный тариф этого типа есть у каждого стола внутри.
    """
    desks = zone_bookable_desks(space_code, layout_places)
    if not desks:
        return {}

    result = {}
    for tariff_type in ZONE_TARIFF_TYPES:
        total = 0.0
        for desk in desks:
            price = desk.get_price(tariff_type)
            if price is None:
                break
            total += float(price)
        else:
            result[tariff_type] = round(total, 2)
    return result


def zone_tariff_price(space_code, tariff_type, layout_places=None):
    """Цена одного типа тарифа для зоны или None, если тип недоступен."""
    return compute_zone_tariffs(space_code, layout_places).get(tariff_type)
