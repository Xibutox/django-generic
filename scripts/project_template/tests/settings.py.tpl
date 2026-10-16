"""The test settings: the development ones, on SQLite and in memory, so
the suite needs no service."""

from {{ project }}.settings.dev import *  # noqa: F401,F403

DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
}
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
}
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}
CELERY_BROKER_URL = "memory://"
CELERY_TASK_ALWAYS_EAGER = True
# Fast hashes: the suite signs in often.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
