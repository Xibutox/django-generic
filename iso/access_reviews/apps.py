from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AccessReviewsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "iso.access_reviews"
    label = "access_reviews"
    verbose_name = _("Access reviews")
