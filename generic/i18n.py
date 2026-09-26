"""The languages the interface is offered in.

Translation itself is Django's: ``gettext`` in Python, ``{% translate %}``
in templates, ``Generic.t()`` in JavaScript against the catalog served by
``JavaScriptCatalog``. What this module adds is the choice - which
languages a project offers, and which one a request is answered in.

A project narrows ``LANGUAGES`` to what it actually translated::

    LANGUAGES = [("en", _("English")), ("fr", _("French"))]

and the frame then shows a language menu. Left at Django's default -
every language Django itself ships - no menu is offered: a hundred
entries is not a choice.
"""

from __future__ import annotations

from typing import Any

from django.conf import global_settings, settings
from django.utils.encoding import force_str
from django.utils.translation import get_language


def offered_languages() -> list[tuple[str, str]]:
    """``(code, label)`` for each language this project offers."""
    if not settings.USE_I18N:
        return []

    languages = [
        (str(code), force_str(label)) for code, label in settings.LANGUAGES
    ]

    # Django's own list, untouched by the project: it says nothing about
    # what was translated, so there is nothing to choose from.
    if len(languages) == len(global_settings.LANGUAGES):
        return []

    return languages


def is_offered(code: Any) -> bool:
    """Whether ``code`` is one of the offered languages."""
    wanted = str(code or "")

    return any(wanted == offered for offered, _label in offered_languages())


def language_menu() -> list[dict[str, Any]]:
    """The offered languages, ready for the frame's menu.

    Empty when there is nothing to choose: one language, or a project
    that never narrowed ``LANGUAGES``.
    """
    languages = offered_languages()

    if len(languages) < 2:
        return []

    current = get_language() or ""

    return [
        {
            "code": code,
            "label": label,
            # "fr" answers for "fr-ca" as well: the label to tick is the
            # one the active language falls back to.
            "is_current": current == code
            or current.split("-")[0] == code.split("-")[0],
        }
        for code, label in languages
    ]


def preferred_language(user: Any) -> str:
    """The language a signed-in user chose, if it is still offered."""
    if user is None or not getattr(user, "is_authenticated", False):
        return ""

    from generic.accounts.models import UserPreferences

    language = UserPreferences.for_user(user).language

    return language if is_offered(language) else ""
