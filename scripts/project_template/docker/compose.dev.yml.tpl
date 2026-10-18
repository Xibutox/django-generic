# {{ title }} in development: Postgres and Redis in containers, Django
# and Celery from the dev image, the working copy mounted over /app so
# runserver reloads on every change.
#
#   python ops.py up --dev
#
# or docker compose -f docker/compose.dev.yml --env-file docker/dev.env up --build
#
# Its passwords are random too (docker/dev.env), and every port is
# published on this machine only (127.0.0.1): never on the network.

name: {{ slug }}-dev

x-app: &app
  build:
    context: ..
    dockerfile: docker/Dockerfile
    target: dev
  image: {{ slug }}:dev
  environment:
    DJANGO_SECRET_KEY: ${DJANGO_SECRET_KEY:?run python ops.py env}
    DATABASE_URL: postgres://${POSTGRES_USER:?run python ops.py env}:${POSTGRES_PASSWORD:?run python ops.py env}@db:5432/${POSTGRES_DB:?run python ops.py env}
    REDIS_URL: redis://:${REDIS_PASSWORD:?run python ops.py env}@redis:6379/0
    CELERY_BROKER_URL: redis://:${REDIS_PASSWORD:?run python ops.py env}@redis:6379/1
  volumes:
    - ..:/app
  security_opt:
    - no-new-privileges:true
  depends_on:
    db:
      condition: service_healthy
    redis:
      condition: service_healthy

services:
  db:
    image: ${POSTGRES_IMAGE:-postgres:17}
    environment:
      POSTGRES_DB: ${POSTGRES_DB:?run python ops.py env}
      POSTGRES_USER: ${POSTGRES_USER:?run python ops.py env}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?run python ops.py env}
      POSTGRES_INITDB_ARGS: --auth-host=scram-sha-256 --data-checksums
      POSTGRES_HOST_AUTH_METHOD: scram-sha-256
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U \"$${POSTGRES_USER}\" -d \"$${POSTGRES_DB}\""]
      interval: 5s
      timeout: 3s
      retries: 10
    ports:
      - "127.0.0.1:${POSTGRES_PORT:-5432}:5432"

  redis:
    image: ${REDIS_IMAGE:-redis:7-alpine}
    environment:
      REDIS_PASSWORD: ${REDIS_PASSWORD:?run python ops.py env}
    command:
      - sh
      - -c
      - >
        printf 'requirepass %s\n' "$$REDIS_PASSWORD" > /tmp/redis.conf &&
        exec redis-server /tmp/redis.conf --save "" --appendonly no
    healthcheck:
      test: ["CMD-SHELL", "REDISCLI_AUTH=\"$$REDIS_PASSWORD\" redis-cli ping | grep -q PONG"]
      interval: 5s
      timeout: 3s
      retries: 10
    ports:
      - "127.0.0.1:${REDIS_PORT:-6379}:6379"

  migrate:
    <<: *app
    command: python manage.py migrate --noinput

  web:
    <<: *app
    command: python manage.py runserver 0.0.0.0:8000
    depends_on:
      migrate:
        condition: service_completed_successfully
    ports:
      - "127.0.0.1:${WEB_PORT:-8000}:8000"

  worker:
    <<: *app
    command: celery -A {{ project }}.celery worker --loglevel=info
    depends_on:
      migrate:
        condition: service_completed_successfully

  beat:
    <<: *app
    command: >
      celery -A {{ project }}.celery beat --loglevel=info
      --scheduler django_celery_beat.schedulers:DatabaseScheduler
    depends_on:
      migrate:
        condition: service_completed_successfully

volumes:
  postgres-data:
