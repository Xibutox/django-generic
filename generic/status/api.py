"""The status, over REST: this server's, and each monitored server's.

``status/`` is what another server plugs in. It answers a signed-in
reader holding ``generic.view_status``, or anyone sending one of this
server's ``STATUS_TOKEN`` values in the ``X-Generic-Status-Token``
header - another server has no account here. ``status/health/`` is the
one-word answer a load balancer or a container probe asks for, open to
all and saying nothing else.
"""

from __future__ import annotations

import hmac
from typing import Any

from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework import status as http
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from generic.conf import generic_settings
from generic.openapi import framework_schema
from generic.status.checks import cache_check, database_check, worst
from generic.status.collect import snapshot
from generic.status.models import StatusServer
from generic.status.remote import TOKEN_HEADER, fetch


def may_view_status(user: Any) -> bool:
    return bool(
        user and user.is_authenticated and user.has_perm("generic.view_status")
    )


def accepted_tokens() -> list[str]:
    configured = generic_settings.STATUS_TOKEN

    if not configured:
        return []

    if isinstance(configured, str):
        configured = [configured]

    return [str(token) for token in configured if token]


def token_matches(request: Any) -> bool:
    sent = request.headers.get(TOKEN_HEADER, "")

    if not sent:
        return False

    # Every token compared, in constant time: neither the position of a
    # match nor its first wrong character shows in how long it takes.
    matched = False

    for token in accepted_tokens():
        if hmac.compare_digest(sent.encode(), token.encode()):
            matched = True

    return matched


def no_store(response: Response) -> Response:
    # A status is true for the second it was taken.
    response["Cache-Control"] = "no-store"

    return response


class StatusView(APIView):
    """This server's status: the document other servers plug in."""

    schema = framework_schema()

    permission_classes = (AllowAny,)

    def get(self, request: Any) -> Response:
        if not (token_matches(request) or may_view_status(request.user)):
            return Response(
                {"detail": gettext("You may not read the server status.")},
                status=(
                    http.HTTP_403_FORBIDDEN
                    if request.user.is_authenticated
                    or request.headers.get(TOKEN_HEADER)
                    else http.HTTP_401_UNAUTHORIZED
                ),
            )

        return no_store(Response(snapshot(request)))


class HealthView(APIView):
    """``ok`` while the databases and caches answer, 503 otherwise.

    Nothing but the word: whoever asks needs no account, so it tells
    them nothing about the server.
    """

    schema = framework_schema()

    authentication_classes = ()
    permission_classes = (AllowAny,)

    def get(self, request: Any) -> Response:
        from django.conf import settings

        checks = [database_check(alias) for alias in settings.DATABASES]
        checks += [cache_check(alias) for alias in settings.CACHES]
        level = worst(check.run()["level"] for check in checks)

        return no_store(
            Response(
                {"level": level},
                status=(
                    http.HTTP_503_SERVICE_UNAVAILABLE
                    if level == "error"
                    else http.HTTP_200_OK
                ),
            )
        )


class RemoteStatusView(APIView):
    """One monitored server's status, asked by this server."""

    schema = framework_schema()

    permission_classes = (IsAuthenticated,)

    def get(self, request: Any, pk: int) -> Response:
        if not may_view_status(request.user):
            return Response(
                {"detail": gettext("You may not read the server status.")},
                status=http.HTTP_403_FORBIDDEN,
            )

        server = get_object_or_404(StatusServer, pk=pk)

        return no_store(Response(fetch(server)))
