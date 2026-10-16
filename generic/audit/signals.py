"""Django's own sign-in signals, and the API tokens' lifetime, recorded.

Imported by ``GenericConfig.ready()``. Every way of signing in sends
``user_logged_in`` - the password form, an SSO provider, ``login()``
in a project's view - so every one is recorded; ``user_login_failed``
carries the name typed, never the password (Django cleans the
credentials before sending them).
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from generic.audit import record


@receiver(user_logged_in, dispatch_uid="generic.audit.signed_in")
def signed_in(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    backend = getattr(user, "backend", "") or ""
    record("signed_in", request=request, user=user, detail=backend)


@receiver(user_logged_out, dispatch_uid="generic.audit.signed_out")
def signed_out(
    sender: Any, request: Any, user: Any = None, **kwargs: Any
) -> None:
    if user is None:
        return

    record("signed_out", request=request, user=user)


@receiver(user_login_failed, dispatch_uid="generic.audit.failed")
def failed(
    sender: Any,
    credentials: dict[str, Any],
    request: Any = None,
    **kwargs: Any,
) -> None:
    from django.contrib.auth import get_user_model

    User = get_user_model()
    username = str(
        credentials.get(User.USERNAME_FIELD)
        or credentials.get("username")
        or ""
    )
    account = User._default_manager.filter(
        **{User.USERNAME_FIELD: username}
    ).first()

    # Anonymous: the request's user is nobody yet.
    record(
        "sign_in_failed",
        request=request,
        user=account,
        username=username,
    )


def token_saved(
    sender: Any, instance: Any, created: bool = False, **kwargs: Any
) -> None:
    from generic.history.actor import current_actor

    if created:
        record(
            "token_created",
            user=instance.user,
            actor=current_actor().person(),
            detail=getattr(instance, "name", "") or "",
        )


def token_deleted(sender: Any, instance: Any, **kwargs: Any) -> None:
    from django.utils import timezone

    from generic.history.actor import current_actor

    expiry = getattr(instance, "expiry", None)
    name = getattr(instance, "name", "") or ""

    record(
        "token_deleted",
        user=getattr(instance, "user", None),
        actor=current_actor().person(),
        detail=(
            f"{name} (expired)"
            if expiry is not None and expiry <= timezone.now()
            else name
        ),
    )


def connect_tokens() -> None:
    """The API tokens, when ``generic.tokens`` is installed."""
    from django.apps import apps

    if not apps.is_installed("generic.tokens"):
        return

    from generic.tokens.models import ApiToken

    post_save.connect(
        token_saved, sender=ApiToken, dispatch_uid="generic.audit.token"
    )
    post_delete.connect(
        token_deleted,
        sender=ApiToken,
        dispatch_uid="generic.audit.token_deleted",
    )
