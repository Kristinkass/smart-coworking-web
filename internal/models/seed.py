"""DB seeding, migrations and init."""
import json
from datetime import date, datetime, timedelta

from sqlalchemy import inspect, text

from internal.models.db import db
from internal.models.layout import load_layout
from internal.models.coworking import Coworking, Floor, Location
from internal.models.category import CategoryTariff, PlaceCategory
from internal.models.place import Place
from internal.models.user import User
from internal.models.schedule import CoworkingSchedule
from internal.models.booking import Booking
from internal.models.subscription import Subscription
from internal.models.location_zone import (
    LocationZoneType,
    ensure_default_zone_types,
    ensure_location_for_zone,
    layout_place_belongs_in_db,
    place_is_amenity,
)
from internal.models.sync import (
    infer_floor_from_location_code,
    migrate_legacy_place_codes,
    sync_location_floors_from_layout,
    sync_place_locations_from_layout,
    sync_place_parents_from_layout,
)


def purge_amenity_places():
    """Удалить служебные зоны из places — они живут только в locations + layout.json."""
    removed = 0
    for place in Place.query.filter(Place.kind.in_(('space', 'room'))).all():
        if not place_is_amenity(place):
            continue
        Booking.query.filter_by(place_id=place.id).delete()
        db.session.delete(place)
        removed += 1
    if removed:
        db.session.commit()
        print(f'[OK] Удалено служебных зон из places: {removed}')
    return removed


