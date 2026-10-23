from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PlannerConfig(AppConfig):
    name = "planner"
    verbose_name = _("Planner")
    default_auto_field = "django.db.models.BigAutoField"
