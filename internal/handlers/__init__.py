"""HTTP handlers layer."""
from internal.handlers.admin.bookings import register_admin_booking_routes
from internal.handlers.admin.pages import register_admin_pages_routes
from internal.handlers.admin.places import register_admin_place_routes
from internal.handlers.admin.room import room_editor_bp
from internal.handlers.api.category import category_bp
from internal.handlers.api.hubs import register_module_hubs
from internal.handlers.api.location_zone import location_zone_bp
from internal.handlers.api.notification import register_notification_routes
from internal.handlers.api.report import register_report_routes
from internal.handlers.api.schedule import register_schedule_routes
from internal.handlers.api.subscription import register_subscription_routes
from internal.handlers.booking.api import booking_bp
from internal.handlers.booking.legacy import register_booking_legacy_routes
from internal.handlers.map.places import register_place_routes
from internal.handlers.web.auth import register_auth_routes
from internal.handlers.web.pages import register_pages_routes
from internal.handlers.web.user import register_user_routes


def register_all_handlers(app):
    """Register all handlers on the Flask app."""
    register_pages_routes(app)
    register_auth_routes(app)
    register_place_routes(app)
    register_booking_legacy_routes(app)
    register_user_routes(app)
    register_admin_pages_routes(app)
    register_admin_booking_routes(app)
    register_admin_place_routes(app)
    register_subscription_routes(app)
    register_notification_routes(app)
    register_report_routes(app)
    register_schedule_routes(app)
    app.register_blueprint(category_bp)
    app.register_blueprint(location_zone_bp)
    app.register_blueprint(room_editor_bp)
    app.register_blueprint(booking_bp)
    register_module_hubs(app)