def init_default_data():
    """
    Инициализация начальных данных для первого запуска на предприятии.
    Создаёт структуру коворкинга, категории мест с тарифами, рабочие места
    из layout.json и первого администратора (из переменных окружения .env).
    Демо-пользователи не создаются.
    """
    import os
    print("Инициализация данных...")
    try:
        layout = load_layout()

        # 1. Коворкинг + этажи
        cw = Coworking.ensure_singleton()
        if Floor.query.filter_by(coworking_id=cw.id).count() == 0:
            for fl_data in layout.get('floors', []):
                db.session.add(Floor(
                    coworking_id=cw.id,
                    number=fl_data['number'],
                    name=fl_data['name'],
                ))
            db.session.commit()
            print(f"[OK] Этажей создано: {len(layout.get('floors', []))}")
        else:
            print(f"[OK] Коворкинг: {cw.name} · этажей: {Floor.query.filter_by(coworking_id=cw.id).count()}")

        # 2. Локации из типов зон
        ensure_default_zone_types()
        for fl in Floor.query.all():
            for zt in LocationZoneType.query.filter_by(active=True).all():
                ensure_location_for_zone(fl.number, zt.id)
        db.session.commit()
        sync_location_floors_from_layout()
        print(f"[OK] Локации: {Location.query.count()}")

        # 3. Категории мест и тарифы (начальные значения, администратор может изменить)
        default_categories = [
            {'name': 'Стол складной (1 место)', 'kind': 'desk', 'capacity': 1, 'width_m': 0.5, 'height_m': 0.75},
            {'name': 'Стол на 2 места',          'kind': 'desk', 'capacity': 2, 'width_m': 1.0, 'height_m': 0.75},
            {'name': 'Стол на 4 места',          'kind': 'desk', 'capacity': 4, 'width_m': 1.2, 'height_m': 1.0},
            {'name': 'Стол на 6 мест',           'kind': 'desk', 'capacity': 6, 'width_m': 1.8, 'height_m': 1.0},
            {'name': 'Стол на 8 мест',           'kind': 'desk', 'capacity': 8, 'width_m': 2.5, 'height_m': 1.2},
            {'name': 'Переговорная 10 мест',     'kind': 'room', 'capacity': 10, 'width_m': 3.5, 'height_m': 2.0},
            {'name': 'Переговорная 14 мест',     'kind': 'room', 'capacity': 14, 'width_m': 4.5, 'height_m': 2.5},
            {'name': 'Переговорная 20 мест',     'kind': 'room', 'capacity': 20, 'width_m': 6.0, 'height_m': 3.0},
        ]
        default_tariffs = {
            'Стол складной (1 место)': {'hourly': 250.0, 'weekly': 3500.0,  'monthly': 12000.0},
            'Стол на 2 места':         {'hourly': 450.0, 'weekly': 6000.0,  'monthly': 20000.0},
            'Стол на 4 места':         {'hourly': 800.0, 'weekly': 10000.0, 'monthly': 35000.0},
            'Стол на 6 мест':          {'hourly': 1100.0,'weekly': 14000.0, 'monthly': 50000.0},
            'Стол на 8 мест':          {'hourly': 1400.0,'weekly': 17000.0, 'monthly': 60000.0},
            'Переговорная 10 мест':    {'hourly': 500.0, 'weekly': 6000.0,  'monthly': 20000.0},
            'Переговорная 14 мест':    {'hourly': 700.0, 'weekly': 8000.0,  'monthly': 28000.0},
            'Переговорная 20 мест':    {'hourly': 1000.0,'weekly': 12000.0, 'monthly': 40000.0},
        }
        for cat_data in default_categories:
            existing = PlaceCategory.query.filter_by(name=cat_data['name']).first()
            if not existing:
                category = PlaceCategory(**cat_data)
                db.session.add(category)
                db.session.flush()
                for tariff_type, price in default_tariffs.get(cat_data['name'], {}).items():
                    if not CategoryTariff.query.filter_by(
                        category_id=category.id, tariff_type=tariff_type
                    ).first():
                        db.session.add(CategoryTariff(
                            category_id=category.id,
                            tariff_type=tariff_type,
                            price=price,
                            active=True,
                        ))
        db.session.commit()
        print(f"[OK] Категории мест: {PlaceCategory.query.count()}")
        print(f"[OK] Тарифы: {CategoryTariff.query.count()}")

        # 4. Рабочие места из layout.json (только desk и room — не кухня/отдых/санузел)
        categories_cache = {cat.capacity: cat for cat in PlaceCategory.query.filter_by(kind='desk').all()}
        room_category    = PlaceCategory.query.filter_by(kind='room', capacity=10).first()
        for p in layout.get('places', []):
            if not layout_place_belongs_in_db(p):
                continue
            if Place.query.filter_by(code=p['code']).first():
                continue
            location = Location.query.filter_by(code=p['location']).first()
            if not location:
                print(f"[ERR] Локация не найдена: {p['location']} (место {p['code']})")
                continue
            category_id = p.get('category_id')
            if category_id and not PlaceCategory.query.get(category_id):
                category_id = None
            if not category_id:
                if p['kind'] == 'room' and room_category:
                    category_id = room_category.id
                elif p['kind'] == 'desk' and categories_cache.get(1):
                    category_id = categories_cache.get(p.get('capacity', 1), categories_cache.get(1)).id
            floor_num = int(p.get('floor') or infer_floor_from_location_code(p.get('location', '1Б')))
            place_floor = Floor.query.filter_by(number=floor_num).first()
            db.session.add(Place(
                code=p['code'],
                name=p['name'],
                location_id=location.id,
                floor_id=place_floor.id if place_floor else location.floor_id,
                kind=p['kind'],
                category_id=category_id,
            ))
        db.session.commit()
        print(f"[OK] Рабочие места: {Place.query.count()}")

        # 5. Первый администратор – из .env (ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_NAME)
        if User.query.filter_by(role='admin').count() == 0:
            admin_email    = os.environ.get('ADMIN_EMAIL',    'admin@coworking.com')
            admin_password = os.environ.get('ADMIN_PASSWORD', 'ChangeMe123!')
            admin_name     = os.environ.get('ADMIN_NAME',     'Администратор')
            admin = User(
                email=admin_email,
                username=admin_name,
                role='admin',
                active=True,
            )
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            print(f"[OK] Администратор создан: {admin_email}")
            print("[!]  Смените пароль администратора после первого входа!")

        # 6. Шаблоны абонементов (начальные значения)
        if Subscription.query.filter_by(is_template=True).count() == 0:
            today = date.today()
            defaults = [
                {'name': 'Столы – 7 дней',          'duration_days': 7,  'price': 3500,  'place_kinds': ['desk'], 'hours_limit': 40},
                {'name': 'Столы – 30 дней',          'duration_days': 30, 'price': 12000, 'place_kinds': ['desk'], 'hours_limit': None},
                {'name': 'Переговорные – 30 дней',   'duration_days': 30, 'price': 18000, 'place_kinds': ['room'], 'hours_limit': 20},
            ]
            for item in defaults:
                db.session.add(Subscription(
                    user_id=None,
                    name=item['name'],
                    is_template=True,
                    duration_days=item['duration_days'],
                    place_kinds=json.dumps(item['place_kinds']),
                    start_date=today,
                    end_date=today + timedelta(days=item['duration_days']),
                    hours_limit=item['hours_limit'],
                    price=item['price'],
                    active=True,
                ))
            db.session.commit()
            print(f"[OK] Шаблоны абонементов: {len(defaults)}")

        print("Начальные данные успешно загружены.")
        _seed_demo_bookings()
    except Exception as e:
        db.session.rollback()
        print(f"[ERR] Ошибка инициализации данных: {e}")
        import traceback
        traceback.print_exc()


