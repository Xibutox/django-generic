"""Framework settings.

Every tunable lives here with a sane default. A project overrides any
subset of them through a single ``GENERIC`` dict in its settings::

    GENERIC = {
        "TABLE_PAGE_SIZE": 25,
        "EXPORT_MAX_ROWS": 100_000,
    }

Access them through the module level ``generic_settings`` singleton::

    from generic.conf import generic_settings

    generic_settings.TABLE_PAGE_SIZE

Values are resolved lazily and cached, and the cache is dropped whenever
Django emits ``setting_changed`` so ``override_settings`` works in tests.
"""

from __future__ import annotations

from typing import Any

from django.core.signals import setting_changed
from django.dispatch import receiver

DEFAULTS: dict[str, Any] = {
    # --- Site chrome -------------------------------------------------
    # Shown in the sidebar and appended to every page title.
    "SITE_TITLE": "Generic",
    # Sidebar brand label; defaults to SITE_TITLE.
    "SITE_HEADER": None,
    # Material Symbols name drawn in the brand tile.
    "SITE_ICON": "dataset",
    # Where the brand links to; None means the site index.
    "SITE_URL": None,
    # Offer staff a link to the Django admin in the account menu.
    "SHOW_ADMIN_LINK": True,
    # Design token overrides injected into every page, for a project
    # that wants its own colours without a stylesheet of its own:
    # {"--color-accent": "#7c3aed"}.
    "THEME": {},
    # Extra navigation groups, after the registered resources:
    # [{"title": "Reports", "items": [{"title": "Weekly", "route":
    #   "reports:weekly", "icon": "bar_chart", "permission": "..."}]}]
    "NAVIGATION": [],
    # Path of the events WebSocket. None switches the client off, for a
    # project served by a WSGI server.
    "EVENTS_WEBSOCKET_URL": "/ws/events/",
    # --- Data tables -------------------------------------------------
    # Rows returned when the client does not send ``length``.
    "TABLE_PAGE_SIZE": 15,
    # Upper bound on ``length`` so a client cannot ask for everything.
    "TABLE_MAX_PAGE_SIZE": 500,
    # ``length=-1`` is the DataTables idiom for "all rows". Allowing it
    # is convenient on small tables and dangerous on large ones.
    "TABLE_ALLOW_UNLIMITED_PAGE_SIZE": False,
    # Counting a large filtered set on every draw is expensive. Above
    # this many rows the total is estimated rather than counted.
    "TABLE_COUNT_LIMIT": None,
    # How a timestamp column is rendered in a cell.
    # None: a date-and-time cell travels as ISO in the active time zone
    # and is drawn in the reader's language (26/09/2026 09:51 in French,
    # 09/26/2026, 09:51 AM in English). A strftime format fixes the text
    # for every language instead.
    "TABLE_DATETIME_FORMAT": None,
    # --- Exports -----------------------------------------------------
    "EXPORT_CHUNK_SIZE": 2000,
    # Refuse exports beyond this many rows instead of timing out.
    "EXPORT_MAX_ROWS": 250_000,
    "EXPORT_DATE_FORMAT": "DD/MM/YYYY",
    "EXPORT_DATETIME_FORMAT": "DD/MM/YYYY HH:MM",
    # --- Scheduled mailings (generic.mailings) ------------------------
    # The Mailings screens, the list menu's entry and the dispatcher.
    "SHOW_MAILINGS": True,
    # Bytes; a larger file is not attached - the mail links the list.
    "MAILING_MAX_ATTACHMENT_SIZE": 10 * 1024 * 1024,
    # --- API tokens (generic.tokens) ----------------------------------
    # Days a new token lasts unless its owner chooses.
    "API_TOKEN_DEFAULT_DAYS": 90,
    # The longest a token may last; None allows tokens that never expire.
    "API_TOKEN_MAX_DAYS": 365,
    # Tokens one person may hold at once.
    "API_TOKEN_LIMIT_PER_USER": 10,
    # --- Imports (a resource's ``imports``) -----------------------------
    # Rows one file may hold; a resource's Import(max_rows=...) wins.
    "IMPORT_MAX_ROWS": 5000,
    # Refused before it is read, in bytes.
    "IMPORT_MAX_FILE_SIZE": 5 * 1024 * 1024,
    # Rows shown by the preview, as they will be written.
    "IMPORT_PREVIEW_ROWS": 20,
    # --- Autocomplete ------------------------------------------------
    "AUTOCOMPLETE_PAGE_SIZE": 25,
    "AUTOCOMPLETE_MIN_INPUT_LENGTH": 0,
    # --- Forms -------------------------------------------------------
    "FORM_DEFAULT_SECTION": "general",
    "FORM_RELATED_POPUP_WIDTH": 980,
    "FORM_RELATED_POPUP_HEIGHT": 760,
    # A relation field whose model has no autocomplete endpoint embeds
    # its choices in the schema - up to this many, beyond which the
    # schema would be too heavy and the field needs an endpoint.
    "FORM_CHOICES_LIMIT": 200,
    # --- Search ------------------------------------------------------
    # Results per resource in the command palette.
    "SEARCH_RESULTS_PER_RESOURCE": 5,
    # --- Events ------------------------------------------------------
    # Channel group every authenticated user is subscribed to.
    "EVENTS_BROADCAST_GROUP": "generic.broadcast",
    # Retention for stored notifications, in days. None keeps forever.
    "EVENTS_RETENTION_DAYS": 90,
    # Deliver events inside the transaction that produced them (False)
    # or once it commits (True). Committing first avoids notifying
    # clients about a row that a later rollback removes.
    "EVENTS_DISPATCH_ON_COMMIT": True,
    # --- Help, licence and changelog ---------------------------------
    # The version the frame shows, in the sidebar and on the help page.
    "VERSION": "",
    # Where the licence is. None looks for LICENSE, LICENSE.md,
    # LICENSE.txt and LICENCE at the root of the project.
    "LICENSE_FILE": None,
    # What the help page says when there is no file to read.
    "LICENSE_TEXT": "",
    # Changelogs to read, newest section first, as paths or
    # ``(label, path)`` pairs. None looks for CHANGELOG.md at the root
    # of the project and of the framework.
    "CHANGELOG_FILES": None,
    # Extra entries on the help page:
    # [{"label": "Handbook", "url": "https://...", "icon": "book",
    #   "description": "..."}]
    "HELP_LINKS": [],
    # A paragraph of the project's own, above the links.
    "HELP_TEXT": "",
    # --- Planned restarts --------------------------------------------
    # How long before the announced hour each warning goes out.
    "MAINTENANCE_REMINDER_SECONDS": 60,
    "MAINTENANCE_IMMINENT_SECONDS": 10,
    # Whether an announcement that is not a manual operation may restart
    # this server. Off means every announcement only warns people,
    # whatever the checkbox says.
    "MAINTENANCE_RESTART": True,
    # What restarting means here: a command ("systemctl restart myapp",
    # or a list of arguments). None uses the development reloader when
    # it is running, and SIGTERM otherwise - which restarts the process
    # only if systemd, Docker or a supervisor is watching it.
    "MAINTENANCE_RESTART_COMMAND": None,
    # --- Tasks ---------------------------------------------------------
    # Whether the task pages appear: the catalogue, the runs, and the
    # schedules when django-celery-beat is installed. None offers them
    # as soon as there is something to show - a declared task or the
    # scheduler - which is what a project that uses neither wants.
    "SHOW_TASKS": None,
    # How many runs the catalogue page shows under each task.
    "TASK_RECENT_RUNS": 5,
    # The dashboard's hub: cards pointing at whatever is worth going to
    # first, inside the application or outside it. Same shape as
    # site.add_shortcut(), which is the other way to declare one:
    # [{"label": "Handbook", "url": "https://...", "icon": "book",
    #   "description": "...", "group": "Elsewhere",
    #   "permission": "app.view_thing"}]
    "SHORTCUTS": [],
    # --- Signing in ----------------------------------------------------
    # Ways in that are not a password, offered on the sign-in page. The
    # framework speaks no protocol: each entry points at the address a
    # library of the project's own already serves.
    # [{"label": "Entra ID", "route": "oidc_authentication_init",
    #   "icon": "corporate_fare", "description": "Your work account."}]
    # The same thing from code is site.add_sso_provider().
    "SSO_PROVIDERS": [],
    # Whether the username and password form is offered at all. False
    # is for an organisation that allows no local passwords - and is
    # ignored when no provider is declared, because a page with no way
    # in is a locked door rather than a policy.
    "SSO_PASSWORD_LOGIN": True,
    # --- People --------------------------------------------------------
    # Whether the accounts, groups and permissions screens appear. They
    # obey the ordinary auth permissions, so most projects leave them
    # on and nobody without them sees a thing. False for a project that
    # declares its own user screens - though registering the user model
    # itself is enough, since these are only added where it is free.
    "SHOW_PEOPLE": True,
    # Whether the Messages screen appears, where whoever holds
    # generic.add_message writes to some people, or to everyone. Nobody
    # without the permission sees it.
    "SHOW_MESSAGES": True,
    # --- History -------------------------------------------------------
    # Keep a version of every record of every registered model, read
    # back by the History tab of its page. False records nothing at all,
    # anywhere; one model opts out with ``history = False`` on its
    # resource.
    "HISTORY": True,
    # Days of history to keep. None keeps everything; a number is what
    # ``generic.history.prune()`` and the ``prune_history`` command
    # delete beyond.
    "HISTORY_RETENTION_DAYS": None,
    # --- Logs ----------------------------------------------------------
    # Seconds during which the same error is mailed to ADMINS only once
    # (generic.logs.ErrorMailHandler); the next mail says how many were
    # held back. 0 mails every one.
    "ERROR_MAIL_INTERVAL": 600,
}

