"""Production: every secret and address from the environment.

``asgi.py`` and ``wsgi.py`` use this module unless told otherwise, so a
server started without ``DJANGO_SETTINGS_MODULE`` never runs with
DEBUG on. It refuses to start without what it cannot guess - the
secret key, the host names, the database, Redis - rather than falling
back to a development value and running unsafely.

``docker/prod.env.example`` lists every variable. What is not here is
as deliberate: no Debug Toolbar, no SQLite, no in-memory channel layer,
no task run inside the request that sends it.
"""

from .base import *  # noqa: F401,F403
from .base import (
    GENERIC,
    database_from_url,
    env,
    env_bool,
    env_int,
    env_list,
    env_required,
    mail_settings,
    redis_backends,
)

DEBUG = False
SECRET_KEY = env_required("DJANGO_SECRET_KEY")
#: The names the site answers to: desk.example.com,www.desk.example.com
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS") or env_required(
    "DJANGO_ALLOWED_HOSTS"
)
#: Full origins, scheme included: https://desk.example.com. Needed when
#: a form is posted from an origin Django cannot infer from the request.
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# -- Database ----------------------------------------------------------
#
# Postgres. No persistent connections: under an ASGI server each
# request may run on a different thread, and a connection kept open by
# one is never reused by the next - Django's own advice is to leave
# CONN_MAX_AGE at 0 there, or pool in front of the database.

DATABASES = {"default": database_from_url(env_required("DATABASE_URL"))}

# -- Events, cache, tasks ----------------------------------------------
#
# Redis for all three: the events have to reach every web process, the
# cache has to be shared by them, and the tasks run in a worker.

REDIS_URL = env_required("REDIS_URL")
CHANNEL_LAYERS, CACHES = redis_backends(REDIS_URL)

CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = False

# -- Static files ------------------------------------------------------
#
# Collected into STATIC_ROOT when the image is built, and served by the
# web server in front (docker/Caddyfile) rather than by Django. Every
# name carries a hash of its content, so they can be cached for good
# and a new release is never half-served from a stale browser cache.

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
        ),
    },
}

# -- HTTPS -------------------------------------------------------------
#
# DJANGO_HTTPS=1 - the default - says the site is served over HTTPS,
# which the proxy in front terminates and reports in X-Forwarded-Proto.
# Set it to 0 only to try the production stack on http://localhost:
# secure cookies are never sent back over plain HTTP, so signing in
# would silently fail.

HTTPS = env_bool("DJANGO_HTTPS", True)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = HTTPS
CSRF_COOKIE_SECURE = HTTPS
SECURE_SSL_REDIRECT = HTTPS
# One hour to start with. Once HTTPS is known to work everywhere the
# site is reached, raise it (a year is 31536000): a browser that has
# seen the header refuses plain HTTP for that long, whatever happens.
SECURE_HSTS_SECONDS = env_int("DJANGO_HSTS_SECONDS", 3600 if HTTPS else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_SUBDOMAINS")
SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD")
# Both are promises about domains this project does not own - every
# subdomain, and the browsers' built-in list - so they are asked for,
# never assumed. Left off, that is a decision, not an oversight, and
# `check --deploy` stays quiet so that a warning there still means one.
SILENCED_SYSTEM_CHECKS = [
    check
    for check, decided in (
        ("security.W005", SECURE_HSTS_INCLUDE_SUBDOMAINS),
        ("security.W021", SECURE_HSTS_PRELOAD),
    )
    if not decided and SECURE_HSTS_SECONDS
]
# CSRF_COOKIE_HTTPONLY stays False: the pages read the token from the
# cookie to send it with every API call.

# -- Mail --------------------------------------------------------------
#
# The notifications that go by mail. Without EMAIL_HOST they are
# written to the log instead of being lost. The variables keep the
# names of Django's old settings; the settings they become - MAILERS
# from Django 6.1, EMAIL_* before - are mail_settings' choice (base.py).

if env("EMAIL_HOST"):
    globals().update(
        mail_settings(
            "django.core.mail.backends.smtp.EmailBackend",
            host=env("EMAIL_HOST"),
            port=env_int("EMAIL_PORT", 587),
            username=env("EMAIL_HOST_USER"),
            password=env("EMAIL_HOST_PASSWORD"),
            use_tls=env_bool("EMAIL_USE_TLS", True),
        )
    )
else:
    globals().update(
        mail_settings("django.core.mail.backends.console.EmailBackend")
    )
    # The log is a decision too, like the HSTS ones above. Django 6.1's
    # deployment check calls the console a development backend
    # (mail.E001); here standard output is the log that keeps them.
    SILENCED_SYSTEM_CHECKS = [*SILENCED_SYSTEM_CHECKS, "mail.E001"]

DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL", "webmaster@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# The address in the links those mails carry: without it, a mail says
# "/example/ticket/12/" and no one can click it.
GENERIC = {**GENERIC, "SITE_URL": env("DJANGO_SITE_URL") or None}

# -- Logging -----------------------------------------------------------
#
# To standard output, one line per record: the container runtime keeps
# it (`docker compose logs web`). Errors carry their traceback there,
# since nobody reads a DEBUG page in production.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "line": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "line"},
    },
    "root": {
        "handlers": ["console"],
        "level": env("DJANGO_LOG_LEVEL", "INFO"),
    },
    "loggers": {
        # Every refused host name would be an error line otherwise, and
        # the internet sends plenty.
        "django.security.DisallowedHost": {
            "handlers": ["console"],
            "level": "CRITICAL",
            "propagate": False,
        },
    },
}
