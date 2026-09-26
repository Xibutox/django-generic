"""What ``generic.tokens`` needs from a project's settings."""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.conf import settings
from django.core import checks

AUTHENTICATION = "generic.tokens.authentication.TokenAuthentication"


@checks.register()
def check_tokens(app_configs: Any = None, **kwargs: Any) -> list:
    messages = []

    if not apps.is_installed("knox"):
        messages.append(
            checks.Error(
                "generic.tokens is installed but knox is not: the tokens "
                "have nowhere to keep their hash.",
                hint="pip install 'django-generic[api]' and add 'knox' to "
                "INSTALLED_APPS. See docs/api.md.",
                id="generic.E006",
            )
        )

    classes = getattr(settings, "REST_FRAMEWORK", {}).get(
        "DEFAULT_AUTHENTICATION_CLASSES", ()
    )

    if AUTHENTICATION not in classes:
        messages.append(
            checks.Warning(
                "generic.tokens is installed but the REST API does not "
                "accept its tokens: every call with one is refused.",
                hint=f"Add '{AUTHENTICATION}' to REST_FRAMEWORK"
                "['DEFAULT_AUTHENTICATION_CLASSES']. See docs/api.md.",
                id="generic.W008",
            )
        )

    return messages
