# Система управления рабочими местами в коворкинге

Веб-приложение для бронирования рабочих мест и переговорных.

**Стек:** Python 3.10+, Flask, PostgreSQL, SQLAlchemy. Геометрия этажей — в `static/layout.json`, бизнес-данные — в PostgreSQL.

## Требования

- Python 3.10+
- PostgreSQL 12+

## Быстрый старт (локально)

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Если PowerShell запрещает Activate.ps1, запускайте команды напрямую:
venv\Scripts\python.exe -m pip install -r requirements.txt

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

Скопируйте `.env.example` в `.env` и укажите параметры подключения к БД:

```env
SECRET_KEY=ваша_случайная_строка
DB_HOST=localhost
DB_USER=postgres
DB_PASSWORD=ваш_пароль
DB_NAME=coworking
DB_PORT=5432

ADMIN_EMAIL=admin@coworking.com
ADMIN_PASSWORD=ВашНадёжныйПароль
ADMIN_NAME=Администратор
```

Запуск:

```bash
python cmd/app/main.py
# Windows PowerShell без активации:
venv\Scripts\python.exe cmd\app\main.py
```

Приложение: http://127.0.0.1:5000

При первом запуске создаются таблицы, выполняются миграции и инициализируются начальные данные (включая администратора из `.env`).

## API-документация (Swagger)

| URL | Описание |
|-----|----------|
| http://127.0.0.1:5000/docs/ | Swagger UI |
| http://127.0.0.1:5000/openapi.json | OpenAPI 3.0 |

## Запуск через Docker (локально)

```bash
cp .env.example .env   # Windows: copy .env.example .env
docker compose up --build
```

Приложение: http://localhost:5000

Остановка: `docker compose down`

## Структура проекта

```text
cmd/app/main.py          — точка входа (dev)
wsgi.py                  — точка входа (production / Docker)
docker-entrypoint.sh     — ожидание PostgreSQL в Docker
internal/
  application.py         — фабрика Flask
  config.py              — настройки
  swagger/               — OpenAPI / Swagger UI
  handlers/              — HTTP-маршруты
  services/              — бизнес-логика
  repositories/          — доступ к PostgreSQL
  layout/                — карта (layout.json)
  models/                — ORM и миграции
static/                  — CSS, JS, layout.json
templates/               — HTML-шаблоны
```
