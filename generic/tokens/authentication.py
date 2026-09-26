"""Knox's authentication, with the token's scope and last use."""

from __future__ import annotations

import datetime
from typing import Any

from django.utils import timezone
from django.utils.translation import gettext
from knox.auth import TokenAuthentication as KnoxTokenAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS

#: How often ``last_used_at`` is written, at most, per token: a script
#: calling every second must not write a row every second.
USE_RESOLUTION = datetime.timedelta(minutes=1)


class TokenAuthentication(KnoxTokenAuthentication):
    """``Authorization: Token <token>``.

    Expired and revoked tokens, and tokens of inactive accounts, are
    refused by knox (401). A read-only token asking to write is refused
    here (403), whatever its owner may do on a page.
    """

    def authenticate(self, request: Any) -> Any:
        result = super().authenticate(request)

        if result is None:
            return None

        user, token = result

        if (
            getattr(token, "scope", "") == "read"
            and request.method not in SAFE_METHODS
        ):
            raise PermissionDenied(gettext("This token may only read."))

        if hasattr(token, "last_used_at"):
            self.record_use(token)

        return user, token

    @staticmethod
    def record_use(token: Any) -> None:
        now = timezone.now()

        if token.last_used_at and now - token.last_used_at < USE_RESOLUTION:
            return

        # update(): no signal, no history, no live event - using a token
        # is not a change of anything anyone watches.
        type(token).objects.filter(pk=token.pk).update(last_used_at=now)
        token.last_used_at = now
