"""Сборка OpenAPI 3.0 из зарегистрированных Flask-маршрутов."""
from __future__ import annotations

import re
from typing import Any

from flask import Flask

FLASK_PATH_RE = re.compile(r'<(?:(\w+):)?([^>]+)>')

SKIP_ENDPOINTS = frozenset({'static', 'openapi_json', 'swagger_ui'})

TAG_DESCRIPTIONS = {
    'Auth': 'Вход, регистрация, выход',
    'Web': 'Публичные и пользовательские HTML-страницы',
    'Map': 'Карта мест и доступность',
    'Booking': 'Бронирование',
    'User': 'Профиль и действия клиента',
    'Notifications': 'Уведомления и обратная связь',
    'Subscriptions': 'Абонементы',
    'Admin API': 'REST API администратора',
    'Editor': 'Редактор планировки',
    'Admin Pages': 'HTML-страницы админ-панели',
    'Modules': 'Хабы функциональных модулей',
    'API': 'Прочие API',
}


def flask_rule_to_openapi(rule: str) -> str:
    return FLASK_PATH_RE.sub(lambda m: '{' + m.group(2) + '}', rule)


def _humanize_endpoint(endpoint: str) -> str:
    return endpoint.replace('_', ' ').strip().capitalize()


def infer_tag(path: str, endpoint: str) -> str:
    if path.startswith('/api/admin/editor') or path.startswith('/api/admin/room') or path.startswith('/api/admin/wall') or path.startswith('/api/admin/door'):
        return 'Editor'
    if path.startswith('/api/admin'):
        return 'Admin API'
    if (
        path.startswith('/api/booking')
        or path.startswith('/api/cancel_booking')
        or path.startswith('/api/extend_booking')
        or path.startswith('/api/check_booking')
        or path.startswith('/api/create_booking')
        or path.startswith('/api/subscription/book')
    ):
        return 'Booking'
    if path.startswith('/api/places') or path.startswith('/api/seat_occupancy') or path.startswith('/api/available_times'):
        return 'Map'
    if path.startswith('/api/notification') or path.startswith('/api/feedback'):
        return 'Notifications'
    if 'subscription' in path:
        return 'Subscriptions'
    if path.startswith('/api/user') or path.startswith('/api/my') or path in (
        '/api/update_profile',
        '/api/change_password',
        '/api/submit_rating',
        '/api/user_stats',
    ):
        return 'User'
    if path.startswith('/api/'):
        return 'API'
    if path.startswith('/admin') or path.startswith('/manager/'):
        return 'Admin Pages'
    if path.startswith('/modules/'):
        return 'Modules'
    if path in ('/login', '/register', '/logout', '/change-password'):
        return 'Auth'
    return 'Web'


def infer_security(path: str, methods: set[str]) -> list[dict[str, list]]:
    public_get = {
        '/',
        '/api/places',
        '/api/public/stats',
        '/api/subscription-templates',
    }
    if methods <= {'GET'} and (
        path in public_get
        or path.startswith('/api/booking/timegrid')
        or path.startswith('/api/seat_occupancy')
        or path.startswith('/api/available_times')
        or re.fullmatch(r'/api/places/\{place_id\}/tariffs', path)
    ):
        return []
    if path in ('/login', '/register') and 'POST' in methods:
        return []
    protected_prefixes = ('/api/', '/admin', '/manager/', '/modules/', '/dashboard', '/mapp', '/change-password')
    if any(path == p or path.startswith(p) for p in protected_prefixes):
        return [{'sessionCookie': []}]
    if 'POST' in methods or 'PUT' in methods or 'DELETE' in methods or 'PATCH' in methods:
        if path.startswith('/api/'):
            return [{'sessionCookie': []}]
    return []


def _json_response_schema() -> dict[str, Any]:
    return {
        '200': {
            'description': 'Успешный ответ (JSON)',
            'content': {
                'application/json': {
                    'schema': {'$ref': '#/components/schemas/SuccessResponse'},
                },
            },
        },
        '400': {
            'description': 'Ошибка валидации',
            'content': {
                'application/json': {
                    'schema': {'$ref': '#/components/schemas/ErrorResponse'},
                },
            },
        },
        '401': {'description': 'Требуется авторизация'},
        '403': {'description': 'Доступ запрещён'},
        '404': {'description': 'Не найдено'},
        '500': {'description': 'Внутренняя ошибка сервера'},
    }


