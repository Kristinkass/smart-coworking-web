-- Сброс зависших сессий на базе coworking_123456 (выполнить в pgAdmin / psql один раз).
-- После этого перезапустите приложение.

SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'coworking_123456'
  AND pid <> pg_backend_pid();
