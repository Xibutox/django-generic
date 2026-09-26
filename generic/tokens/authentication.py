"""Knox's authentication, over ``ApiToken``, with its scope and last use."""

from __future__ import annotations

import binascii
import datetime
from hmac import compare_digest
from typing import Any

from django.utils import timezone
from django.utils.translation import gettext
from knox.auth import TokenAuthentication as KnoxTokenAuthentication
from knox.crypto import hash_token
from knox.settings import CONSTANTS
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
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

    def authenticate_credentials(self, token: bytes) -> Any:
        """The ``ApiToken`` this token is, as knox finds its own.

        Candidates share the token's first characters; the hash decides,
        compared in constant time. An expired one is deleted on the way.
        """
        from generic.tokens.models import ApiToken

        message = gettext("Invalid token.")
        text = token.decode("utf-8")
        candidates = ApiToken.objects.filter(
            token_key=text[: CONSTANTS.TOKEN_KEY_LENGTH]
        ).select_related("user")

        for candidate in candidates:
            if candidate.expiry is not None and candidate.expiry < (
                timezone.now()
            ):
                candidate.delete()
                continue

            try:
                digest = hash_token(text)
            except (TypeError, binascii.Error):
                raise AuthenticationFailed(message)

            if compare_digest(digest, candidate.digest):
                return self.validate_user(candidate)

        raise AuthenticationFailed(message)

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
