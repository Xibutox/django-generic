"""Announcing and calling off a restart, over REST.

Both need the model permissions of the announcement, so the right to
take a server down is granted like any other right in the project.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from generic.maintenance.models import RestartAnnouncement
from generic.maintenance.scheduler import announce_restart, cancel_restart
from generic.maintenance.serializers import RestartAnnouncementSerializer


def may_announce(user: Any) -> bool:
    return bool(
        user
        and user.is_authenticated
        and user.has_perm("generic.add_restartannouncement")
    )


class RestartAnnouncementView(APIView):
    """The current announcement: read it, make one, call it off."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Any) -> Response:
        """What every page draws its banner from."""
        announcement = RestartAnnouncement.objects.current()

        return Response(
            {
                "announcement": (
                    announcement.as_client() if announcement else None
                ),
                "canAnnounce": may_announce(request.user),
            }
        )

    def post(self, request: Any) -> Response:
        if not may_announce(request.user):
            return Response(
                {"detail": gettext("You may not announce a restart.")},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = RestartAnnouncementSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        announcement = announce_restart(
            created_by=request.user,
            **serializer.validated_data,
        )

        return Response(
            announcement.as_client(),
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request: Any) -> Response:
        """Call off whatever is planned."""
        if not may_announce(request.user):
            return Response(
                {"detail": gettext("You may not announce a restart.")},
                status=status.HTTP_403_FORBIDDEN,
            )

        announcement = RestartAnnouncement.objects.current()

        if announcement is None:
            return Response(
                {"detail": gettext("Nothing is planned.")},
                status=status.HTTP_404_NOT_FOUND,
            )

        cancel_restart(announcement)

        return Response(announcement.as_client("cancelled"))


class RestartFormSchemaView(APIView):
    """The announcement form, described for the page that draws it."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Any) -> Response:
        schema = RestartAnnouncementSerializer.get_form_schema(request=request)
        schema.update(
            {
                "mode": "create",
                "inlines": [],
                "submitLabel": gettext("Announce the restart"),
            }
        )

        return Response(schema)
