"""User data access."""
from datetime import date

from internal.models import Subscription, User, db


class UserRepository:
    @staticmethod
    def get_by_id(user_id):
        return User.query.get(user_id)

    @staticmethod
    def get_or_404(user_id):
        return User.query.get_or_404(user_id)

    @staticmethod
    def get_by_phone(phone):
        from internal.utils.phone import normalize_phone
        norm = normalize_phone(phone)
        if not norm:
            return None
        return User.query.filter_by(phone=norm).first()

    @staticmethod
    def get_by_email(email):
        if not email:
            return None
        return User.query.filter_by(email=email.strip().lower()).first()

    @staticmethod
    def get_for_login(login_mode, identifier):
        """Поиск пользователя для входа: login_mode = email | phone."""
        from internal.utils.phone import normalize_phone

        if login_mode == 'phone':
            phone = normalize_phone(identifier)
            if not phone:
                return None
            return UserRepository.get_by_phone(phone)
        email = (identifier or '').strip().lower()
        if not email:
            return None
        return UserRepository.get_by_email(email)

    @staticmethod
    def save(user):
        db.session.add(user)
        db.session.commit()
        return user

    @staticmethod
    def sync_visitor_kind(user):
        """tariff — оплата по тарифам; subscription — действующий абонемент."""
        if not user:
            return
        today = date.today()
        has_valid = Subscription.query.filter(
            Subscription.user_id == user.id,
            Subscription.active == True,
            Subscription.start_date <= today,
            Subscription.end_date >= today,
        ).first()
        if has_valid and has_valid.is_valid():
            user.visitor_kind = 'subscription'
        else:
            user.visitor_kind = 'tariff'
