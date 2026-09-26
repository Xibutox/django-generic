"""Signing in through somebody else.

The framework does not speak OIDC or SAML, and should not: a project
picks a library - ``mozilla-django-oidc``, ``django-allauth``,
``djangosaml2``, a reverse proxy - and that library owns the protocol,
the keys and the callback. What the framework owns is the **door**: the
sign-in page, where the choice is offered and in what order.

So a provider is declared, not implemented. It is a label, an icon and
the address the library already serves::

    site.add_sso_provider(
        _("Microsoft Entra ID"),
        route="oidc_authentication_init",     # mozilla-django-oidc
        icon="corporate_fare",
        description=_("Use your work account."),
    )

With one declared, the sign-in page leads with it and folds the
password form away underneath; with none, the page is what it always
was. Where an organisation allows no local passwords at all,
``SSO_PASSWORD_LOGIN = False`` takes the form away entirely - except
when nothing else is offered, because a page with no way in is not a
security measure.
"""

from __future__ import annotations

import dataclasses
from typing import Any
from urllib.parse import urlencode

from django.urls import NoReverseMatch, reverse
from django.utils.encoding import force_str

from generic.sites.shortcuts import clean_url


@dataclasses.dataclass
class SsoProvider:
    """One way in, offered on the sign-in page."""

    label: Any
    url: str = ""
    route: str = ""
    icon: str = "shield_person"
    description: Any = ""
    order: int = 0
    #: What the provider's view calls the page to come back to.
    #: ``""`` sends nothing, for a library that keeps its own state.
    next_param: str = "next"

    def resolve_url(self, destination: str = "") -> str:
        """Where the button goes, carrying where the reader was going."""
        if self.url:
            base = clean_url(self.url, self.label)
        elif self.route:
            try:
                base = reverse(self.route)
            except NoReverseMatch:
                # The library is not installed in this project after
                # all: the button goes quiet rather than 500ing the one
                # page nobody can sign in without.
                return ""
        else:
            return ""

        if not base or not destination or not self.next_param:
            return base

        separator = "&" if "?" in base else "?"

        return f"{base}{separator}{urlencode({self.next_param: destination})}"

    def as_entry(self, destination: str = "") -> dict[str, Any]:
        return {
            "label": force_str(self.label),
            "description": force_str(self.description or ""),
            "icon": self.icon or "shield_person",
            "url": self.resolve_url(destination),
            "order": self.order,
        }


#: What a provider declared in ``GENERIC["SSO_PROVIDERS"]`` may say.
SETTING_KEYS = frozenset(
    {"label", "url", "route", "icon", "description", "order", "next_param"}
)


def from_setting(entries: Any) -> list[SsoProvider]:
    """``GENERIC["SSO_PROVIDERS"]`` as providers."""
    from django.core.exceptions import ImproperlyConfigured

    providers = []

    for entry in entries or ():
        if not isinstance(entry, dict) or not entry.get("label"):
            raise ImproperlyConfigured(
                "Every entry of GENERIC['SSO_PROVIDERS'] is an object "
                "with at least a label."
            )

        unknown = set(entry) - SETTING_KEYS

        if unknown:
            raise ImproperlyConfigured(
                f"GENERIC['SSO_PROVIDERS'] entry "
                f"{entry['label']!r} has no key "
                f"{', '.join(sorted(unknown))}. Known keys: "
                f"{', '.join(sorted(SETTING_KEYS))}."
            )

        providers.append(SsoProvider(**entry))

    return providers


__all__ = ["SsoProvider", "from_setting"]
