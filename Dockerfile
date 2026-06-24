FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PGCLIENTENCODING=UTF8 \
    TZ=Europe/Moscow

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh

COPY . .

EXPOSE 5000

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "wsgi:app"]
