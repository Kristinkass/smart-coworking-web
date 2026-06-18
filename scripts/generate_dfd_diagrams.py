#!/usr/bin/env python3
"""Генерация DFD-диаграмм draw.io (Гейна–Сарсона).

Запуск:
    python scripts/generate_dfd_diagrams.py

Результат:
    docs/DFD-full-level1.drawio   — полная DFD системы (уровень 1)
    docs/DFD-A0-context.drawio    — контекст (A-0)
    docs/DFD-A1-level1.drawio     — декомпозиция A1 (в стиле полной DFD)
    docs/DFD-A1-level2-A12.drawio — детализация редактора
"""
from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

# Светлая тема — вспомогательные DFD; тёмная — основная DFD уровня 1 (как в ПЗ).
STYLE = {
    "light": {
        "entity": (
            "rounded=0;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
            "fillColor=#f5f5f5;strokeColor=#666666;fontStyle=1"
        ),
        "process": (
            "ellipse;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
            "fillColor=#fff2cc;strokeColor=#d6b656;fontStyle=0"
        ),
        "datastore": (
            "shape=partialRectangle;right=0;whiteSpace=wrap;html=1;align=left;"
            "verticalAlign=middle;spacingLeft=8;fillColor=#dae8fc;strokeColor=#6c8ebf;"
        ),
        "flow": "endArrow=block;html=1;rounded=0;fontSize=10;",
        "title": (
            "text;html=1;strokeColor=none;fillColor=none;align=center;"
            "verticalAlign=middle;fontSize=15;fontStyle=1"
        ),
        "legend": (
            "text;html=1;strokeColor=#999999;fillColor=#ffffff;align=left;"
            "verticalAlign=top;spacingLeft=8;fontSize=10;"
        ),
    },
    "dark": {
        "entity": (
            "rounded=0;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
            "fillColor=#000000;strokeColor=#FFFFFF;fontColor=#FFFFFF;fontStyle=1"
        ),
        "process": (
            "ellipse;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
            "fillColor=#000000;strokeColor=#FFFFFF;fontColor=#FFFFFF;fontStyle=0"
        ),
        "datastore": (
            "shape=partialRectangle;right=0;whiteSpace=wrap;html=1;align=left;"
            "verticalAlign=middle;spacingLeft=8;fillColor=#000000;strokeColor=#FFFFFF;"
            "fontColor=#FFFFFF;"
        ),
        "flow": (
            "endArrow=block;html=1;rounded=0;fontSize=10;"
            "strokeColor=#FFFFFF;fontColor=#FFFFFF;"
        ),
        "title": (
            "text;html=1;strokeColor=none;fillColor=none;align=center;"
            "verticalAlign=middle;fontSize=15;fontStyle=1;fontColor=#FFFFFF"
        ),
        "legend": (
            "text;html=1;strokeColor=#FFFFFF;fillColor=#000000;align=left;"
            "verticalAlign=top;spacingLeft=8;fontSize=10;fontColor=#FFFFFF;"
        ),
    },
}


def esc(text: str) -> str:
    """Экранирование для XML-атрибутов draw.io."""
    return html.escape(text, quote=True)


def nl(*lines: str) -> str:
    """Многострочная подпись (без сырого «<» в атрибутах)."""
    return "&#xa;".join(esc(line) for line in lines)


def mxfile(
    diagram_id: str,
    diagram_name: str,
    cells: str,
    w: int = 1400,
    h: int = 900,
    *,
    dark: bool = False,
) -> str:
    bg = ' background="#000000" gridColor="#333333"' if dark else ""
    return f"""<mxfile host="app.diagrams.net" agent="generate_dfd_diagrams.py" version="22.1.0" type="device">
  <diagram id="{diagram_id}" name="{esc(diagram_name)}">
    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{w}" pageHeight="{h}" math="0" shadow="0"{bg}>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
{cells}
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
"""


def page_background(w: int, h: int, theme: str) -> str:
    if theme != "dark":
        return ""
    return (
        '        <mxCell id="bg" value="" style="rounded=0;whiteSpace=wrap;html=1;'
        'fillColor=#000000;strokeColor=none;" vertex="1" parent="1">\n'
        f'          <mxGeometry x="0" y="0" width="{w}" height="{h}" as="geometry"/>\n'
        "        </mxCell>\n"
    )


