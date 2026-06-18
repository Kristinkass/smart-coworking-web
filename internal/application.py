"""Flask application factory."""
import os
import sys

# Ensure project root is on sys.path when running as module
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, url_for
from flask_login import LoginManager

from internal.config import Config
from internal.handlers import register_all_handlers
from internal.models import User, db, init_db
from internal.utils.formatters import (
    format_booking_location,
    format_duration,
    format_duration_mins,
    format_money,
    format_place_code,
    format_place_container,
    format_place_full_code,
    get_status_name,
    get_type_name,
)
from internal.utils.phone import format_phone_display
from internal.utils.paths import PROJECT_ROOT as ROOT, STATIC_DIR, TEMPLATES_DIR

load_dotenv()


def create_app(config_class=Config):
    app = Flask(
        __name__,
        template_folder=TEMPLATES_DIR,
        static_folder=STATIC_DIR,
    )
    app.config.from_object(config_class)
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = 'Пожалуйста, войдите для доступа к этой странице'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'error': 'Требуется авторизация'}), 401
        return redirect(url_for('login', next=request.url))

    @app.context_processor
    def utility_processor():
        return {
            'get_type_name': get_type_name,
            'get_status_name': get_status_name,
            'format_duration': format_duration,
            'format_duration_mins': format_duration_mins,
            'format_booking_location': format_booking_location,
            'format_place_code': format_place_code,
            'format_place_container': format_place_container,
            'format_place_full_code': format_place_full_code,
            'format_money': format_money,
            'format_phone': format_phone_display,
        }

    app.add_template_global(format_phone_display, 'format_phone')
    app.add_template_global(format_booking_location, 'format_booking_location')
    app.add_template_global(format_place_code, 'format_place_code')
    app.add_template_global(format_place_container, 'format_place_container')
    app.add_template_global(format_place_full_code, 'format_place_full_code')
    app.add_template_global(format_money, 'format_money')

    register_all_handlers(app)
    from internal.swagger import register_swagger
    register_swagger(app)

    if not app.config.get('TESTING'):
        with app.app_context():
            from internal.models.seed import run_migrations
            run_migrations()

    return app
