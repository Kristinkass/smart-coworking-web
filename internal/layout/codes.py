"""Нормализация кодов мест: омоглифы, поиск в layout, локация стола."""

from __future__ import annotations

# Кириллица → латиница (визуально похожие буквы в кодах 1РС → 1PC)
_CODE_CHAR_MAP = str.maketrans({
    'А': 'A', 'а': 'A',
    'В': 'C', 'в': 'C',
    'Б': 'B', 'б': 'B',
    'С': 'C', 'с': 'C',
    'Р': 'P', 'р': 'P',
    'К': 'K', 'к': 'K',
    'О': 'O', 'о': 'O',
    'Е': 'E', 'е': 'E',
    'Н': 'H', 'н': 'H',
    'М': 'M', 'м': 'M',
    'Т': 'T', 'т': 'T',
    'Х': 'X', 'х': 'X',
    'У': 'Y', 'у': 'Y',
})


def normalize_code_chars(value):
    """Привести символы кода к латинице (омоглифы кириллицы)."""
    if value is None:
        return ''
    return str(value).strip().translate(_CODE_CHAR_MAP)


def codes_match(a, b):
    if not a or not b:
        return False
    return a == b or normalize_code_chars(a) == normalize_code_chars(b)


def find_layout_place(code, layout_places):
    """Найти запись layout по коду (точно или с учётом омоглифов)."""
    code = str(code or '').strip()
    if not code:
        return None, None
    for p in layout_places or []:
        c = p.get('code')
        if c == code:
            return p, c
    norm = normalize_code_chars(code)
    for p in layout_places or []:
        c = p.get('code')
        if c and normalize_code_chars(c) == norm:
            return p, c
    return None, None


def resolve_layout_place_code(code, layout_places=None):
    """Канонический код места в layout.json."""
    if layout_places is None:
        from internal.layout.store import load_layout
        layout_places = load_layout().get('places', [])
    _, canonical = find_layout_place(code, layout_places)
    return canonical


def resolve_location_for_layout_place(layout_place, layout_places=None):
    """Корректный код локации для объекта layout (стол наследует от контейнера)."""
    from internal.models.coworking import Location

    if layout_places is None:
        from internal.layout.store import load_layout
        layout_places = load_layout().get('places', [])

    container_code = layout_place.get('container_code')
    if container_code:
        container, _ = find_layout_place(container_code, layout_places)
        if container and container.get('location'):
            loc = normalize_code_chars(container['location'])
            if Location.query.filter_by(code=loc).first():
                return loc

    loc = normalize_code_chars(layout_place.get('location') or '')
    if loc and Location.query.filter_by(code=loc).first():
        return loc

    code = layout_place.get('code') or ''
    base = normalize_code_chars(str(code).split('-')[0])
    if base and Location.query.filter_by(code=base).first():
        return base

    return loc or None