def title_cell(text: str, x: int, y: int, w: int = 700, *, theme: str = "light") -> str:
    return (
        f'        <mxCell id="title" value="{esc(text)}" '
        f'style="{STYLE[theme]["title"]}" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="28" as="geometry"/>\n'
        "        </mxCell>\n"
    )


def entity(
    eid: str, label: str, x: int, y: int, w: int = 120, h: int = 50, *, theme: str = "light"
) -> str:
    return (
        f'        <mxCell id="{eid}" value="{esc(label)}" '
        f'style="{STYLE[theme]["entity"]}" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>\n'
        "        </mxCell>\n"
    )


def process(
    pid: str,
    num: str,
    name: str,
    x: int,
    y: int,
    w: int = 110,
    h: int = 110,
    *,
    theme: str = "light",
) -> str:
    return (
        f'        <mxCell id="{pid}" value="{nl(num, name)}" '
        f'style="{STYLE[theme]["process"]}" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>\n'
        "        </mxCell>\n"
    )


def datastore(
    did: str, label: str, x: int, y: int, w: int = 150, h: int = 50, *, theme: str = "light"
) -> str:
    return (
        f'        <mxCell id="{did}" value="{esc(label)}" '
        f'style="{STYLE[theme]["datastore"]}" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>\n'
        "        </mxCell>\n"
    )


def flow(
    fid: str, label: str, src: str, tgt: str, style: str = "", *, theme: str = "light"
) -> str:
    base = STYLE[theme]["flow"]
    return (
        f'        <mxCell id="{fid}" value="{esc(label)}" style="{base}{style}" '
        f'edge="1" parent="1" source="{src}" target="{tgt}">\n'
        '          <mxGeometry relative="1" as="geometry"/>\n'
        "        </mxCell>\n"
    )


def legend_box(x: int, y: int, *, theme: str = "light") -> str:
    text = esc(
        "Обозначения DFD (Гейн–Сарсон):\n"
        "□ — внешняя сущность\n"
        "○ — процесс\n"
        "═| — хранилище данных"
    ).replace("&#10;", "&#xa;").replace("\n", "&#xa;")
    return (
        f'        <mxCell id="legend" value="{text}" '
        f'style="{STYLE[theme]["legend"]}" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="220" height="88" as="geometry"/>\n'
        "        </mxCell>\n"
    )


