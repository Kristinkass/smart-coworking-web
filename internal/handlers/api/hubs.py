"""Хабы четырёх функциональных модулей системы."""

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

space_bp = Blueprint('space_module', __name__, url_prefix='/modules/space')
booking_hub_bp = Blueprint('booking_module_hub', __name__, url_prefix='/modules/booking')
billing_bp = Blueprint('billing_module', __name__, url_prefix='/modules/billing')
reports_bp = Blueprint('reports_module', __name__, url_prefix='/modules/analytics')


def _deny(msg='Доступ запрещен'):
    flash(msg, 'error')
    return redirect(url_for('dashboard'))


@space_bp.route('/')
@login_required
def hub():
    if not (current_user.is_admin() or current_user.is_manager()):
        return _deny('Модуль пространства доступен администратору и менеджеру.')
    return render_template('admin/module_space.html')


@booking_hub_bp.route('/')
@login_required
def hub():
    if current_user.is_admin() or current_user.is_manager():
        return render_template('admin/module_booking.html')
    if current_user.is_client():
        return redirect(url_for('map_view'))
    return _deny()


@billing_bp.route('/')
@login_required
def hub():
    if current_user.is_admin() or current_user.is_manager() or current_user.is_client():
        return render_template('admin/module_billing.html')
    return _deny()


@reports_bp.route('/')
@login_required
def hub():
    if not current_user.is_admin():
        return _deny('Отчётность доступна только администратору.')
    return redirect(url_for('admin_dashboard'))


def register_module_hubs(app):
    app.register_blueprint(space_bp)
    app.register_blueprint(booking_hub_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(reports_bp)
