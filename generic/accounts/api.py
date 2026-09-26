"""REST endpoints for the signed-in user's own state.

Everything is scoped to ``request.user`` at the queryset level, so no
request can reach another user's preferences or saved views.
"""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.utils.translation import gettext
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from generic.accounts.models import SavedView, UserPreferences
from generic.accounts.serializers import (
    PreferencesSerializer,
    ProfileSerializer,
    SavedViewSerializer,
)
from generic.openapi import framework_schema


class SingletonFormView(APIView):
    """GET and PATCH one object belonging to the user.

    ``GET form-schema/`` on the sibling route describes the form, so the
    account page renders it with the same code as any resource form.
    """

    schema = framework_schema()

    serializer_class: Any = None
    permission_classes = (IsAuthenticated,)

    def get_object(self) -> Any:
        raise NotImplementedError

    def get_serializer(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("context", {"request": self.request})

        return self.serializer_class(*args, **kwargs)

    def get(self, request: Any) -> Response:
        return Response(self.get_serializer(self.get_object()).data)

    def patch(self, request: Any) -> Response:
        serializer = self.get_serializer(
            self.get_object(),
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data)


class FormSchemaView(APIView):
    """The form schema of a serializer, for a singleton form."""

    schema = framework_schema()

    serializer_class: Any = None
    permission_classes = (IsAuthenticated,)

    def get(self, request: Any) -> Response:
        schema = self.serializer_class.get_form_schema(request=request)
        schema.update(
            {
                "mode": "update",
                "inlines": [],
                "submitLabel": gettext("Save"),
            }
        )

        return Response(schema)


class PreferencesView(SingletonFormView):
    serializer_class = PreferencesSerializer

    def get_object(self) -> UserPreferences:
        return UserPreferences.for_user(self.request.user)


class ProfileView(SingletonFormView):
    serializer_class = ProfileSerializer

    def get_object(self) -> Any:
        return self.request.user


class SavedViewViewSet(viewsets.ModelViewSet):
    """Named table layouts: ``?table=<state key>`` lists one table's."""

    serializer_class = SavedViewSerializer

    #: Read by the API description, which cannot ask get_queryset() -
    #: it has no signed-in user. Every request goes through it anyway.
    queryset = SavedView.objects.none()
    permission_classes = (IsAuthenticated,)
    pagination_class = None

    def get_queryset(self) -> QuerySet:
        queryset = SavedView.objects.filter(user=self.request.user)
        table = self.request.query_params.get("table")

        if table:
            queryset = queryset.filter(table=table)

        return queryset

    def clear_other_defaults(self, saved: SavedView) -> None:
        if saved.is_default:
            SavedView.objects.filter(
                user=saved.user,
                table=saved.table,
                is_default=True,
            ).exclude(pk=saved.pk).update(is_default=False)

    def perform_create(self, serializer: Any) -> None:
        saved = serializer.save(user=self.request.user)
        self.clear_other_defaults(saved)

    def perform_update(self, serializer: Any) -> None:
        saved = serializer.save()
        self.clear_other_defaults(saved)
