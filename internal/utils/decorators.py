"""HTTP access decorators."""
from functools import wraps

from flask import flash, redirect, url_for
from flask_login import current_user, login_required


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Доступ запрещен. Требуются права администратора.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def staff_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not (current_user.is_admin() or current_user.is_manager()):
            flash('Доступ запрещен. Требуются права администратора или менеджера.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def manager_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_manager():
            flash('Доступ запрещен. Требуются права менеджера.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function