def _default_responses(path: str, method: str) -> dict[str, Any]:
    if path.startswith('/api/'):
        return _json_response_schema()
    if method.upper() == 'GET':
        return {
            '200': {
                'description': 'HTML-страница',
                'content': {'text/html': {'schema': {'type': 'string'}}},
            },
        }
    return {
        '302': {'description': 'Редирект после действия'},
        '200': {'description': 'HTML-страница или редирект'},
    }


def _path_parameters(path: str) -> list[dict[str, Any]]:
    return [
        {
            'name': seg.strip('{}'),
            'in': 'path',
            'required': True,
            'schema': {'type': 'integer' if 'id' in seg else 'string'},
        }
        for seg in re.findall(r'\{[^}]+\}', path)
    ]


def _request_body(path: str, method: str) -> dict[str, Any] | None:
    if method.upper() not in ('POST', 'PUT', 'PATCH'):
        return None
    if path.startswith('/api/'):
        return {
            'required': method.upper() in ('POST', 'PUT'),
            'content': {
                'application/json': {
                    'schema': {'type': 'object', 'additionalProperties': True},
                },
            },
        }
    if path.startswith('/admin') or path.startswith('/manager'):
        return {
            'required': True,
            'content': {
                'application/x-www-form-urlencoded': {
                    'schema': {'type': 'object', 'additionalProperties': True},
                },
            },
        }
    return None


def _merge_operation(path: str, method: str, endpoint: str, view_func) -> dict[str, Any]:
    doc = (view_func.__doc__ or '').strip() if view_func else ''
    tag = infer_tag(path, endpoint)
    operation: dict[str, Any] = {
        'summary': doc.split('\n')[0] if doc else _humanize_endpoint(endpoint),
        'tags': [tag],
        'operationId': f'{endpoint}_{method.lower()}',
        'responses': _default_responses(path, method),
    }
    if doc and '\n' in doc:
        operation['description'] = doc

    if method.upper() == 'GET' and '{' in path:
        operation['parameters'] = _path_parameters(path)

    body = _request_body(path, method)
    if body:
        operation['requestBody'] = body

    security = infer_security(path, {method.upper()})
    if security:
        operation['security'] = security

    return operation


def build_openapi_spec(app: Flask) -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}

    for rule in app.url_map.iter_rules():
        if rule.endpoint in SKIP_ENDPOINTS:
            continue
        openapi_path = flask_rule_to_openapi(rule.rule)
        if openapi_path.startswith('/openapi') or openapi_path.startswith('/docs'):
            continue

        path_item = paths.setdefault(openapi_path, {})
        methods = sorted(m for m in rule.methods if m not in ('HEAD', 'OPTIONS'))

        for method in methods:
            view_func = app.view_functions.get(rule.endpoint)
            path_item[method.lower()] = _merge_operation(
                openapi_path, method, rule.endpoint, view_func,
            )

    tags = sorted({op['tags'][0] for item in paths.values() for op in item.values()})
    tag_objects = [{'name': t, 'description': TAG_DESCRIPTIONS.get(t, '')} for t in tags]

    return {
        'openapi': '3.0.3',
        'info': {
            'title': 'Система управления рабочими местами',
            'description': (
                'HTTP API веб-приложения коворкинга. '
                'Авторизация — сессионная cookie Flask-Login (`session`). '
                'Для защищённых эндпоинтов сначала выполните вход через `/login`.'
            ),
            'version': '1.0.0',
        },
        'servers': [{'url': '/', 'description': 'Текущий хост'}],
        'tags': tag_objects,
        'paths': dict(sorted(paths.items())),
        'components': {
            'securitySchemes': {
                'sessionCookie': {
                    'type': 'apiKey',
                    'in': 'cookie',
                    'name': 'session',
                    'description': 'Сессия после успешного входа (Flask-Login)',
                },
            },
            'schemas': {
                'SuccessResponse': {
                    'type': 'object',
                    'properties': {
                        'success': {'type': 'boolean', 'example': True},
                        'data': {'type': 'object'},
                    },
                },
                'ErrorResponse': {
                    'type': 'object',
                    'properties': {
                        'success': {'type': 'boolean', 'example': False},
                        'error': {'type': 'string'},
                    },
                },
            },
        },
    }
