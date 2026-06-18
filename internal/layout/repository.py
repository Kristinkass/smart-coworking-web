"""Layout.json persistence."""
from internal.layout import store as layout_store


class LayoutRepository:
    @staticmethod
    def load():
        return layout_store.load_layout()

    @staticmethod
    def reload():
        return layout_store.reload_layout()

    @staticmethod
    def get_place_geometry(code):
        return layout_store.get_place_geometry(code)

    @staticmethod
    def save_place_geometry(code, x, y, floor=None):
        return layout_store.save_place_geometry(code, x, y, floor=floor)

    @staticmethod
    def add_place(place_dict):
        return layout_store.add_place_to_layout(place_dict)

    @staticmethod
    def remove_place(code):
        return layout_store.remove_place_from_layout(code)

    @staticmethod
    def save_place_category(code, category_id):
        return layout_store.save_place_category_in_layout(code, category_id)

    @staticmethod
    def load_walls():
        return layout_store.load_walls()

    @staticmethod
    def load_doors():
        return layout_store.load_doors()

    @staticmethod
    def add_wall(x1, y1, x2, y2, floor=1):
        return layout_store.add_wall(x1, y1, x2, y2, floor=floor)

    @staticmethod
    def delete_wall(wall_id):
        return layout_store.delete_wall(wall_id)

    @staticmethod
    def add_door(wall_id, position, floor=1, width=100):
        return layout_store.add_door(wall_id, position, floor=floor, width=width)

    @staticmethod
    def delete_door(door_id):
        return layout_store.delete_door(door_id)

    @staticmethod
    def move_door(door_id, wall_id=None, position=None, width=None):
        return layout_store.move_door(door_id, wall_id, position, width)

    @staticmethod
    def move_wall(wall_id, x1, y1, x2, y2):
        return layout_store.move_wall(wall_id, x1, y1, x2, y2)

    @staticmethod
    def resize_place(code, width, height):
        return layout_store.resize_place(code, width, height)

    @staticmethod
    def rotate_place(code, rotation):
        return layout_store.rotate_place(code, rotation)
