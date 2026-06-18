"""Совместимость: см. internal.layout.store."""
import internal.layout.store as _store

globals().update({name: getattr(_store, name) for name in dir(_store) if not name.startswith('__')})
