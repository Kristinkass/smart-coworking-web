"""Project root paths."""
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
STATIC_DIR = os.path.join(PROJECT_ROOT, 'static')
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, 'templates')
LAYOUT_PATH = os.environ.get('LAYOUT_PATH') or os.path.join(STATIC_DIR, 'layout.json')
