"""User model."""
from datetime import datetime

from flask_login import UserMixin
from sqlalchemy.orm import synonym
from werkzeug.security import check_password_hash, generate_password_hash

from internal.models.db import db

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id_user = db.Column(db.Integer, primary_key=True)
    id = synonym('id_user')
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    username = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=True, index=True)
    # admin | manager | client
    role = db.Column(db.String(20), default='client')
    # Только для client: tariff (по тарифам) | subscription (по абонементу)
    visitor_kind = db.Column(db.String(20), default='tariff')
    active = db.Column(db.Boolean, default=True)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    issued_temp_password = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == 'admin'

    def is_manager(self):
        return self.role == 'manager'

    def is_visitor(self):
        return self.role == 'client'

    @property
    def is_active(self):
        """Flask-Login и шаблоны: статус учётной записи."""
        return bool(self.active)

    @property
    def login_label(self):
        """Отображаемый идентификатор: телефон, иначе почта или имя."""
        from internal.utils.phone import format_phone_display
        if self.phone:
            return format_phone_display(self.phone)
        if self.email:
            return self.email
        return self.username

    def to_dict(self):
        return {
            'id': self.id_user,
            'email': self.email,
            'phone': self.phone,
            'username': self.username,
            'role': self.role,
            'visitor_kind': self.visitor_kind,
            'login_label': self.login_label,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<User {self.login_label} ({self.role})>'
