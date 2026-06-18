import os
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault('PGCLIENTENCODING', 'UTF8')


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-change-in-production'

    # PostgreSQL — все значения берутся из .env (обязательно для запуска)
    DB_HOST     = os.environ.get('DB_HOST',     'localhost')
    DB_USER     = os.environ.get('DB_USER',     'postgres')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')          # без .env не запустится
    DB_NAME     = os.environ.get('DB_NAME',     'coworking')
    DB_PORT     = os.environ.get('DB_PORT',     '5432')

    SQLALCHEMY_DATABASE_URI = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
        'connect_args': {'options': '-c client_encoding=UTF8'},
    }
    # Настройки безопасности
    WTF_CSRF_ENABLED = True
    DEBUG = True


class TestConfig(Config):
    """Конфигурация для unit-тестов (SQLite in-memory)."""
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_ENGINE_OPTIONS = {}


def ensure_database():
    """Создать БД PostgreSQL, если её ещё нет (первый запуск)."""
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    conn = psycopg2.connect(
        host=Config.DB_HOST,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        port=Config.DB_PORT,
        dbname='postgres',
    )
    try:
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (Config.DB_NAME,))
            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{Config.DB_NAME}"')
                print(f'[DB] Создана база данных: {Config.DB_NAME}')
    finally:
        conn.close()