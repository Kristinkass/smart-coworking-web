# -*- coding: utf-8 -*-
"""Генерация ER-диаграммы БД «Умный Коворкинг» в нотации IDEF1X (draw.io).

Запуск:  python scripts/generate_er_diagram.py
Результат: docs/ER-diagram.drawio
"""
import os

# ─────────────────────────── Схема БД ───────────────────────────
# key: 'PK' | 'FK' | '' (обычное поле)
TABLES = {
    "users": {
        "pos": (1000, 60),
        "fields": [
            ("PK", "id_user"),
            ("", "email"),
            ("", "username"),
            ("", "password_hash"),
            ("", "phone"),
            ("", "role"),
            ("", "visitor_kind"),
            ("", "active"),
            ("", "created_at"),
            ("", "last_login"),
        ],
    },
    "coworkings": {
        "pos": (40, 60),
        "fields": [
            ("PK", "id_coworking"),
            ("", "name"),
            ("", "address"),
        ],
    },
    "floors": {
        "pos": (40, 240),
        "fields": [
            ("PK", "id_floor"),
            ("FK", "coworking_id"),
            ("", "number"),
            ("", "name"),
        ],
    },
    "coworking_schedules": {
        "pos": (40, 470),
        "fields": [
            ("PK", "id_schedule"),
            ("FK", "id_coworking"),
            ("", "day_of_week"),
            ("", "open_time"),
            ("", "close_time"),
            ("", "is_active"),
            ("", "is_bookable"),
        ],
    },
    "location_zone_types": {
        "pos": (40, 730),
        "fields": [
            ("PK", "id_zone_type"),
            ("", "letter"),
            ("", "name"),
            ("", "kind"),
            ("", "active"),
        ],
    },
    "locations": {
        "pos": (360, 360),
        "fields": [
            ("PK", "id_location"),
            ("FK", "floor_id"),
            ("FK", "zone_type_id"),
            ("", "code"),
            ("", "name"),
            ("", "kind"),
        ],
    },
    "place_categories": {
        "pos": (360, 660),
        "fields": [
            ("PK", "id_category"),
            ("", "name"),
            ("", "kind"),
            ("", "capacity"),
            ("", "width_m"),
            ("", "height_m"),
            ("", "active"),
        ],
    },
    "category_tariffs": {
        "pos": (680, 720),
        "fields": [
            ("PK", "id_tariff"),
            ("FK", "category_id"),
            ("", "tariff_type"),
            ("", "price"),
            ("", "active"),
            ("", "updated_at"),
        ],
    },
    "places": {
        "pos": (680, 360),
        "fields": [
            ("PK", "id_place"),
            ("FK", "location_id"),
            ("FK", "floor_id"),
            ("FK", "category_id"),
            ("", "code"),
            ("", "name"),
            ("", "kind"),
            ("", "container_code"),
            ("", "enclosed"),
            ("", "status"),
            ("", "rating"),
            ("", "rating_count"),
            ("", "maintenance"),
            ("", "active"),
        ],
    },
    "subscriptions": {
        "pos": (1000, 420),
        "fields": [
            ("PK", "id_subscription"),
            ("FK", "user_id"),
            ("", "name"),
            ("", "is_template"),
            ("", "place_kinds"),
            ("", "start_date"),
            ("", "end_date"),
            ("", "hours_limit"),
            ("", "hours_used"),
            ("", "price"),
            ("", "active"),
        ],
    },
    "bookings": {
        "pos": (1340, 60),
        "fields": [
            ("PK", "id_booking"),
            ("FK", "user_id"),
            ("FK", "place_id"),
            ("FK", "category_tariff_id"),
            ("FK", "subscription_id"),
            ("", "tariff_type"),
            ("", "booking_date"),
            ("", "start_time"),
            ("", "end_time"),
            ("", "duration_hours"),
            ("", "total_price"),
            ("", "status"),
            ("", "created_at"),
        ],
    },
    "ratings": {
        "pos": (1340, 560),
        "fields": [
            ("PK", "id_rating"),
            ("FK", "user_id"),
            ("FK", "place_id"),
            ("FK", "booking_id"),
            ("", "score"),
            ("", "comment"),
            ("", "created_at"),
        ],
    },
    "notifications": {
        "pos": (1340, 820),
        "fields": [
            ("PK", "id_notification"),
            ("FK", "user_id"),
            ("FK", "sender_id"),
            ("FK", "booking_id"),
            ("", "title"),
            ("", "message"),
            ("", "target_audience"),
            ("", "is_read"),
            ("", "created_at"),
        ],
    },
}

