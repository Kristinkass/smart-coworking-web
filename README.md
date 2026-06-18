# Система управления рабочими местами в коворкинге

Веб-приложение для бронирования рабочих мест и переговорных.

**Стек:** Python 3.10+, Flask, PostgreSQL, SQLAlchemy. Геометрия этажей — в `static/layout.json`, бизнес-данные — в PostgreSQL.

## Требования

- Python 3.10+
- PostgreSQL 12+
- Git

## Быстрый старт (локально)

```bash
git clone <url-репозитория>
cd <папка-проекта>

python -m venv venv

# Windows
venv\Scripts\activate

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

Запуск в режиме разработки:

```bash
python cmd/app/main.py
```

Приложение: http://127.0.0.1:5000

При первом запуске создаются таблицы, выполняются миграции и инициализируются начальные данные (включая администратора из `.env`).


## Запуск через Docker

```bash
# Скопируйте и настройте переменные
cp .env.example .env

# Сборка и запуск (приложение + PostgreSQL)
docker compose up --build
```

Для Docker **обязательны** в корне проекта: `Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh`, `wsgi.py`, `requirements.txt`, папки `internal/`, `static/`, `templates/`. Папки `docs/`, `tests/`, `scripts/generate_*.py` для запуска **не нужны** — их можно не копировать в «лёгкую» версию для деплоя.

Приложение: http://localhost:5000  
Swagger: http://localhost:5000/docs/

Остановка:

```bash
docker compose down
```

Данные PostgreSQL сохраняются в Docker volume `pgdata`.

## Структура проекта

```text
cmd/app/main.py          — точка входа (dev)
wsgi.py                  — точка входа (production / Docker)
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
Dockerfile
docker-compose.yml
```

## Production (без Docker)

```bash
pip install -r requirements.txt
# задайте переменные окружения или .env
waitress-serve --host=0.0.0.0 --port=5000 wsgi:app
```

## Публикация на GitHub

Проект большой (код + `docs/` с диаграммами и документами), но в git попадает только нужное: `.gitignore` исключает `venv/`, `.env`, кэши и локальные файлы.

### Вариант 1: GitHub Desktop (проще)

1. Установите [GitHub Desktop](https://desktop.github.com/).
2. **File → Add local repository** → выберите папку `smart-coworking`.
3. Если git ещё не инициализирован — Desktop предложит создать репозиторий.
4. На [github.com](https://github.com) нажмите **New repository**, имя например `smart-coworking`, **без** README (он уже есть локально).
5. В Desktop: **Publish repository** → выберите созданный репозиторий → **Publish**.
6. Дальше: правки → галочки у файлов слева → Summary → **Commit** → **Push origin**.

**Не коммитьте:** `.env` (пароли), папку `venv/`, файлы из `instance/`.

### Вариант 2: командная строка

```powershell
cd C:\Users\user\PycharmProjects\smart-coworking

# один раз: имя и email (локально для этого репозитория)
git config user.name "Ваше Имя"
git config user.email "ваш@email.com"

# посмотреть, что попадёт в коммит
git status

# добавить всё, кроме того что в .gitignore
git add .

# первый коммит
git commit -m "Первоначальная версия системы управления коворкингом"

# создайте пустой репозиторий на github.com, затем:
git remote add origin https://github.com/ВАШ_ЛОГИН/smart-coworking.git
git branch -M main
git push -u origin main
```

При `git push` GitHub попросит войти (браузер или [Personal Access Token](https://github.com/settings/tokens) вместо пароля).

### Если push долгий или падает

- Убедитесь, что не добавили `venv/` (`git status` не должен показывать тысячи файлов из venv).
- Крупные `.docx` в `docs/` можно оставить — обычно это 5–20 МБ, GitHub принимает до 100 МБ на файл.
- Файлы **больше 100 МБ** — используйте [Git LFS](https://git-lfs.com/) или не включайте их в репозиторий.

### Клонирование на другом компьютере

```bash
git clone https://github.com/ВАШ_ЛОГИН/smart-coworking.git
cd smart-coworking
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env         # и заполните пароль БД
python cmd/app/main.py
```
