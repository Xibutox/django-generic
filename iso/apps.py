from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IsoConfig(AppConfig):
    """What the ISO apps share: helpers, the demo data command."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "iso"
    verbose_name = _("ISO 27001")
