"""Совместимая точка входа (раньше запускали python app.py)."""
import os
import sys

os.environ.setdefault('PGCLIENTENCODING', 'UTF8')
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from internal.application import create_app
from internal.models import init_db

app = create_app()

if __name__ == '__main__':
    init_db(app)
    print('Система управления рабочими местами в коворкинге')
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
