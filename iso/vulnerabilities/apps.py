from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class VulnerabilitiesConfig(AppConfig):
    """The vulnerability register. Needs ``iso.assets``."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "iso.vulnerabilities"
    label = "vulnerabilities"
    verbose_name = _("Vulnerabilities")
