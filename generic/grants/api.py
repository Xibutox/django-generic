"""Asking for a right given on request, over REST.

``GET`` says where the signed-in person stands with each right;
``POST {"kind", "message", "page"}`` asks for one - or asks again,
which reminds the people who decide, no more than once an
``ACCESS_REQUEST_INTERVAL``.
"""

from __future__ import annotations

from typing import Any

from django.utils import formats, timezone
from django.utils.translation import gettext
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from generic import grants
from generic.openapi import framework_schema


class AskSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=())
    message = serializers.CharField(
        required=False, allow_blank=True, max_length=2000
    )
    page = serializers.CharField(
        required=False, allow_blank=True, max_length=500
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = grants.gated()

    def validate_page(self, value: str) -> str:
        # A path of this site only: it becomes a link in a notification.
        return value if value.startswith("/") else ""


class AccessRequestView(APIView):
    """The signed-in person's rights given on request."""

    schema = framework_schema()

    permission_classes = (IsAuthenticated,)

    def get(self, request: Any) -> Response:
        return Response({"rights": grants.state(request.user)})

    def post(self, request: Any) -> Response:
        serializer = AskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            access_request, created = grants.ask(
                request.user,
                data["kind"],
                message=data.get("message", ""),
                page=data.get("page", ""),
            )
        except grants.AlreadyHeld:
            return Response(
                {"detail": gettext("You already have this permission.")},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except grants.TooSoon as error:
            when = formats.time_format(
                timezone.localtime(error.retry_at), "TIME_FORMAT"
            )

            return Response(
                {
                    "detail": gettext(
                        "You asked a short while ago. From %(time)s, you "
                        "can remind the administrators."
                    )
                    % {"time": when},
                    "retryAt": error.retry_at.isoformat(),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        return Response(
            {
                "created": created,
                "detail": (
                    gettext(
                        "Your request was sent. You will be told when an "
                        "administrator has answered."
                    )
                    if created
                    else gettext(
                        "The administrators were reminded of your request."
                    )
                ),
                "rights": grants.state(request.user),
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
