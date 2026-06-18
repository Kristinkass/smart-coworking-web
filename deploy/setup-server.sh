#!/bin/bash
# Первичная настройка сервера Ubuntu для smart-coworking.
# Запускать на сервере от root: bash deploy/setup-server.sh

set -euo pipefail

DOMAIN="smart-co-working.ru"
PROJECT_DIR="${PROJECT_DIR:-/root/smart-coworking}"

echo "==> Установка Nginx и Certbot..."
apt-get update
apt-get install -y nginx certbot python3-certbot-nginx

echo "==> Каталог для ACME challenge..."
mkdir -p /var/www/certbot

echo "==> Копирование конфига Nginx..."
cp "$PROJECT_DIR/deploy/nginx/smart-co-working.ru.conf" \
   /etc/nginx/sites-available/smart-co-working.ru

ln -sf /etc/nginx/sites-available/smart-co-working.ru \
        /etc/nginx/sites-enabled/smart-co-working.ru
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl reload nginx

echo "==> SSL-сертификат Let's Encrypt..."
# Замените email на свой перед запуском
CERTBOT_EMAIL="${CERTBOT_EMAIL:-admin@$DOMAIN}"

certbot --nginx -d "$DOMAIN" -d "www.$DOMAIN" --non-interactive --agree-tos -m "$CERTBOT_EMAIL" || {
  echo "Certbot не смог выпустить сертификат. Проверьте DNS (A-запись -> IP сервера) и повторите:"
  echo "  certbot --nginx -d $DOMAIN -d www.$DOMAIN"
  exit 1
}

echo "==> Firewall (UFW)..."
if command -v ufw >/dev/null 2>&1; then
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable || true
fi

echo "==> Готово. Сайт: https://$DOMAIN"
