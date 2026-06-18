"""Общие зависимости HTTP-обработчиков."""
from internal import models
from internal.models import (
    Booking,
    Coworking,
    CoworkingSchedule,
    Notification,
    Place,
    Subscription,
    User,
    db,
)
from internal.repositories.booking_repository import BookingRepository
from internal.layout.repository import LayoutRepository
from internal.repositories.place_repository import PlaceRepository
from internal.repositories.user_repository import UserRepository
from internal.services import booking_legacy_service
from internal.utils.decorators import admin_required, manager_required, staff_required
from internal.utils.formatters import (
    format_duration,
    format_duration_mins,
    get_status_name,
    get_type_name,
    render_stars,
)

__all__ = [
    'models', 'db', 'Booking', 'Coworking', 'CoworkingSchedule', 'Notification', 'Place',
    'Subscription', 'User', 'BookingRepository', 'LayoutRepository',
    'PlaceRepository', 'UserRepository', 'booking_legacy_service',
    'admin_required', 'manager_required', 'staff_required', 'format_duration', 'format_duration_mins',
    'get_status_name', 'get_type_name', 'render_stars',
]