#: Settings holding an import path that should be resolved to an object.
IMPORT_STRINGS: frozenset[str] = frozenset()


class GenericSettings:
    """Lazy, cached accessor over ``settings.GENERIC``."""

    def __init__(
        self,
        defaults: dict[str, Any] | None = None,
        user_settings_name: str = "GENERIC",
    ) -> None:
        self.defaults = defaults if defaults is not None else DEFAULTS
        self.user_settings_name = user_settings_name
        self._cache: dict[str, Any] = {}

    @property
    def user_settings(self) -> dict[str, Any]:
        from django.conf import settings

        return getattr(settings, self.user_settings_name, {}) or {}

    def __getattr__(self, name: str) -> Any:
        if name not in self.defaults:
            raise AttributeError(
                f"'{name}' is not a setting of "
                f"{self.user_settings_name}. Known settings: "
                f"{', '.join(sorted(self.defaults))}."
            )

        if name in self._cache:
            return self._cache[name]

        value = self.user_settings.get(name, self.defaults[name])
        self._cache[name] = value

        return value

    def reload(self) -> None:
        self._cache.clear()


generic_settings = GenericSettings()


@receiver(setting_changed)
def _reload_generic_settings(
    sender: object,
    setting: str,
    **kwargs: Any,
) -> None:
    if setting == generic_settings.user_settings_name:
        generic_settings.reload()
