from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DocxConfig(AppConfig):
    name = "generic.docx"
    label = "generic_docx"
    verbose_name = _("Word files")

    def ready(self) -> None:
        # The page in the sidebar, for whoever may merge.
        from generic.docx.permissions import may_merge
        from generic.sites import site

        site.add_link(
            _("Merge Word files"),
            route="generic_docx:merge",
            icon="merge_type",
            order=10,
            permission=may_merge,
        )