# (родитель, поле_PK, потомок, поле_FK, optional)
# optional=True — FK допускает NULL (на стороне «много» в IDEF1X — необязательное участие)
RELATIONS = [
    ("coworkings", "id_coworking", "floors", "coworking_id", False),
    ("coworkings", "id_coworking", "coworking_schedules", "id_coworking", False),
    ("floors", "id_floor", "locations", "floor_id", False),
    ("floors", "id_floor", "places", "floor_id", True),
    ("location_zone_types", "id_zone_type", "locations", "zone_type_id", True),
    ("locations", "id_location", "places", "location_id", False),
    ("place_categories", "id_category", "category_tariffs", "category_id", False),
    ("place_categories", "id_category", "places", "category_id", True),
    ("category_tariffs", "id_tariff", "bookings", "category_tariff_id", True),
    ("users", "id_user", "bookings", "user_id", False),
    ("users", "id_user", "subscriptions", "user_id", True),
    ("users", "id_user", "ratings", "user_id", False),
    ("users", "id_user", "notifications", "user_id", True),
    ("users", "id_user", "notifications", "sender_id", True),
    ("places", "id_place", "bookings", "place_id", False),
    ("places", "id_place", "ratings", "place_id", False),
    ("subscriptions", "id_subscription", "bookings", "subscription_id", True),
    ("bookings", "id_booking", "ratings", "booking_id", True),
    ("bookings", "id_booking", "notifications", "booking_id", True),
]

HEADER_H = 30
ROW_H = 24
DIVIDER_H = 4
NAME_W_MIN = 150


def col_name_width(fields):
    longest = max((len(n) for _, n in fields), default=8)
    return max(NAME_W_MIN, longest * 8 + 24)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pk_count(fields):
    return sum(1 for k, _ in fields if k == "PK")


def build_entity(tname, t, cells, row_ids):
    x, y = t["pos"]
    fields = t["fields"]
    tw = col_name_width(fields)
    n_pk = pk_count(fields)
    th = HEADER_H + ROW_H * len(fields) + (DIVIDER_H if n_pk < len(fields) else 0)
    tid = f"tbl_{tname}"

    # IDEF1X: прямоугольник сущности, имя в заголовке
    cells.append(
        f'<mxCell id="{tid}" value="{esc(tname)}" '
        f'style="shape=table;startSize={HEADER_H};container=1;collapsible=0;childLayout=tableLayout;'
        f'fixedRows=1;rowLines=0;columnLines=0;fillColor=#ffffff;strokeColor=#000000;'
        f'fontStyle=1;fontSize=13;align=center;rounded=0;" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{tw}" height="{th}" as="geometry"/></mxCell>'
    )

    row_idx = 0
    y_off = HEADER_H
    for i, (key, fname) in enumerate(fields):
        # Разделитель PK | атрибуты (IDEF1X)
        if i == n_pk and n_pk < len(fields):
            rid = f"{tid}_div"
            cells.append(
                f'<mxCell id="{rid}" value="" '
                f'style="shape=tableRow;horizontal=0;startSize=0;swimlaneHead=0;swimlaneBody=0;'
                f'top=0;left=0;bottom=0;right=0;collapsible=0;dropTarget=0;'
                f'fillColor=#000000;strokeColor=#000000;" '
                f'vertex="1" parent="{tid}">'
                f'<mxGeometry y="{y_off}" width="{tw}" height="{DIVIDER_H}" as="geometry"/></mxCell>'
            )
            y_off += DIVIDER_H

        rid = f"{tid}_r{row_idx}"
        row_ids[(tname, fname)] = rid
        row_idx += 1

        if key == "PK":
            display = f"&lt;u&gt;{esc(fname)}&lt;/u&gt;"
        elif key == "FK":
            display = f"{esc(fname)} *"
        else:
            display = esc(fname)

        cells.append(
            f'<mxCell id="{rid}" value="" '
            f'style="shape=tableRow;horizontal=0;startSize=0;swimlaneHead=0;swimlaneBody=0;'
            f'strokeColor=inherit;top=0;left=0;bottom=0;right=0;collapsible=0;dropTarget=0;'
            f'fillColor=none;points=[[0,0.5],[1,0.5]];portConstraint=eastwest;fontSize=12;" '
            f'vertex="1" parent="{tid}"><mxGeometry y="{y_off}" width="{tw}" height="{ROW_H}" as="geometry"/></mxCell>'
        )
        cells.append(
            f'<mxCell id="{rid}_n" value="{display}" '
            f'style="shape=partialRectangle;html=1;whiteSpace=wrap;connectable=0;strokeColor=inherit;'
            f'overflow=hidden;fillColor=none;top=0;left=0;bottom=0;right=0;align=left;spacingLeft=8;fontSize=12;" '
            f'vertex="1" parent="{rid}"><mxGeometry width="{tw}" height="{ROW_H}" as="geometry">'
            f'<mxRectangle width="{tw}" height="{ROW_H}" as="alternateBounds"/></mxGeometry></mxCell>'
        )
        y_off += ROW_H


