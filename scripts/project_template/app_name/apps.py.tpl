from django.apps import AppConfig


class {{ app_class }}Config(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "{{ app }}"