def _seed_demo_bookings():
    """Демо-бронирования за последние ~60 дней для отчётности (только если БД пуста)."""
    import random
    from datetime import time as dt_time

    if Booking.query.count() > 0:
        return False

    desks = Place.query.filter_by(kind='desk', active=True).limit(12).all()
    rooms = Place.query.filter(
        Place.kind.in_(('room', 'space')),
        Place.active == True,
        Place.category.has(kind='room'),
    ).limit(4).all()
    places = desks + rooms
    if not places:
        print('[SKIP] Нет мест для демо-бронирований')
        return False

    clients = []
    demo_users = [
        ('client1@coworking.local', 'Анна К.', '+7 999 111 22 01'),
        ('client2@coworking.local', 'Иван П.', '+7 999 111 22 02'),
        ('client3@coworking.local', 'Мария С.', '+7 999 111 22 03'),
    ]
    for email, name, phone in demo_users:
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email, username=name, phone=phone, role='client', visitor_kind='tariff')
            user.set_password('Demo123!')
            db.session.add(user)
            db.session.flush()
        clients.append(user)

    templates = Subscription.query.filter_by(is_template=True, active=True).all()
    issued_subs = []
    today = date.today()
    rng = random.Random(42)

    for i, client in enumerate(clients[:2]):
        if not templates:
            break
        tpl = templates[i % len(templates)]
        sub = Subscription(
            user_id=client.id,
            name=tpl.name,
            is_template=False,
            duration_days=tpl.duration_days,
            place_kinds=tpl.place_kinds,
            start_date=today - timedelta(days=45 - i * 10),
            end_date=today + timedelta(days=15),
            hours_limit=tpl.hours_limit,
            hours_used=0,
            price=tpl.price,
            active=True,
        )
        db.session.add(sub)
        db.session.flush()
        issued_subs.append(sub)

    db.session.commit()

    start_day = today - timedelta(days=60)
    statuses_weights = [('completed', 0.72), ('active', 0.13), ('cancelled', 0.15)]
    created = 0

    for day_offset in range(61):
        bdate = start_day + timedelta(days=day_offset)
        if bdate > today + timedelta(days=14):
            break
        daily_count = rng.randint(0, 3) if bdate.weekday() < 5 else rng.randint(0, 1)
        for _ in range(daily_count):
            place = rng.choice(places)
            client = rng.choice(clients)
            tariff_type = rng.choices(
                ['hourly', 'weekly', 'monthly'],
                weights=[0.78, 0.14, 0.08],
            )[0]
            status = rng.choices([s for s, _ in statuses_weights], weights=[w for _, w in statuses_weights])[0]
            if bdate > today:
                status = 'active'
            elif bdate < today - timedelta(days=1):
                status = rng.choices(['completed', 'cancelled'], weights=[0.88, 0.12])[0]

            hourly_price = float(place.get_price('hourly') or 250)
            weekly_price = float(place.get_price('weekly') or 3500)
            monthly_price = float(place.get_price('monthly') or 12000)
            people = 1
            subscription_id = None
            duration_hours = 0.0
            start_t = dt_time(rng.randint(9, 16), rng.choice([0, 15, 30, 45]))
            end_t = start_t

            if tariff_type == 'hourly':
                slots = rng.choice([2, 3, 4, 6, 8])
                duration_hours = slots * 0.25
                end_min = start_t.hour * 60 + start_t.minute + int(duration_hours * 60)
                end_t = dt_time(min(21, end_min // 60), end_min % 60)
                total = round(hourly_price * people * duration_hours)
                if issued_subs and rng.random() < 0.22:
                    subscription_id = rng.choice(issued_subs).id
                    total = 0
            elif tariff_type == 'weekly':
                duration_hours = 7 * 8
                end_t = dt_time(22, 0)
                total = int(weekly_price)
            else:
                duration_hours = 30 * 8
                end_t = dt_time(22, 0)
                total = int(monthly_price)

            db.session.add(Booking(
                user_id=client.id,
                place_id=place.id,
                booking_date=bdate,
                start_time=start_t,
                end_time=end_t,
                duration_hours=duration_hours,
                total_price=total,
                people_count=people,
                tariff_type=tariff_type,
                subscription_id=subscription_id,
                status=status,
            ))
            created += 1

    db.session.commit()
    print(f'[OK] Демо-бронирования: {created} записей за 60 дней')
    return True


def update_booking_statuses():
    try:
        from internal.services.booking_service import booking_period_end

        now = datetime.now()
        active_bookings = Booking.query.filter_by(status='active').all()
        bookings_to_complete = []
        for b in active_bookings:
            period_end = booking_period_end(b)
            if b.tariff_type in ('weekly', 'monthly'):
                if period_end < now.date():
                    bookings_to_complete.append(b)
            elif b.booking_date < now.date() or (
                b.booking_date == now.date() and b.end_time <= now.time()
            ):
                bookings_to_complete.append(b)

        for b in bookings_to_complete:
            b.status = 'completed'
        if bookings_to_complete:
            db.session.commit()
            print(f"Обновлено {len(bookings_to_complete)} бронирований")
            return len(bookings_to_complete)
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка обновления статусов: {e}")
    return 0


def cleanup_suspicious_bookings(max_hourly_rate=2500, max_short_total=5000, max_short_hours=2):
    """Удалить почасовые брони с нереалистичной стоимостью (артефакты демо-данных)."""
    from sqlalchemy import inspect as sa_inspect
    try:
        if not sa_inspect(db.engine).has_table('bookings'):
            return 0
        deleted = 0
        for booking in Booking.query.filter(Booking.tariff_type == 'hourly').all():
            if not booking.total_price:
                continue
            hours = booking.duration_hours or 0
            if hours <= 0:
                hours = 1.0
            hourly_rate = float(booking.total_price) / float(hours)
            if hourly_rate > max_hourly_rate or (
                booking.total_price >= max_short_total and hours <= max_short_hours
            ):
                db.session.delete(booking)
                deleted += 1
        if deleted:
            db.session.commit()
            print(f'[MIGRATE] Удалено подозрительных бронирований: {deleted}')
        return deleted
    except Exception as e:
        db.session.rollback()
        print(f'[MIGRATE] cleanup_suspicious_bookings: {e}')
        return 0


def run_migrations():
    """Простейшие миграции: добавление колонок и таблиц без Alembic."""
    from sqlalchemy import inspect, text
    try:
        inspector = inspect(db.engine)

        # 1. Таблица notifications
        if not inspector.has_table('notifications'):
            print("[MIGRATE] Создаем таблицу notifications...")
            db.create_all()

        # 2. container_code и enclosed в places
        if inspector.has_table('places'):
            place_columns = [c['name'] for c in inspector.get_columns('places')]
            if 'container_code' not in place_columns:
                print("[MIGRATE] Добавляем container_code в places...")
                with db.engine.connect() as conn:
                    conn.execute(text(
                        "ALTER TABLE places ADD COLUMN container_code VARCHAR(32)"
                    ))
                    conn.commit()
            if 'parent_id' in place_columns:
                print("[MIGRATE] Перенос parent_id -> container_code...")
                with db.engine.connect() as conn:
                    conn.execute(text("""
                        UPDATE places SET container_code = (
                            SELECT p2.code FROM places p2
                            WHERE p2.id_place = places.parent_id
                        )
                        WHERE parent_id IS NOT NULL
                          AND (container_code IS NULL OR container_code = '')
                    """))
                    conn.commit()
            if 'enclosed' not in place_columns:
                print("[MIGRATE] Добавляем enclosed в places...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE places ADD COLUMN enclosed BOOLEAN DEFAULT FALSE"))
                    conn.commit()
            print("[MIGRATE] places OK")

        # 5. subscriptions: шаблоны
        if not inspector.has_table('subscriptions'):
            db.create_all()
        if inspector.has_table('subscriptions'):
            sub_columns = [c['name'] for c in inspector.get_columns('subscriptions')]
            if 'is_template' not in sub_columns:
                print('[MIGRATE] Добавляем is_template в subscriptions...')
                with db.engine.connect() as conn:
                    conn.execute(text(
                        'ALTER TABLE subscriptions ADD COLUMN is_template BOOLEAN DEFAULT FALSE'
                    ))
                    conn.commit()
            if 'duration_days' not in sub_columns:
                print('[MIGRATE] Добавляем duration_days в subscriptions...')
                with db.engine.connect() as conn:
                    conn.execute(text(
                        'ALTER TABLE subscriptions ADD COLUMN duration_days INTEGER'
                    ))
                    conn.commit()
            user_id_col = next((c for c in inspector.get_columns('subscriptions') if c['name'] == 'user_id'), None)
            if user_id_col and not user_id_col.get('nullable'):
                try:
                    with db.engine.connect() as conn:
                        conn.execute(text(
                            'ALTER TABLE subscriptions ALTER COLUMN user_id DROP NOT NULL'
                        ))
                        conn.commit()
                except Exception:
                    pass

        # 5a. sender_id и booking_id в notifications
        if inspector.has_table('notifications'):
            notif_columns = [c['name'] for c in inspector.get_columns('notifications')]
            if 'sender_id' not in notif_columns:
                print('[MIGRATE] Добавляем sender_id в notifications...')
                with db.engine.connect() as conn:
                    conn.execute(text(
                        'ALTER TABLE notifications ADD COLUMN sender_id INTEGER '
                        'REFERENCES users(id_user) ON DELETE SET NULL'
                    ))
                    conn.commit()
                notif_columns.append('sender_id')
            if 'booking_id' not in notif_columns:
                booking_pk = 'id_booking'
                if inspector.has_table('bookings'):
                    booking_cols = [c['name'] for c in inspector.get_columns('bookings')]
                    if 'id_booking' not in booking_cols and 'id' in booking_cols:
                        booking_pk = 'id'
                print('[MIGRATE] Добавляем booking_id в notifications...')
                with db.engine.connect() as conn:
                    conn.execute(text(
                        f'ALTER TABLE notifications ADD COLUMN booking_id INTEGER '
                        f'REFERENCES bookings({booking_pk}) ON DELETE SET NULL'
                    ))
                    conn.commit()

            for col_name, col_def in (
                ('staff_reply', 'TEXT'),
                ('replied_at', 'TIMESTAMP'),
                ('replied_by_id', 'INTEGER REFERENCES users(id_user) ON DELETE SET NULL'),
                ('is_archived', 'BOOLEAN DEFAULT FALSE'),
                ('archived_at', 'TIMESTAMP'),
                ('reply_read_by_client', 'BOOLEAN DEFAULT TRUE'),
            ):
                if col_name not in notif_columns:
                    print(f'[MIGRATE] Добавляем {col_name} в notifications...')
                    with db.engine.connect() as conn:
                        conn.execute(text(
                            f'ALTER TABLE notifications ADD COLUMN {col_name} {col_def}'
                        ))
                        conn.commit()
                    notif_columns.append(col_name)

            if 'reply_read_by_client' in notif_columns:
                with db.engine.connect() as conn:
                    conn.execute(text(
                        "UPDATE notifications SET reply_read_by_client = FALSE "
                        "WHERE staff_reply IS NOT NULL AND TRIM(staff_reply) != '' "
                        "AND reply_read_by_client IS TRUE"
                    ))
                    conn.execute(text(
                        "UPDATE notifications SET is_archived = TRUE, "
                        "archived_at = COALESCE(archived_at, replied_at, CURRENT_TIMESTAMP) "
                        "WHERE staff_reply IS NOT NULL AND TRIM(staff_reply) != '' "
                        "AND (is_archived IS FALSE OR is_archived IS NULL)"
                    ))
                    conn.commit()

        # 5b. subscription_id в bookings
        if inspector.has_table('bookings'):
            booking_columns = [c['name'] for c in inspector.get_columns('bookings')]
            if 'subscription_id' not in booking_columns:
                print('[MIGRATE] Добавляем subscription_id в bookings...')
                with db.engine.connect() as conn:
                    conn.execute(text(
                        'ALTER TABLE bookings ADD COLUMN subscription_id INTEGER '
                        'REFERENCES subscriptions(id_subscription) ON DELETE SET NULL'
                    ))
                    conn.commit()

            _migrate_booking_fk_policy(inspector)

        # 6. location_zone_types и zone_type_id в locations
        if not inspector.has_table('location_zone_types'):
            print("[MIGRATE] Создаем таблицу location_zone_types...")
            db.create_all()
        if inspector.has_table('locations'):
            loc_columns = [c['name'] for c in inspector.get_columns('locations')]
            if 'zone_type_id' not in loc_columns:
                print("[MIGRATE] Добавляем zone_type_id в locations...")
                with db.engine.connect() as conn:
                    conn.execute(text(
                        "ALTER TABLE locations ADD COLUMN zone_type_id INTEGER "
                        "REFERENCES location_zone_types(id) ON DELETE SET NULL"
                    ))
                    conn.commit()
    except Exception as e:
        print(f"[MIGRATE] Ошибка: {e}")
        import traceback
        traceback.print_exc()

    try:
        _migrate_user_login_fields(inspector)
        _migrate_user_password_fields(inspector)
    except Exception as e:
        print(f"[MIGRATE] users login fields: {e}")

    try:
        from internal.utils.phone import migrate_user_phones
        migrate_user_phones()
    except Exception as e:
        print(f"[MIGRATE] Телефоны: {e}")

    try:
        _migrate_primary_key_names(inspector)
    except Exception as e:
        print(f"[MIGRATE] PK rename: {e}")

    try:
        cleanup_suspicious_bookings()
    except Exception as e:
        print(f"[MIGRATE] suspicious bookings: {e}")


def _migrate_user_login_fields(inspector):
    """email nullable, phone unique; убрать технические guest_*@coworking.local."""
    if not inspector.has_table('users'):
        return

    user_columns = {c['name']: c for c in inspector.get_columns('users')}
    email_nullable = user_columns.get('email', {}).get('nullable', True)

    with db.engine.connect() as conn:
        if db.engine.dialect.name == 'postgresql':
            conn.execute(text(
                "UPDATE users SET email = NULL "
                "WHERE email LIKE 'guest_%@coworking.local'"
            ))
            conn.commit()

            if not email_nullable:
                print('[MIGRATE] users.email: DROP NOT NULL')
                conn.execute(text('ALTER TABLE users ALTER COLUMN email DROP NOT NULL'))
                conn.commit()

            idx = conn.execute(text(
                "SELECT 1 FROM pg_indexes "
                "WHERE tablename = 'users' AND indexname = 'users_phone_unique'"
            )).fetchone()
            if not idx:
                try:
                    conn.execute(text(
                        'CREATE UNIQUE INDEX users_phone_unique ON users (phone) '
                        'WHERE phone IS NOT NULL'
                    ))
                    conn.commit()
                    print('[MIGRATE] users.phone: unique index')
                except Exception as e:
                    conn.rollback()
                    print(f'[MIGRATE] users.phone unique: {e}')
        else:
            conn.execute(text(
                "UPDATE users SET email = NULL "
                "WHERE email LIKE 'guest_%@coworking.local'"
            ))
            conn.commit()


def _migrate_user_password_fields(inspector):
    """Временный пароль для быстрой регистрации."""
    if not inspector.has_table('users'):
        return
    cols = {c['name'] for c in inspector.get_columns('users')}
    with db.engine.connect() as conn:
        if 'must_change_password' not in cols:
            print('[MIGRATE] users.must_change_password')
            if db.engine.dialect.name == 'postgresql':
                conn.execute(text(
                    'ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE'
                ))
            else:
                conn.execute(text(
                    'ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0'
                ))
            conn.commit()
        if 'issued_temp_password' not in cols:
            print('[MIGRATE] users.issued_temp_password')
            conn.execute(text(
                'ALTER TABLE users ADD COLUMN issued_temp_password VARCHAR(32)'
            ))
            conn.commit()


def _drop_fk_on_column(conn, table, column):
    rows = conn.execute(text("""
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
        WHERE t.relname = :table AND a.attname = :column AND c.contype = 'f'
    """), {'table': table, 'column': column}).fetchall()
    for (name,) in rows:
        conn.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{name}"'))


def _booking_fk_restrict_applied(conn):
    """Миграция RESTRICT уже применена?"""
    row = conn.execute(text("""
        SELECT c.confdeltype
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE t.relname = 'bookings' AND c.contype = 'f'
          AND c.conname = 'bookings_user_id_fkey'
    """)).fetchone()
    return row and row[0] == 'r'


def _migrate_booking_fk_policy(inspector):
    """RESTRICT на user/place; убрать лишние place_code/place_name из bookings."""
    if db.engine.dialect.name != 'postgresql' or not inspector.has_table('bookings'):
        return

    booking_columns = [c['name'] for c in inspector.get_columns('bookings')]
    with db.engine.connect() as conn:
        for col in ('place_code', 'place_name', 'seat_number'):
            if col in booking_columns:
                print(f'[MIGRATE] Удаляем bookings.{col}...')
                conn.execute(text(f'ALTER TABLE bookings DROP COLUMN IF EXISTS {col}'))
                conn.commit()

        if _booking_fk_restrict_applied(conn):
            return

        print('[MIGRATE] FK bookings/ratings: RESTRICT (история броней)...')
        try:
            for table, column in (('bookings', 'place_id'), ('bookings', 'user_id'),
                                  ('ratings', 'place_id'), ('ratings', 'user_id')):
                if inspector.has_table(table):
                    _drop_fk_on_column(conn, table, column)

            conn.execute(text(
                'DELETE FROM bookings WHERE place_id IS NULL'
            ))
            if inspector.has_table('ratings'):
                conn.execute(text(
                    'DELETE FROM ratings WHERE place_id IS NULL'
                ))

            conn.execute(text('ALTER TABLE bookings ALTER COLUMN place_id SET NOT NULL'))
            if inspector.has_table('ratings'):
                conn.execute(text('ALTER TABLE ratings ALTER COLUMN place_id SET NOT NULL'))

            conn.execute(text(
                'ALTER TABLE bookings ADD CONSTRAINT bookings_user_id_fkey '
                'FOREIGN KEY (user_id) REFERENCES users(id_user) ON DELETE RESTRICT'
            ))
            conn.execute(text(
                'ALTER TABLE bookings ADD CONSTRAINT bookings_place_id_fkey '
                'FOREIGN KEY (place_id) REFERENCES places(id_place) ON DELETE RESTRICT'
            ))
            if inspector.has_table('ratings'):
                conn.execute(text(
                    'ALTER TABLE ratings ADD CONSTRAINT ratings_user_id_fkey '
                    'FOREIGN KEY (user_id) REFERENCES users(id_user) ON DELETE RESTRICT'
                ))
                conn.execute(text(
                    'ALTER TABLE ratings ADD CONSTRAINT ratings_place_id_fkey '
                    'FOREIGN KEY (place_id) REFERENCES places(id_place) ON DELETE RESTRICT'
                ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f'[MIGRATE] FK bookings/ratings: {e}')


def _migrate_primary_key_names(inspector):
    """Переименование id -> id_user, id_place и т.д. (PostgreSQL)."""
    from sqlalchemy import inspect, text

    if db.engine.dialect.name != 'postgresql':
        return

    renames = [
        ('users', 'id_user'),
        ('coworkings', 'id_coworking'),
        ('floors', 'id_floor'),
        ('location_zone_types', 'id_zone_type'),
        ('locations', 'id_location'),
        ('place_categories', 'id_category'),
        ('category_tariffs', 'id_tariff'),
        ('places', 'id_place'),
        ('bookings', 'id_booking'),
        ('ratings', 'id_rating'),
        ('subscriptions', 'id_subscription'),
        ('notifications', 'id_notification'),
        ('coworking_schedules', 'id_schedule'),
    ]

    inspector = inspect(db.engine)
    with db.engine.connect() as conn:
        for table, new_name in renames:
            if not inspector.has_table(table):
                continue
            cols = {c['name'] for c in inspector.get_columns(table)}
            if 'id' in cols and new_name not in cols:
                print(f'[MIGRATE] {table}.id -> {new_name}')
                conn.execute(text(f'ALTER TABLE {table} RENAME COLUMN id TO {new_name}'))
                conn.commit()
                inspector = inspect(db.engine)


def init_db(app):
    from internal.config import ensure_database

    ensure_database()
    with app.app_context():
        # run_migrations() уже вызван в create_app()
        print("Создание/проверка таблиц базы данных...")
        db.create_all()
        init_default_data()
        sync_place_parents_from_layout()
        sync_location_floors_from_layout()
        sync_place_locations_from_layout()
        ensure_default_zone_types()
        purge_amenity_places()
        n = migrate_legacy_place_codes()
        if n:
            print(f'[OK] Переименовано legacy-кодов: {n}')
        Coworking.ensure_singleton()

        print("Инициализация расписания коворкинга...")
        first_coworking = Coworking.query.first()
        if first_coworking:
            CoworkingSchedule.init_default_schedule(first_coworking.id)
        print(f"[OK] Расписание: {CoworkingSchedule.query.count()} дней")
        print("Таблицы базы данных готовы")
        completed = update_booking_statuses()
        if completed > 0:
            print(f"Автоматически завершено {completed} бронирований")
