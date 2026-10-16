# {{ title }} in production: Daphne, Celery's worker and scheduler,
# Postgres, Redis, Caddy in front, and the encrypted backups.
#
#   python ops.py up                      # build and start
#   python ops.py manage createsuperuser  # the first account
#   python ops.py backup | verify | restore-test | restore
#
# or by hand, from the project's root:
#
#   docker compose -f docker/compose.prod.yml --env-file docker/prod.env up -d --build
#
# Every value comes from docker/prod.env, written with random secrets by
# `python ops.py env`; a missing required one stops `docker compose`
# before anything starts. SECURITY-CONTROLS.md says which ISO/IEC
# 27002:2022 control each choice below answers.

name: {{ slug }}

# -- What every container gets (27002 8.9 configuration, 8.20-8.22) ------
#
# No privilege escalation, no Linux capability it does not name, a
# read-only filesystem but for its volumes and an in-memory /tmp, and
# logs rotated rather than filling the disk (8.15 logging). Each
# service bounds its memory and processes under deploy (8.6 capacity).

x-hardened: &hardened
  restart: unless-stopped
  security_opt:
    - no-new-privileges:true
  cap_drop:
    - ALL
  read_only: true
  tmpfs:
    - /tmp:size=64m,mode=1777
  logging:
    driver: json-file
    options:
      max-size: "10m"
      max-file: "10"

x-app: &app
  <<: *hardened
  build:
    context: ..
    dockerfile: docker/Dockerfile
    target: prod
  image: {{ slug }}:prod
  environment: &app-environment
    TZ: ${TZ:-UTC}
    DJANGO_SETTINGS_MODULE: {{ project }}.settings.prod
    DJANGO_SECRET_KEY: ${DJANGO_SECRET_KEY:?run python ops.py env}
    DJANGO_ALLOWED_HOSTS: ${DJANGO_ALLOWED_HOSTS:?run python ops.py env}
    DJANGO_CSRF_TRUSTED_ORIGINS: ${DJANGO_CSRF_TRUSTED_ORIGINS:-}
    DJANGO_SITE_URL: ${DJANGO_SITE_URL:-}
    DJANGO_HTTPS: ${DJANGO_HTTPS:-1}
    DJANGO_HSTS_SECONDS: ${DJANGO_HSTS_SECONDS:-}
    DJANGO_HSTS_SUBDOMAINS: ${DJANGO_HSTS_SUBDOMAINS:-}
    DJANGO_HSTS_PRELOAD: ${DJANGO_HSTS_PRELOAD:-}
    DJANGO_SESSION_AGE: ${DJANGO_SESSION_AGE:-}
    DJANGO_LOG_LEVEL: ${DJANGO_LOG_LEVEL:-INFO}
    DJANGO_LOG_FILE: /app/logs/app.log
    DJANGO_ADMINS: ${DJANGO_ADMINS:-}
    DJANGO_DEFAULT_FROM_EMAIL: ${DJANGO_DEFAULT_FROM_EMAIL:-}
    DATABASE_URL: postgres://${POSTGRES_USER:?run python ops.py env}:${POSTGRES_PASSWORD:?run python ops.py env}@db:5432/${POSTGRES_DB:?run python ops.py env}
    REDIS_URL: redis://:${REDIS_PASSWORD:?run python ops.py env}@redis:6379/0
    CELERY_BROKER_URL: redis://:${REDIS_PASSWORD:?run python ops.py env}@redis:6379/1
    EMAIL_HOST: ${EMAIL_HOST:-}
    EMAIL_PORT: ${EMAIL_PORT:-}
    EMAIL_HOST_USER: ${EMAIL_HOST_USER:-}
    EMAIL_HOST_PASSWORD: ${EMAIL_HOST_PASSWORD:-}
    EMAIL_USE_TLS: ${EMAIL_USE_TLS:-}
  volumes:
    - app-logs:/app/logs
    - app-media:/app/media
  networks:
    - backend
    - outbound
  deploy:
    resources:
      limits:
        memory: ${APP_MEMORY_LIMIT:-1g}
        pids: 256

x-backup: &backup
  <<: *hardened
  build:
    context: ..
    dockerfile: docker/Dockerfile
    target: backup
  image: {{ slug }}:backup
  # root, to read every uploaded file and write the backups folder, but
  # with only the capabilities that takes - and none to escalate with.
  user: "0:0"
  cap_add:
    - CHOWN
    - DAC_OVERRIDE
    - FOWNER
  environment: &backup-environment
    TZ: ${TZ:-UTC}
    BACKUP_NAME: {{ slug }}
    PGHOST: db
    PGUSER: ${POSTGRES_USER:?run python ops.py env}
    PGPASSWORD: ${POSTGRES_PASSWORD:?run python ops.py env}
    PGDATABASE: ${POSTGRES_DB:?run python ops.py env}
    BACKUP_PASSPHRASE: ${BACKUP_PASSPHRASE:?run python ops.py env}
    BACKUP_TIME: ${BACKUP_TIME:-02:30}
    BACKUP_KEEP_DAYS: ${BACKUP_KEEP_DAYS:-30}
    BACKUP_TEST_WEEKDAY: ${BACKUP_TEST_WEEKDAY:-7}
  tmpfs:
    - /tmp:size=64m,mode=1777
  networks:
    - backend
  deploy:
    resources:
      limits:
        memory: ${BACKUP_MEMORY_LIMIT:-512m}
        pids: 64
  depends_on:
    db:
      condition: service_healthy

