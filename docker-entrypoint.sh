#!/bin/sh
set -e

echo "Ожидание PostgreSQL (${DB_HOST:-db})..."

python <<'PY'
import os
import sys
import time

import psycopg2

host = os.environ.get("DB_HOST", "db")
user = os.environ.get("DB_USER", "postgres")
password = os.environ.get("DB_PASSWORD", "")
port = os.environ.get("DB_PORT", "5432")

for attempt in range(60):
    try:
        psycopg2.connect(
            host=host,
            user=user,
            password=password,
            port=port,
            dbname="postgres",
            connect_timeout=3,
        ).close()
        print("PostgreSQL доступен")
        break
    except psycopg2.Error as exc:
        if attempt == 59:
            print(f"PostgreSQL недоступен: {exc}", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
PY

if [ -n "$LAYOUT_PATH" ] && [ ! -f "$LAYOUT_PATH" ]; then
    echo "Инициализация layout.json: $LAYOUT_PATH"
    mkdir -p "$(dirname "$LAYOUT_PATH")"
    cp /app/static/layout.json "$LAYOUT_PATH"
fi

echo "Инициализация БД..."
python -u <<'PY' || exit 1
import sys
try:
    from wsgi import app
    from internal.models import init_db
    init_db(app)
    print("Инициализация БД завершена", flush=True)
except Exception as exc:
    print(f"Ошибка инициализации БД: {exc}", file=sys.stderr, flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)
PY

echo "Запуск приложения..."
exec "$@"
