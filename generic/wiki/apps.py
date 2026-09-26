from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class WikiConfig(AppConfig):
    name = "generic.wiki"
    label = "generic_wiki"
    verbose_name = _("Wiki")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # The sidebar link, the pinned pages on the dashboard and the
        # command palette results.
        from generic.sites import site
        from generic.wiki.integration import connect

        connect(site)
