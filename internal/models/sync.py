"""Совместимость: см. internal.layout.sync."""
import internal.layout.sync as _sync

globals().update({name: getattr(_sync, name) for name in dir(_sync) if not name.startswith('__')})