def build_relations(cells, row_ids):
    """IDEF1X: пунктир — нетождественная связь; * у FK — необязательное участие."""
    for idx, (p, pf, c, cf, optional) in enumerate(RELATIONS):
        src = row_ids[(p, pf)]
        dst = row_ids[(c, cf)]
        eid = f"rel_{idx}"
        end_arrow = "ERzeroToMany" if optional else "ERoneToMany"
        cells.append(
            f'<mxCell id="{eid}" value="" '
            f'style="edgeStyle=entityRelationEdgeStyle;fontSize=12;html=1;'
            f'startArrow=ERmandOne;endArrow={end_arrow};dashed=1;'
            f'rounded=0;exitX=1;exitY=0.5;entryX=0;entryY=0.5;strokeColor=#000000;" '
            f'edge="1" parent="1" source="{src}" target="{dst}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>'
        )


def build_legend(cells):
    cells.append(
        '<mxCell id="legend_box" value="" '
        'style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;" '
        'vertex="1" parent="1">'
        '<mxGeometry x="40" y="980" width="520" height="90" as="geometry"/></mxCell>'
    )
    cells.append(
        '<mxCell id="legend_title" value="Условные обозначения IDEF1X" '
        'style="text;html=1;strokeColor=none;fillColor=none;align=left;fontStyle=1;fontSize=12;" '
        'vertex="1" parent="1">'
        '<mxGeometry x="50" y="988" width="300" height="20" as="geometry"/></mxCell>'
    )
    cells.append(
        '<mxCell id="legend1" value="&lt;u&gt;атрибут&lt;/u&gt; — первичный ключ" '
        'style="text;html=1;strokeColor=none;fillColor=none;align=left;fontSize=11;" '
        'vertex="1" parent="1">'
        '<mxGeometry x="50" y="1010" width="240" height="18" as="geometry"/></mxCell>'
    )
    cells.append(
        '<mxCell id="legend2" value="fk_field * — внешний ключ (необязательное участие)" '
        'style="text;html=1;strokeColor=none;fillColor=none;align=left;fontSize=11;" '
        'vertex="1" parent="1">'
        '<mxGeometry x="50" y="1030" width="320" height="18" as="geometry"/></mxCell>'
    )
    cells.append(
        '<mxCell id="legend3" value="Пунктирная линия — нетождественная (non-identifying) связь" '
        'style="text;html=1;strokeColor=none;fillColor=none;align=left;fontSize=11;" '
        'vertex="1" parent="1">'
        '<mxGeometry x="50" y="1050" width="400" height="18" as="geometry"/></mxCell>'
    )


def build():
    cells = []
    row_ids = {}

    for tname, t in TABLES.items():
        build_entity(tname, t, cells, row_ids)

    build_relations(cells, row_ids)
    build_legend(cells)

    title = (
        '<mxCell id="title" value="IDEF1X-диаграмма базы данных системы «Умный Коворкинг»" '
        'style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;'
        'fontSize=16;fontStyle=1;" vertex="1" parent="1">'
        '<mxGeometry x="480" y="10" width="780" height="30" as="geometry"/></mxCell>'
    )

    body = "\n        ".join([title] + cells)
    xml = (
        '<mxfile host="app.diagrams.net" agent="cursor" version="22.1.0" type="device">\n'
        '  <diagram id="er-coworking-idef1x" name="IDEF1X-диаграмма">\n'
        '    <mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" guides="1" tooltips="1" '
        'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1800" pageHeight="1100" math="0" shadow="0">\n'
        '      <root>\n'
        '        <mxCell id="0"/>\n'
        '        <mxCell id="1" parent="0"/>\n'
        f'        {body}\n'
        '      </root>\n'
        '    </mxGraphModel>\n'
        '  </diagram>\n'
        '</mxfile>\n'
    )
    return xml


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "..", "docs", "ER-diagram.drawio")
    out = os.path.normpath(out)
    with open(out, "w", encoding="utf-8") as f:
        f.write(build())
    print(f"OK: {out}")


if __name__ == "__main__":
    main()
