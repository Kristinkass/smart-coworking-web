"""Phone number formatting and validation."""
import re

CANONICAL_RE = re.compile(r'^\+7 \d{3} \d{3} \d{2} \d{2}$')


def digits_only(phone):
    if not phone:
        return ''
    return re.sub(r'\D', '', str(phone).strip())


def normalize_phone(phone):
    """Canonical storage: +7 XXX XXX XX XX (spaces, no dashes)."""
    if not phone:
        return None
    raw = str(phone).strip()
    if not raw:
        return None
    digits = digits_only(raw)
    if not digits:
        return None
    if digits.startswith('8') and len(digits) >= 11:
        digits = '7' + digits[1:]
    elif len(digits) == 10:
        digits = '7' + digits
    if len(digits) != 11 or not digits.startswith('7'):
        return raw
    return f'+7 {digits[1:4]} {digits[4:7]} {digits[7:9]} {digits[9:11]}'


def format_phone_display(phone):
    return normalize_phone(phone) or (phone or '')


def migrate_user_phones():
    """One-time normalization of stored phone numbers (без ORM-сессии)."""
    from sqlalchemy import text
    from internal.models import db

    with db.engine.connect() as conn:
        bad = conn.execute(text(
            "SELECT id_user, phone FROM users "
            "WHERE phone IS NOT NULL AND phone LIKE '%-%' LIMIT 500"
        )).fetchall()
        if not bad:
            return 0

        updated = 0
        for user_id, phone in bad:
            norm = normalize_phone(phone)
            if norm and norm != phone:
                conn.execute(
                    text('UPDATE users SET phone = :p WHERE id_user = :id'),
                    {'p': norm, 'id': user_id},
                )
                updated += 1
        if updated:
            conn.commit()
            print(f'[MIGRATE] Нормализовано телефонов: {updated}')
    return updated
