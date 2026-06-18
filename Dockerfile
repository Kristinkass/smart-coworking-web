FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PGCLIENTENCODING=UTF8

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x scripts/docker-entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["scripts/docker-entrypoint.sh"]
CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "wsgi:app"]
