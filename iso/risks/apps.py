from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class RisksConfig(AppConfig):
    """The risk register. Needs ``iso.assets`` and ``iso.compliance``:
    a risk threatens assets and is treated by controls."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "iso.risks"
    label = "risks"
    verbose_name = _("Risks")
