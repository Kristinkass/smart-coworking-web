"""Authentication pages and forms."""
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from internal.handlers.deps import User, UserRepository, db, models
from internal.utils.errors import user_error_message
from internal.utils.phone import normalize_phone


def register_auth_routes(app):
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))

        login_mode = request.form.get('login_mode', 'email') if request.method == 'POST' else 'email'

        if request.method == 'POST':
            identifier = (
                request.form.get('identifier')
                or request.form.get('email')
                or ''
            ).strip()
            password = request.form.get('password')
            remember = True if request.form.get('remember') else False
            login_mode = request.form.get('login_mode', 'email')

            if login_mode == 'phone':
                phone = normalize_phone(identifier)
                if not phone:
                    flash('Введите корректный номер телефона', 'error')
                    return redirect(url_for('login', mode='phone'))
                user = UserRepository.get_for_login('phone', phone)
                invalid_msg = 'Неверный телефон или пароль. Попробуйте снова.'
            else:
                email = identifier.lower()
                if '@' not in email or '.' not in email.split('@')[-1]:
                    flash('Введите корректный email (должен содержать @ и домен)', 'error')
                    return redirect(url_for('login', mode='email'))
                user = UserRepository.get_for_login('email', email)
                invalid_msg = 'Неверный email или пароль. Попробуйте снова.'

            if user and user.check_password(password):
                if not user.active:
                    flash('Ваш аккаунт деактивирован. Свяжитесь с администратором.', 'error')
                    return redirect(url_for('login', mode=login_mode))

                login_user(user, remember=remember)
                user.last_login = datetime.utcnow()
                if user.is_visitor():
                    UserRepository.sync_visitor_kind(user)
                db.session.commit()

                flash(f'Добро пожаловать, {user.username}!', 'success')

                if user.is_admin():
                    return redirect(url_for('admin_dashboard'))
                return redirect(url_for('dashboard'))

            flash(invalid_msg, 'error')
            return redirect(url_for('login', mode=login_mode))

        mode = request.args.get('mode', login_mode)
        if mode not in ('email', 'phone'):
            mode = 'email'
        return render_template('login.html', login_mode=mode)

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))

        if request.method == 'POST':
            username = (request.form.get('username') or '').strip()
            password = request.form.get('password')
            phone = normalize_phone(request.form.get('phone'))

            if not username or not password or not phone:
                flash('Укажите имя, телефон и пароль', 'error')
                return redirect(url_for('register'))

            if UserRepository.get_by_phone(phone):
                flash('Пользователь с таким телефоном уже существует', 'error')
                return redirect(url_for('register'))

            email = (request.form.get('email') or '').strip().lower() or None
            if email:
                if '@' not in email or '.' not in email.split('@')[-1]:
                    flash('Введите корректный email (должен содержать @ и домен)', 'error')
                    return redirect(url_for('register'))
                if UserRepository.get_by_email(email):
                    flash('Пользователь с таким email уже существует', 'error')
                    return redirect(url_for('register'))

            user = models.User(
                email=email,
                username=username,
                phone=phone,
                active=True
            )
            user.set_password(password)

            try:
                db.session.add(user)
                db.session.commit()

                flash('Регистрация успешна! Теперь вы можете войти.', 'success')
                return redirect(url_for('login'))
            except IntegrityError:
                db.session.rollback()
                flash('Пользователь с таким email или телефоном уже существует', 'error')
            except Exception as e:
                db.session.rollback()
                flash(f'Ошибка при регистрации: {user_error_message(e)}', 'error')

        return render_template('register.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('Вы успешно вышли из системы', 'success')
        return redirect(url_for('index'))

    @app.route('/change-password')
    @login_required
    def change_password_page():
        """Страница смены пароля."""
        return render_template('change_password.html')
