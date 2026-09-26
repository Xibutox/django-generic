"""The wiki's REST endpoint.

================================  ====================================
``GET    pages/``                  the menu: every page, no content
``POST   pages/``                  a new page
``GET    pages/<id>/``             one page, with its content
``PATCH  pages/<id>/``             change it; ``version`` guards it
``DELETE pages/<id>/``             delete it; its subpages move up
``GET    pages/<id>/revisions/``   its earlier versions
``POST   pages/<id>/restore/``     bring one back: ``{"revision"}``
================================  ====================================

Reading is for any signed-in user; writing needs the model permissions
``add``, ``change`` and ``delete`` on wiki pages.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response

from generic.wiki.models import WikiPage, WikiRevision
from generic.wiki.serializers import (
    WikiPageListSerializer,
    WikiPageSerializer,
    WikiRevisionSerializer,
)

#: HTTP method -> the permission a write needs.
WRITE_PERMISSIONS = {
    "POST": "add",
    "PUT": "change",
    "PATCH": "change",
    "DELETE": "delete",
}


def can(user: Any, action_name: str) -> bool:
    return bool(
        user
        and user.is_authenticated
        and user.has_perm(f"generic_wiki.{action_name}_wikipage")
    )


class WikiPermission(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        user = request.user

        if not (user and user.is_authenticated):
            return False

        if request.method in SAFE_METHODS:
            return True

        # Restoring a version changes the page.
        if view.action == "restore":
            return can(user, "change")

        return can(user, WRITE_PERMISSIONS.get(request.method, "change"))


class WikiPageViewSet(viewsets.ModelViewSet):
    permission_classes = (WikiPermission,)
    pagination_class = None

    def get_queryset(self) -> Any:
        return WikiPage.objects.select_related("updated_by").order_by(
            "position", "title"
        )

    def get_serializer_class(self) -> Any:
        if self.action == "list":
            return WikiPageListSerializer

        return WikiPageSerializer

    def perform_create(self, serializer: Any) -> None:
        user = self.request.user
        serializer.save(created_by=user, updated_by=user)

    def perform_update(self, serializer: Any) -> None:
        page = serializer.instance
        before = WikiPage(
            pk=page.pk,
            title=page.title,
            content=page.content,
            updated_at=page.updated_at,
            updated_by_id=page.updated_by_id,
        )

        with transaction.atomic():
            saved = serializer.save(updated_by=self.request.user)

            # A version is kept when the words change, not when the page
            # only moves in the menu.
            if (saved.title, saved.content) != (before.title, before.content):
                WikiRevision.keep(before)

    @action(detail=True, methods=["get"])
    def revisions(self, request: Any, pk: Any = None) -> Response:
        page = self.get_object()
        serializer = WikiRevisionSerializer(page.revisions.all(), many=True)

        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def restore(self, request: Any, pk: Any = None) -> Response:
        page = self.get_object()
        revision = get_object_or_404(
            page.revisions,
            pk=request.data.get("revision"),
        )

        with transaction.atomic():
            # The current text becomes a version too: restoring can be
            # undone like any other change.
            WikiRevision.keep(page)
            page.title = revision.title
            page.content = revision.content
            page.updated_by = request.user
            page.save()

        return Response(
            WikiPageSerializer(page, context={"request": request}).data
        )
