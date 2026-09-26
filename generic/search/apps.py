from typing import Any

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SearchConfig(AppConfig):
    name = "generic.search"
    label = "generic_search"
    verbose_name = _("Search")

    def ready(self) -> None:
        from django.db.backends.signals import connection_created
        from django.db.models import Field

        from generic.search.lookups import Unaccented

        # On every field, not only text: a search field may walk to a
        # number or a code, which icontains already reads as text.
        Field.register_lookup(Unaccented)
        connection_created.connect(
            add_sqlite_function, dispatch_uid="generic.search.sqlite"
        )

        # A connection opened before the app was ready - the test
        # runner's, for one - never sent the signal.
        from django.db import connections

        for connection in connections.all(initialized_only=True):
            if connection.connection is not None:
                add_sqlite_function(connection.vendor, connection)


def add_sqlite_function(sender: Any, connection: Any, **kwargs: Any) -> None:
    """Give SQLite the function PostgreSQL gets from the migration."""
    if connection.vendor != "sqlite":
        return

    from generic.search import FUNCTION, fold

    connection.connection.create_function(
        FUNCTION, 1, fold, deterministic=True
    )