def build_full_level1() -> str:
    """Полная DFD уровня 1 — основная диаграмма системы (тёмное оформление ПЗ)."""
    theme = "dark"
    w, h = 1360, 820
    kw = {"theme": theme}
    parts = [
        page_background(w, h, theme),
        title_cell("DFD уровень 1: система «Умный Коворкинг»", 280, 15, 840, **kw),
        entity("e_admin", "Администратор", 30, 180, 130, 55, **kw),
        entity("e_manager", "Менеджер", 30, 420, 130, 55, **kw),
        entity("e_client", "Клиент", 1180, 60, 120, 50, **kw),
        process(
            "p1",
            "1",
            "Внесение данных о местах, категориях и планировке",
            220,
            60,
            130,
            120,
            **kw,
        ),
        process("p2", "2", "Добавление расписания", 220, 210, 120, 120, **kw),
        process("p3", "3", "Добавление тарифов и абонементов", 220, 360, 120, 120, **kw),
        process(
            "p4",
            "4",
            "Обновление карты мест и синхронизация с БД",
            520,
            210,
            150,
            140,
            **kw,
        ),
        process(
            "p5",
            "5",
            "Бронирование места (слоты / абонемент)",
            820,
            60,
            130,
            120,
            **kw,
        ),
        process("p6", "6", "Обновление истории бронирований", 820, 230, 140, 120, **kw),
        process("p7", "7", "Выставление оценки", 820, 390, 120, 120, **kw),
        process(
            "p8",
            "8",
            "Составление отчётности о доходах и статистике",
            1080,
            230,
            150,
            140,
            **kw,
        ),
        datastore("d11", "1.1 Карта мест и планировка (layout.json)", 210, 530, 270, 50, **kw),
        datastore("d21", "2.1 Расписание работы коворкинга", 210, 610, 220, 50, **kw),
        datastore("d31", "3.1 Тарифы и абонементы", 210, 690, 180, 50, **kw),
        datastore("d41", "4.1 Актуальная карта, статусы и тарифы", 500, 530, 260, 50, **kw),
        datastore("d51", "5.1 Список активных бронирований", 810, 530, 210, 50, **kw),
        datastore("d61", "6.1 История бронирований", 810, 610, 180, 50, **kw),
        datastore("d71", "7.1 Список оценок", 810, 690, 150, 50, **kw),
        datastore("d81", "8.1 Отчёты", 1080, 530, 130, 50, **kw),
        flow(
            "f01",
            "места, категории, планировка",
            "e_admin",
            "p1",
            "exitX=1;exitY=0.35;entryX=0;entryY=0.5;",
            **kw,
        ),
        flow("f02", "расписание", "e_admin", "p2", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", **kw),
        flow(
            "f03",
            "тарифы, абонементы",
            "e_admin",
            "p3",
            "exitX=1;exitY=0.65;entryX=0;entryY=0.5;",
            **kw,
        ),
        flow(
            "fm1",
            "статусы, техобслуживание",
            "e_manager",
            "p4",
            "exitX=1;exitY=0.35;entryX=0;entryY=0.85;",
            **kw,
        ),
        flow(
            "fm2",
            "выдача абонементов",
            "e_manager",
            "p3",
            "exitX=1;exitY=0.35;entryX=0;entryY=0.75;",
            **kw,
        ),
        flow(
            "fm3",
            "бронь за клиента, отмена, продление",
            "e_manager",
            "p5",
            "exitX=1;exitY=0.25;entryX=0;entryY=0.85;",
            **kw,
        ),
        flow(
            "fm4",
            "запрос отчётов",
            "e_manager",
            "p8",
            "exitX=1;exitY=0.65;entryX=0;entryY=0.85;",
            **kw,
        ),
        flow("f04", "карта, геометрия", "p1", "d11", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", **kw),
        flow("f05", "график работы", "p2", "d21", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", **kw),
        flow("f06", "тарифы, абонементы", "p3", "d31", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", **kw),
        flow("f07", "карта мест", "d11", "p4", "exitX=1;exitY=0.25;entryX=0;entryY=0.25;", **kw),
        flow("f08", "расписание", "d21", "p4", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", **kw),
        flow("f09", "тарифы", "d31", "p4", "exitX=1;exitY=0.75;entryX=0;entryY=0.75;", **kw),
        flow("f10", "актуальная карта", "p4", "d41", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", **kw),
        flow("f11", "запрос брони", "e_client", "p5", "exitX=0;exitY=0.5;entryX=1;entryY=0.5;", **kw),
        flow(
            "f12",
            "карта, тарифы, слоты",
            "d41",
            "p5",
            "exitX=1;exitY=0.25;entryX=0;entryY=0.75;",
            **kw,
        ),
        flow("f13", "активные брони", "p5", "d51", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", **kw),
        flow("f14", "подтверждение", "p5", "e_client", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", **kw),
        flow(
            "fm5",
            "подтверждение брони",
            "p5",
            "e_manager",
            "exitX=0;exitY=0.75;entryX=1;entryY=0.35;",
            **kw,
        ),
        flow("f15", "активные брони", "d51", "p6", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", **kw),
        flow("f16", "история", "p6", "d61", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", **kw),
        flow("f17", "оценка", "e_client", "p7", "exitX=0;exitY=0.5;entryX=1;entryY=0.5;", **kw),
        flow("f18", "оценки", "p7", "d71", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", **kw),
        flow("f19", "история", "d61", "p8", "exitX=1;exitY=0.35;entryX=0;entryY=0.35;", **kw),
        flow("f20", "оценки", "d71", "p8", "exitX=1;exitY=0.65;entryX=0;entryY=0.65;", **kw),
        flow(
            "f23",
            "запрос отчётов",
            "e_admin",
            "p8",
            "exitX=1;exitY=0.75;entryX=0;entryY=0.65;",
            **kw,
        ),
        flow("f21", "отчёты", "p8", "d81", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", **kw),
        flow("f22", "статистика, доходы", "p8", "e_admin", "exitX=0;exitY=0.35;entryX=1;entryY=0.35;", **kw),
        flow(
            "fm6",
            "статистика, доходы",
            "p8",
            "e_manager",
            "exitX=0;exitY=0.65;entryX=1;entryY=0.65;",
            **kw,
        ),
        legend_box(30, 680, **kw),
    ]
    return mxfile("dfd-full-l1", "DFD Полная уровень 1", "".join(parts), w, h, dark=True)


def build_a0_context() -> str:
    parts = [
        title_cell("DFD уровень 0 (контекст): система управления коворкингом", 250, 20, 900),
        entity("e_admin", "Администратор", 40, 200, 130, 55),
        entity("e_client", "Клиент", 40, 400, 130, 55),
        entity("e_manager", "Менеджер", 40, 600, 130, 55),
        process("p0", "0", "Управление коворкингом", 520, 340, 160, 160),
        flow("f1", "настройка мест, тарифов", "e_admin", "p0", "exitX=1;exitY=0.35;entryX=0;entryY=0.25;"),
        flow("f2", "запрос брони, карта", "e_client", "p0", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"),
        flow("f3", "управление бронями", "e_manager", "p0", "exitX=1;exitY=0.5;entryX=0;entryY=0.75;"),
        flow("f4", "подтверждение брони", "p0", "e_client", "exitX=0;exitY=0.5;entryX=1;entryY=0.5;"),
        flow("f5", "отчёты, уведомления", "p0", "e_admin", "exitX=0;exitY=0.35;entryX=1;entryY=0.5;"),
        legend_box(900, 560),
    ]
    return mxfile("dfd-a0", "DFD A-0 Контекст", "".join(parts), 1100, 720)


def build_a1_level1() -> str:
    """DFD декомпозиции A1 в том же стиле, что и полная DFD."""
    parts = [
        title_cell("DFD уровень 1: A1 «Управление пространством коворкинга»", 220, 15, 960),
        entity("e_admin", "Администратор", 30, 260, 130, 55),
        entity("e_client", "Клиент", 1180, 80, 120, 50),
        entity("e_a2", "A2 Бронирования", 1180, 380, 140, 50),
        process("p1", "A11", "Внесение категорий и тарифов мест", 220, 60, 130, 120),
        process("p2", "A12", "Редактирование планировки (редактор)", 220, 220, 140, 120),
        process("p3", "A13", "Управление статусами мест", 220, 380, 130, 120),
        process("p4", "A14", "Синхронизация БД и layout.json", 520, 220, 150, 140),
        process("p5", "A15", "Формирование актуальной карты", 820, 220, 150, 140),
        datastore("d11", "A1.1 Категории и тарифы", 210, 540, 180, 50),
        datastore("d12", "A1.2 layout.json (стены, двери, places)", 210, 620, 240, 50),
        datastore("d13", "A1.3 Места (PostgreSQL)", 500, 540, 180, 50),
        datastore("d14", "A1.4 Актуальная карта и статусы", 810, 540, 230, 50),
        flow("fa1", "CRUD категорий", "e_admin", "p1", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"),
        flow("fa2", "стены, столы, комнаты", "e_admin", "p2", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"),
        flow("fa3", "maintenance, статусы", "e_admin", "p3", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"),
        flow("fa4", "категории, тарифы", "p1", "d11", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"),
        flow("fa5", "шаблоны размеров", "d11", "p2", "exitX=1;exitY=0.25;entryX=0;entryY=0.25;"),
        flow("fa6", "walls, doors, places", "p2", "d12", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"),
        flow("fa7", "геометрия places", "d12", "p4", "exitX=1;exitY=0.35;entryX=0;entryY=0.35;"),
        flow("fa8", "sync Place, container_code", "p4", "d13", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"),
        flow("fa9", "данные places", "d13", "p4", "exitX=0.5;exitY=0;entryX=0.5;entryY=1;"),
        flow("fa10", "статусы, maintenance", "p3", "d13", "exitX=1;exitY=0.5;entryX=0;entryY=0.75;"),
        flow("fa11", "занятость слотов", "e_a2", "p3", "exitX=0;exitY=0.5;entryX=1;entryY=0.5;"),
        flow("fa12", "capacity, kind", "d13", "e_a2", "exitX=1;exitY=0.35;entryX=0;entryY=0.5;"),
        flow("fa13", "карта, статусы", "d13", "p5", "exitX=1;exitY=0.5;entryX=0;entryY=0.35;"),
        flow("fa14", "layout + БД", "p4", "p5", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"),
        flow("fa15", "актуальная карта", "p5", "d14", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"),
        flow("fa16", "карта мест", "d14", "e_client", "exitX=1;exitY=0.25;entryX=0;entryY=0.5;"),
        flow("fa17", "данные для брони", "d14", "e_a2", "exitX=1;exitY=0.75;entryX=0;entryY=0.5;"),
        legend_box(30, 600),
    ]
    return mxfile("dfd-a1-l1", "DFD A1 Уровень 1", "".join(parts), 1360, 720)


def build_a12_level2() -> str:
    """Уровень 2: редактор планировки (A12)."""
    parts = [
        title_cell("DFD уровень 2: A12 «Редактор планировки»", 200, 15, 900),
        entity("adm", "Администратор", 30, 280, 120, 50),
        process("p1", "1", "Рисование стен и дверей", 220, 80, 110, 110),
        process("p2", "2", "Регистрация комнаты по стенам", 400, 80, 120, 110),
        process("p3", "3", "Размещение столов", 600, 80, 110, 110),
        process("p4", "4", "Проверка пересечений", 600, 260, 120, 110),
        process("p5", "5", "Синхронизация Place в БД", 940, 260, 120, 110),
        process("p6", "6", "Создание зоны вручную", 780, 80, 120, 110),
        datastore("dw", "D walls[]", 220, 480, 120, 45),
        datastore("dd", "D doors[]", 360, 480, 120, 45),
        datastore("dp", "D places[] (геометрия)", 720, 480, 170, 45),
        datastore("db", "D2 PostgreSQL places", 940, 480, 150, 50),
        flow("g1", "сегменты стен", "adm", "p1"),
        flow("g2", "walls", "p1", "dw", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"),
        flow("g3", "двери", "p1", "dd", "exitX=1;exitY=0.75;entryX=0;entryY=0.5;"),
        flow("g4", "контур комнаты", "adm", "p2"),
        flow("g5", "space / enclosed", "p2", "dp", "exitX=0.5;exitY=1;entryX=0.25;entryY=0;"),
        flow("g6", "шаблон стола", "adm", "p3"),
        flow("g7", "desk", "p3", "p4", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"),
        flow("g8", "выделенные столы", "adm", "p6"),
        flow("g9", "open zone", "p6", "p4", "exitX=0;exitY=0.5;entryX=1;entryY=0.5;"),
        flow("g10", "places", "p4", "dp", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"),
        flow("g11", "code", "dp", "p5", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"),
        flow("g12", "Place row", "p5", "db", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"),
        flow("g13", "геометрия", "dp", "p2", "exitX=0;exitY=0.25;entryX=1;entryY=0.75;"),
        legend_box(30, 560),
    ]
    return mxfile("dfd-a12-l2", "DFD A12 Уровень 2", "".join(parts), 1140, 620)


def validate_xml(path: Path, content: str) -> None:
    try:
        ET.fromstring(content)
    except ET.ParseError as exc:
        raise SystemExit(f"Invalid XML in {path}: {exc}") from exc


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    files = {
        "DFD-full-level1.drawio": build_full_level1(),
        "DFD-A0-context.drawio": build_a0_context(),
        "DFD-A1-level1.drawio": build_a1_level1(),
        "DFD-A1-level2-A12.drawio": build_a12_level2(),
    }
    for name, content in files.items():
        path = DOCS / name
        validate_xml(path, content)
        path.write_text(content, encoding="utf-8")
        print(f"Written: {path}")


if __name__ == "__main__":
    main()
