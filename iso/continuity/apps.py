from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ContinuityConfig(AppConfig):
    """Business impact analysis, continuity plans and their tests.
    Needs ``iso.assets``."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "iso.continuity"
    label = "continuity"
    verbose_name = _("Continuity")
