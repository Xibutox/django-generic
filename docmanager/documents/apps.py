from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DocumentsConfig(AppConfig):
    name = "documents"
    verbose_name = _("Documents")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from documents.wikis import keep_readers
        from generic.wiki.duplicates import wiki_duplicated

        wiki_duplicated.connect(keep_readers, dispatch_uid="documents.wikis")