services:
  db:
    <<: *hardened
    image: ${POSTGRES_IMAGE:-postgres:16}
    # The image's entry point prepares the data folder as root, then
    # runs Postgres as its own user: these are what that takes.
    cap_add:
      - CHOWN
      - DAC_OVERRIDE
      - FOWNER
      - SETGID
      - SETUID
    tmpfs:
      - /tmp:size=64m,mode=1777
      - /var/run/postgresql:size=1m
    shm_size: 256m
    environment:
      TZ: ${TZ:-UTC}
      POSTGRES_DB: ${POSTGRES_DB:?run python ops.py env}
      POSTGRES_USER: ${POSTGRES_USER:?run python ops.py env}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?run python ops.py env}
      # Passwords checked with SCRAM-SHA-256, never sent in clear, and
      # every data page checksummed: corruption is found, not copied
      # into the backups (8.5, 8.13, 8.24).
      POSTGRES_INITDB_ARGS: --auth-host=scram-sha-256 --data-checksums
      POSTGRES_HOST_AUTH_METHOD: scram-sha-256
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - backend
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U \"$${POSTGRES_USER}\" -d \"$${POSTGRES_DB}\""]
      interval: 5s
      timeout: 3s
      retries: 10
    deploy:
      resources:
        limits:
          memory: ${DB_MEMORY_LIMIT:-1g}
          pids: 256

  redis:
    <<: *hardened
    image: ${REDIS_IMAGE:-redis:7-alpine}
    # Its own user from the start, so it needs no capability at all.
    user: redis
    # A password, written to a file only Redis reads rather than given
    # on its command line, where any user of the host would see it.
    environment:
      REDIS_PASSWORD: ${REDIS_PASSWORD:?run python ops.py env}
    command:
      - sh
      - -c
      - >
        umask 077 &&
        printf 'requirepass %s\n' "$$REDIS_PASSWORD" > /tmp/redis.conf &&
        exec redis-server /tmp/redis.conf
        --appendonly yes --protected-mode yes
    volumes:
      - redis-data:/data
    networks:
      - backend
    healthcheck:
      test: ["CMD-SHELL", "REDISCLI_AUTH=\"$$REDIS_PASSWORD\" redis-cli ping | grep -q PONG"]
      interval: 5s
      timeout: 3s
      retries: 10
    deploy:
      resources:
        limits:
          memory: ${REDIS_MEMORY_LIMIT:-256m}
          pids: 64

  # Runs once per start and exits; the rest waits for it to succeed.
  migrate:
    <<: *app
    restart: "no"
    command: python manage.py migrate --noinput
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

  web:
    <<: *app
    networks:
      - frontend
      - backend
      - outbound
    depends_on:
      migrate:
        condition: service_completed_successfully

  worker:
    <<: *app
    command: celery -A {{ project }}.celery worker --loglevel=info
    healthcheck:
      disable: true
    depends_on:
      migrate:
        condition: service_completed_successfully

  # One scheduler, never two: each would send every task it schedules.
  beat:
    <<: *app
    command: >
      celery -A {{ project }}.celery beat --loglevel=info
      --scheduler django_celery_beat.schedulers:DatabaseScheduler
    healthcheck:
      disable: true
    networks:
      - backend
    depends_on:
      migrate:
        condition: service_completed_successfully

  proxy:
    <<: *hardened
    build:
      context: ..
      dockerfile: docker/Dockerfile
      target: proxy
    image: {{ slug }}:proxy
    cap_add:
      - NET_BIND_SERVICE
    environment:
      SITE_ADDRESS: ${SITE_ADDRESS:-:80}
    # The only published ports of the stack (8.20-8.22).
    ports:
      - "${HTTP_PORT:-80}:80"
      - "${HTTPS_PORT:-443}:443"
      - "${HTTPS_PORT:-443}:443/udp"
    volumes:
      - caddy-data:/data
      - caddy-config:/config
    networks:
      - frontend
    deploy:
      resources:
        limits:
          memory: ${PROXY_MEMORY_LIMIT:-256m}
          pids: 64
    depends_on:
      web:
        condition: service_healthy

  # The encrypted backups, every day at BACKUP_TIME, kept
  # BACKUP_KEEP_DAYS days, each one checked after it is written, and a
  # full restore tried every week into a throwaway database (8.13).
  # Written to BACKUP_DIR on the host: copy that folder off the server.
  backup:
    <<: *backup
    volumes:
      - app-media:/media:ro
      - ${BACKUP_DIR:-../backups}:/backups

  # `python ops.py restore`: the same image, allowed to write the
  # uploaded files. Started only on demand.
  restore:
    <<: *backup
    restart: "no"
    profiles: ["restore"]
    entrypoint: ["/usr/local/bin/restore.sh"]
    command: ["--help"]
    volumes:
      - app-media:/media
      - ${BACKUP_DIR:-../backups}:/backups

networks:
  # Caddy and Daphne.
  frontend:
  # The database and Redis: no route out, nothing published (8.22).
  backend:
    internal: true
  # Mail and other servers, for the web server and the worker only.
  outbound:

volumes:
  app-logs:
  app-media:
  postgres-data:
  redis-data:
  caddy-data:
  caddy-config:
