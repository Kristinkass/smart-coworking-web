"""Совместимость: см. internal.layout.geometry."""
import internal.layout.geometry as _geometry

globals().update({name: getattr(_geometry, name) for name in dir(_geometry) if not name.startswith('__')})
