"""
Модель данных: Coworking → Floor → Location → Place.
Геометрия карты — в internal/layout/ и static/layout.json.
"""
import importlib


def _export(module: str, *names: str) -> None:
    mod = importlib.import_module(f'internal.models.{module}')
    for name in names:
        globals()[name] = getattr(mod, name)


_export('db', 'db')

# ORM
_export('coworking', 'Coworking', 'Floor', 'Location')
_export('user', 'User')
_export('category', 'PlaceCategory', 'CategoryTariff')
_export('schedule', 'CoworkingSchedule')
_export('place', 'Place')
_export('booking', 'Booking', 'Rating')
_export('subscription', 'Subscription')
_export('notification', 'Notification')

# layout.json
_export(
    'layout',
    'load_layout', 'reload_layout', 'get_place_geometry', 'get_layout_place_meta',
    'migrate_rooms_to_spaces_in_layout', 'save_place_geometry', 'add_place_to_layout',
    'remove_place_from_layout', 'save_place_category_in_layout', 'save_place_zone_in_layout',
    'resize_place', 'rotate_place', 'load_walls', 'save_walls', 'add_wall', 'delete_wall',
    'load_doors', 'save_doors', 'add_door', 'move_door', 'move_wall', 'delete_door',
    'sync_wall_bound_places', 'move_container_with_children', 'create_walls_around_rect',
)

# Геометрия карты
_export(
    'geometry',
    'CANVAS_WIDTH', 'CANVAS_HEIGHT', 'rect_overlaps_walls', 'adjust_rect_from_walls',
    'clamp_rect_to_floor', 'clamp_rect_in_parent', 'validate_place_rect',
    'project_layout_positions', 'find_place_overlap',
    'fit_open_zone_bounds', 'desks_overlap_each_other', 'nudge_desks_from_walls',
    'zone_overlaps_other_desks', 'OPEN_ZONE_PAD',
)

# Синхронизация БД ↔ layout.json
_export(
    'sync',
    'infer_floor_from_location_code', 'FLOOR_DEFAULT_LOCATION', 'default_location_code_for_floor',
    'sync_place_locations_from_layout', 'sync_location_floors_from_layout',
    'ensure_place_parent_links', 'wrap_orphan_desks_in_open_spaces',
    'create_open_zone_from_desks',
    'sync_place_parents_from_layout', 'sync_place_by_code', 'resolve_place_id',
    'generate_place_code', 'apply_place_location_zone', 'auto_detect_place_parents_in_layout',
    'sync_parent_ids_from_layout', 'migrate_legacy_place_codes', 'place_allows_child_desks',
    'place_allows_layout_items', 'rename_place_code', 'desk_partial_open_zone_overlap',
)

# Зоны локаций (A/B/C)
_export(
    'location_zone',
    'LocationZoneType', 'build_location_prefix', 'ensure_default_zone_types',
    'ensure_location_for_zone', 'parse_location_prefix',
)

# Инициализация и миграции
_export('seed', 'init_default_data', 'update_booking_statuses', 'run_migrations', 'init_db')

__all__ = [name for name in globals() if not name.startswith('_')]
