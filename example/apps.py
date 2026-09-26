from django.apps import AppConfig


class ExampleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "example"
    verbose_name = "Support desk example"

    def ready(self) -> None:
        # Topics have to be declared before a client may subscribe.
        from example import events  # noqa: F401
