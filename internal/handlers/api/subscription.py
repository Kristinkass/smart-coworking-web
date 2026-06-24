"""Subscription API."""
import json
from datetime import date, datetime, timedelta

from flask import jsonify, request
from flask_login import current_user, login_required

from internal.handlers.deps import Subscription, User, admin_required, db, models, staff_required
from internal.repositories.user_repository import UserRepository
from internal.utils.errors import user_error_message


def _parse_place_kinds(data):
    kinds = data.get('place_kinds') or []
    if isinstance(kinds, str):
        kinds = json.loads(kinds)
    return kinds


def register_subscription_routes(app):
    @app.route('/api/admin/subscriptions', methods=['GET'])
    @staff_required
    def get_subscriptions():
        """Абонементы пользователей (без шаблонов)."""
        try:
            subs = models.Subscription.query.filter_by(is_template=False).all()
            return jsonify({'subscriptions': [sub.to_dict() for sub in subs]})
        except Exception as e:
            return jsonify({'error': user_error_message(e)}), 500

    @app.route('/api/admin/subscription-templates', methods=['GET'])
    @admin_required
    def get_subscription_templates_admin():
        try:
            templates = models.Subscription.query.filter_by(is_template=True).order_by(
                models.Subscription.price,
            ).all()
            return jsonify({'templates': [t.to_dict() for t in templates]})
        except Exception as e:
            return jsonify({'error': user_error_message(e)}), 500

    @app.route('/api/subscription-templates', methods=['GET'])
    @login_required
    def get_subscription_templates_public():
        """Шаблоны абонементов для оформления в личном кабинете."""
        try:
            templates = models.Subscription.query.filter_by(
                is_template=True, active=True,
            ).order_by(models.Subscription.price).all()
            return jsonify({'success': True, 'templates': [t.to_dict() for t in templates]})
        except Exception as e:
            return jsonify({'success': False, 'error': user_error_message(e)}), 500

    @app.route('/api/staff/users/<int:user_id>/subscriptions', methods=['GET'])
    @staff_required
    def get_client_subscriptions_for_booking(user_id):
        """Активные абонементы клиента – для оформления брони менеджером/админом."""
        try:
            user = UserRepository.get_by_id(user_id)
            if not user or user.role != 'client':
                return jsonify({'success': False, 'error': 'Клиент не найден'}), 404
            now = datetime.now().date()
            subs = models.Subscription.query.filter(
                models.Subscription.user_id == user_id,
                models.Subscription.is_template == False,
                models.Subscription.active == True,
                models.Subscription.start_date <= now,
                models.Subscription.end_date >= now,
            ).all()
            return jsonify({'success': True, 'subscriptions': [s.to_dict() for s in subs]})
        except Exception as e:
            return jsonify({'success': False, 'error': user_error_message(e)}), 500

    @app.route('/api/admin/subscriptions/<int:user_id>', methods=['GET'])
    @admin_required
    def get_user_subscriptions(user_id):
        try:
            subs = Subscription.query.filter_by(user_id=user_id, is_template=False).all()
            return jsonify({'subscriptions': [sub.to_dict() for sub in subs]})
        except Exception as e:
            return jsonify({'error': user_error_message(e)}), 500

    @app.route('/api/admin/subscriptions/issue-template', methods=['POST'])
    @staff_required
    def issue_subscription_from_template():
        """Выдать клиенту абонемент по шаблону (менеджер или администратор)."""
        try:
            data = request.json or {}
            user_id = data.get('user_id')
            template_id = data.get('template_id')
            if not user_id or not template_id:
                return jsonify({'error': 'Укажите пользователя и шаблон'}), 400

            user = UserRepository.get_by_id(int(user_id))
            if not user:
                return jsonify({'error': 'Пользователь не найден'}), 404
            if user.role != 'client':
                return jsonify({'error': 'Абонемент можно выдать только клиенту'}), 400

            template = models.Subscription.query.filter_by(
                id=int(template_id), is_template=True, active=True,
            ).first()
            if not template:
                return jsonify({
                    'error': 'Шаблон не найден или в архиве – выдача недоступна',
                }), 404

            duration = template.duration_days or max(
                1, (template.end_date - template.start_date).days,
            )
            start = date.today()
            end = start + timedelta(days=duration)
            subscription = models.Subscription(
                user_id=user.id,
                name=template.name,
                place_kinds=template.place_kinds,
                start_date=start,
                end_date=end,
                hours_limit=template.hours_limit,
                hours_used=0,
                price=template.price,
                active=True,
                is_template=False,
            )
            db.session.add(subscription)
            db.session.flush()
            UserRepository.sync_visitor_kind(user)
            db.session.commit()
            return jsonify({'success': True, 'subscription': subscription.to_dict()}), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': user_error_message(e)}), 500

    @app.route('/api/admin/subscriptions', methods=['POST'])
    @admin_required
    def create_subscription():
        """Устарело: используйте issue-template."""
        return jsonify({
            'error': 'Индивидуальное создание отключено. Выдайте абонемент по шаблону.',
        }), 400

    @app.route('/api/admin/subscription-templates', methods=['POST'])
    @admin_required
    def create_subscription_template():
        """Создать шаблон абонемента."""
        try:
            data = request.json
            duration_days = int(data.get('duration_days') or 30)
            today = date.today()
            subscription = models.Subscription(
                user_id=None,
                name=data['name'],
                place_kinds=json.dumps(_parse_place_kinds(data)),
                start_date=today,
                end_date=today + timedelta(days=duration_days),
                hours_limit=data.get('hours_limit'),
                hours_used=0,
                price=data['price'],
                active=True,
                is_template=True,
                duration_days=duration_days,
            )
            db.session.add(subscription)
            db.session.commit()
            return jsonify({'success': True, 'template': subscription.to_dict()}), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': user_error_message(e)}), 500

    @app.route('/api/admin/subscriptions/<int:subscription_id>', methods=['PUT'])
    @admin_required
    def update_subscription(subscription_id):
        try:
            data = request.json
            subscription = Subscription.query.get_or_404(subscription_id)
            if subscription.is_template:
                return jsonify({'error': 'Используйте API шаблонов'}), 400
            if 'name' in data:
                subscription.name = data['name']
            if 'place_kinds' in data:
                subscription.place_kinds = json.dumps(_parse_place_kinds(data))
            if 'start_date' in data:
                subscription.start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
            if 'end_date' in data:
                subscription.end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            if 'hours_limit' in data:
                subscription.hours_limit = data['hours_limit']
            if 'price' in data:
                subscription.price = data['price']
            if 'active' in data:
                subscription.active = data['active']
            db.session.flush()
            if subscription.user_id:
                user = UserRepository.get_by_id(subscription.user_id)
                if user:
                    UserRepository.sync_visitor_kind(user)
            db.session.commit()
            return jsonify({'success': True, 'subscription': subscription.to_dict()})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': user_error_message(e)}), 500

    @app.route('/api/admin/subscription-templates/<int:template_id>', methods=['PUT'])
    @admin_required
    def update_subscription_template(template_id):
        try:
            data = request.json
            template = Subscription.query.filter_by(id=template_id, is_template=True).first_or_404()
            if 'name' in data:
                template.name = data['name']
            if 'place_kinds' in data:
                template.place_kinds = json.dumps(_parse_place_kinds(data))
            if 'duration_days' in data:
                template.duration_days = int(data['duration_days'])
                template.end_date = template.start_date + timedelta(days=template.duration_days)
            if 'hours_limit' in data:
                template.hours_limit = data['hours_limit']
            if 'price' in data:
                template.price = data['price']
            if 'active' in data:
                template.active = data['active']
            db.session.commit()
            return jsonify({'success': True, 'template': template.to_dict()})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': user_error_message(e)}), 500

    @app.route('/api/user/subscriptions/purchase', methods=['POST'])
    @login_required
    def purchase_subscription():
        """Оформить абонемент по шаблону."""
        try:
            data = request.json or {}
            template_id = data.get('template_id')
            if not template_id:
                return jsonify({'success': False, 'error': 'Укажите шаблон'}), 400

            template = Subscription.query.filter_by(
                id=template_id, is_template=True, active=True,
            ).first()
            if not template:
                return jsonify({
                    'success': False,
                    'error': 'Шаблон не найден или в архиве – оформление недоступно',
                }), 404

            duration = template.duration_days or max(
                1, (template.end_date - template.start_date).days,
            )
            start = date.today()
            end = start + timedelta(days=duration)

            subscription = models.Subscription(
                user_id=current_user.id,
                name=template.name,
                place_kinds=template.place_kinds,
                start_date=start,
                end_date=end,
                hours_limit=template.hours_limit,
                hours_used=0,
                price=template.price,
                active=True,
                is_template=False,
                duration_days=None,
            )
            db.session.add(subscription)
            db.session.flush()
            UserRepository.sync_visitor_kind(current_user)
            db.session.commit()
            return jsonify({'success': True, 'subscription': subscription.to_dict()})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': user_error_message(e)}), 500

    @app.route('/api/user/subscriptions', methods=['GET'])
    @login_required
    def get_my_subscriptions():
        try:
            subs = models.Subscription.query.filter_by(
                user_id=current_user.id, is_template=False,
            ).all()
            return jsonify({'subscriptions': [sub.to_dict() for sub in subs]})
        except Exception as e:
            return jsonify({'error': user_error_message(e)}), 500

    @app.route('/api/my/subscriptions', methods=['GET'])
    @login_required
    def api_my_subscriptions():
        try:
            now = datetime.now().date()
            subs = models.Subscription.query.filter(
                models.Subscription.user_id == current_user.id,
                models.Subscription.is_template == False,
                models.Subscription.active == True,
                models.Subscription.start_date <= now,
                models.Subscription.end_date >= now,
            ).all()
            return jsonify({'success': True, 'subscriptions': [s.to_dict() for s in subs]})
        except Exception as e:
            return jsonify({'success': False, 'error': user_error_message(e)}), 500
