"""``api/generic/tokens/``: a person's own tokens, from the account page.

Session only: a token cannot mint tokens, so one leaked token cannot
become ten.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.translation import gettext
from rest_framework import mixins, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from generic.conf import generic_settings
from generic.tokens.models import ApiToken
from generic.tokens.serializers import ApiTokenSerializer

ADD = "generic_tokens.add_apitoken"


class ApiTokenViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ApiTokenSerializer

    #: Read by the API description, which cannot ask get_queryset() -
    #: it has no signed-in user. Every request goes through it anyway.
    queryset = ApiToken.objects.none()
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    pagination_class = None

    def get_queryset(self) -> Any:
        return ApiToken.objects.filter(user=self.request.user)

    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        if not request.user.has_perm(ADD):
            return Response(
                {"detail": gettext("You may not create API tokens.")},
                status=status.HTTP_403_FORBIDDEN,
            )

        limit = generic_settings.API_TOKEN_LIMIT_PER_USER

        if limit and self.get_queryset().count() >= limit:
            return Response(
                {
                    "detail": gettext(
                        "You have %(count)s tokens already: revoke one "
                        "first."
                    )
                    % {"count": limit}
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("days", None)

        with transaction.atomic():
            instance, token = ApiToken.objects.create(
                user=request.user, expiry=serializer.expiry_of(), **data
            )

        body = ApiTokenSerializer(instance).data
        # The only time it is ever sent: knox keeps a hash of it.
        body["token"] = token

        return Response(body, status=status.HTTP_201_CREATED)
