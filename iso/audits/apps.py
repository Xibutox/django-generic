from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AuditsConfig(AppConfig):
    """Audits and nonconformities. Needs ``iso.compliance``: a finding
    names the control it is about."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "iso.audits"
    label = "audits"
    verbose_name = _("Audits")
