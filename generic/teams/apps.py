from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class TeamsConfig(AppConfig):
    name = "generic.teams"
    label = "generic_teams"
    verbose_name = _("Teams")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from generic.teams.resources import register_screens

        register_screens()
