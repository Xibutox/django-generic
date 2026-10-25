from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IncidentsConfig(AppConfig):
    """Incidents. Needs ``iso.assets``: an incident touches assets."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "iso.incidents"
    label = "incidents"
    verbose_name = _("Incidents")
