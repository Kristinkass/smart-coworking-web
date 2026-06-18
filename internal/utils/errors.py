"""Пользовательские сообщения об ошибках на русском."""
import re

from sqlalchemy.exc import IntegrityError

_CYRILLIC_RE = re.compile(r'[а-яА-ЯёЁ]')


def _has_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC_RE.search(text or ''))


def user_error_message(exc, fallback=None):
    """Преобразовать исключение в понятное сообщение на русском."""
    if fallback is None:
        fallback = 'Произошла ошибка. Попробуйте ещё раз или обратитесь к администратору.'

    if exc is None:
        return fallback

    msg = exc.strip() if isinstance(exc, str) else str(exc).strip()
    if not msg:
        return fallback

    if _has_cyrillic(msg):
        return msg

    lower = msg.lower()
    exc_type = type(exc).__name__.lower() if not isinstance(exc, str) else ''

    if isinstance(exc, IntegrityError) or 'integrityerror' in exc_type:
        if 'email' in lower:
            return 'Пользователь с таким email уже существует'
        if 'phone' in lower:
            return 'Пользователь с таким телефоном уже существует'
        return 'Запись с такими данными уже существует'

    rules = (
        (('unique constraint', 'already exists', 'duplicate key', 'unique failed'), 'Запись с такими данными уже существует'),
        (('users.email',), 'Пользователь с таким email уже существует'),
        (('users.phone',), 'Пользователь с таким телефоном уже существует'),
        (('not found',), 'Запись не найдена'),
        (('permission denied', 'forbidden', 'access denied'), 'Недостаточно прав'),
        (('unauthorized',), 'Требуется авторизация'),
        (('timeout',), 'Превышено время ожидания. Попробуйте ещё раз'),
        (('connection refused', 'connection error', 'network'), 'Ошибка соединения с сервером'),
        (('invalid',), 'Некорректные данные'),
        (('required', 'missing', 'not null'), 'Не заполнены обязательные поля'),
        (('placecategory', 'not defined'), 'Ошибка категории места. Перезапустите сервер и повторите'),
    )

    for keys, ru in rules:
        if any(key in lower for key in keys):
            return ru

    return fallback
