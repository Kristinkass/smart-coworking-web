"""Точка входа WSGI для Waitress (Windows) и Gunicorn (Linux)."""
import os
import sys

os.environ.setdefault('PGCLIENTENCODING', 'UTF8')
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from internal.application import create_app
from internal.models import init_db

app = create_app()
init_db(app)
