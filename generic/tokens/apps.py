from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class TokensConfig(AppConfig):
    name = "generic.tokens"
    label = "generic_tokens"
    verbose_name = _("API tokens")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from generic.tokens import checks  # noqa: F401
        from generic.tokens.resources import register_screens

        register_screens()
