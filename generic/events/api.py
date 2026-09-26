"""REST endpoints for stored notifications.

The socket carries live events; these endpoints carry the history, the
unread badge, and the read/unread transitions. A client that missed
events while offline catches up here.
"""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from generic.api.filters import DATATABLE_FILTER_BACKENDS
from generic.api.pagination import DataTablesPagination
from generic.api.renderers import DataTablesRenderer, GenericJSONRenderer
from generic.events.models import Notification
from generic.events.serializers import NotificationSerializer


class NotificationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """The signed in user's own notifications.

    Scoped to ``request.user`` at the queryset level rather than through
    a permission check, so no action can reach somebody else's rows.
    """

    serializer_class = NotificationSerializer

    #: Read by the API description, which cannot ask get_queryset() -
    #: it has no signed-in user. Every request goes through it anyway.
    queryset = Notification.objects.none()
    permission_classes = (IsAuthenticated,)
    filter_backends = DATATABLE_FILTER_BACKENDS
    pagination_class = DataTablesPagination
    renderer_classes = (GenericJSONRenderer, DataTablesRenderer)

    def get_queryset(self) -> QuerySet:
        return Notification.objects.for_user(self.request.user)

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request: Any) -> Response:
        return Response({"unread": self.get_queryset().unread().count()})

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        notification = self.get_object()
        notification.mark_read()

        return Response(self.get_serializer(notification).data)

    @action(detail=True, methods=["post"], url_path="unread")
    def mark_unread(
        self,
        request: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        notification = self.get_object()
        notification.mark_unread()

        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def mark_all_read(self, request: Any) -> Response:
        updated = self.get_queryset().mark_read()

        # A bulk update bypasses post_save, so tell the other tabs
        # explicitly instead of leaving their badge stale.
        from generic.events.bus import Event, publish

        publish(
            Event(
                type="notification.read_all",
                payload={"count": updated},
            ),
            users=[request.user.pk],
        )

        return Response(
            {"updated": updated},
            status=status.HTTP_200_OK,
        )
