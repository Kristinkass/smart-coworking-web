FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PGCLIENTENCODING=UTF8 \
    TZ=Europe/Moscow

WORKDIR /app

# Без apt-get: на части VPS deb.debian.org недоступен.
# psycopg2-binary — готовые wheels; шрифты PDF — scripts/ensure_pdf_fonts.py
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/ensure_pdf_fonts.py scripts/ensure_pdf_fonts.py
RUN python scripts/ensure_pdf_fonts.py || echo "PDF fonts: skip (Helvetica fallback)"

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh

COPY . .

EXPOSE 5000

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "wsgi:app"]
