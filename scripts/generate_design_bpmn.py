"""Generate design-phase BPMN diagrams (roles and processes only, no implementation details)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / 'docs'
OUT_DIR = ROOT / 'docs' / 'design' / 'bpmn'

TITLE_BY_FILE = {
    'BPMN-manager-booking.drawio': 'Оформление брони менеджером за клиента',
    'BPMN-editor-place.drawio': 'Добавление рабочего места в редакторе планировки',
    'BPMN-maintenance.drawio': 'Перевод рабочего места в режим техобслуживания',
}

REPLACEMENTS: list[tuple[str, str]] = [
    ('BPMN: процесс «', 'Процесс «'),
    ('name="BPMN ', 'name="'),
    ('Сохранить бронь в БД и обновить карту мест', 'Сохранить бронирование в хранилище данных и обновить карту мест'),
    ('Сохранить бронь за&amp;nbsp;&lt;div&gt;клиентом в БД, обновить карту мест&lt;/div&gt;',
     'Сохранить бронирование за клиентом в хранилище данных и обновить карту мест'),
    ('Обновить время окончания и стоимость брони в БД',
     'Обновить время окончания и стоимость бронирования в хранилище данных'),
    ('Создать записи уведомлений в БД', 'Сохранить уведомления в хранилище данных'),
    ('Сохранить абонемент в БД', 'Сохранить абонемент в хранилище данных'),
    ('Сохранить оценку в БД (ratings, bookings.user_rating)', 'Сохранить оценку в хранилище данных'),
    ('Обновить rating и rating_count места', 'Обновить средний рейтинг и число оценок места'),
    ('Создать сессию (Flask-Login), обновить last_login', 'Создать пользовательскую сессию'),
    ('Нормализовать email, найти пользователя', 'Проверить учётные данные пользователя'),
    ('Захешировать пароль (PBKDF2)', 'Защитить пароль перед сохранением'),
    ('Создать учётную запись (role=client) и сессию', 'Создать учётную запись клиента и сессию'),
    ('Установить maintenance = true', 'Установить режим техобслуживания'),
    ('Рассчитать размеры по категории (1 м = 100 px)', 'Рассчитать размеры объекта по категории места'),
    ('Сохранить место в базе данных (код, категория)', 'Сохранить сведения о месте в хранилище данных'),
    ('Экспортировать отчёт в PDF', 'Экспортировать отчёт в файл'),
    ('Просмотр и скачивание отчёта (PDF)', 'Просмотр и скачивание отчёта'),
    (' в БД', ' в хранилище данных'),
]


def sanitize(content: str) -> str:
    for old, new in REPLACEMENTS:
        content = content.replace(old, new)
    content = re.sub(r'host="[^"]*"', 'host="app.diagrams.net"', content)
    content = re.sub(r'agent="[^"]*"', 'agent="design-export"', content)
    return content


def fix_rating_diagram(content: str) -> str:
    """Move system tasks from client lane into system lane."""
    for cell_id in ('s1', 's2', 's3', 's4'):
        content = content.replace(
            f'id="{cell_id}" parent="lane_client"',
            f'id="{cell_id}" parent="lane_system"',
        )
        content = content.replace(
            f'source="{cell_id}" style=',
            f'source="{cell_id}" style=',
        )
    content = content.replace('parent="lane_client" source="s1"', 'parent="lane_system" source="s1"')
    for cell_id in ('s1', 's2', 's3', 's4', 'es1', 'es2', 'es3', 'es4', 'ec5'):
        content = content.replace(f'edge="1" parent="lane_client" source="{cell_id}"',
                                  f'edge="1" parent="1" source="{cell_id}"')
        content = content.replace(f'edge="1" parent="lane_client" target="{cell_id}"',
                                  f'edge="1" parent="1" target="{cell_id}"')
    content = re.sub(
        r'(<mxCell id="s[1-4]" parent="lane_system"[^>]*vertex="1">\s*<mxGeometry height="60" width="[^"]*" )x="(\d+)" y="290"',
        lambda m: f'{m.group(1)}x="{m.group(2)}" y="60"',
        content,
    )
    return content


def ensure_title(content: str, filename: str) -> str:
    title = TITLE_BY_FILE.get(filename)
    if not title or 'id="title"' in content:
        return content
    insert = (
        '        <mxCell id="title" parent="1" '
        'style="text;html=1;strokeColor=none;fillColor=none;align=center;'
        'verticalAlign=middle;fontSize=15;fontStyle=1" '
        f'value="Процесс «{title}»" vertex="1">\n'
        '          <mxGeometry height="28" width="980" x="280" y="10" as="geometry" />\n'
        '        </mxCell>\n'
    )
    return content.replace('        <mxCell id="lane_', insert + '        <mxCell id="lane_', 1)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC_DIR.glob('BPMN-*.drawio'))
    if not files:
        raise SystemExit(f'No BPMN sources found in {SRC_DIR}')

    for src in files:
        content = sanitize(src.read_text(encoding='utf-8'))
        content = ensure_title(content, src.name)
        if src.name == 'BPMN-rating.drawio':
            content = fix_rating_diagram(content)
        out = OUT_DIR / src.name
        out.write_text(content, encoding='utf-8')
        print(f'Wrote {out.relative_to(ROOT)}')

    readme = OUT_DIR / 'README.md'
    readme.write_text(
        '# BPMN-диаграммы (этап проектирования)\n\n'
        'Диаграммы процессов системы «Умный Коворкинг» в нотации BPMN.\n'
        'Описаны роли участников (клиент, менеджер, администратор, система) '
        'и логика процессов без привязки к реализации.\n\n'
        'Исходные диаграммы с деталями реализации сохранены в каталоге `docs/`.\n',
        encoding='utf-8',
    )
    print(f'Wrote {readme.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
