"""Reading and changing the help settings, over REST.

Changing them needs the model's change permission, so the right to
point everyone at a ticket service is granted like any other right in
the project.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from django.utils.translation import gettext
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from generic.conf import generic_settings
from generic.help.models import HelpSettings, safe_link
from generic.help.serializers import HelpSettingsSerializer
from generic.openapi import framework_schema


def may_change_settings(user: Any) -> bool:
    return bool(
        user
        and user.is_authenticated
        and user.has_perm("generic.change_helpsettings")
    )


class HelpSettingsView(APIView):
    """The one row of help settings: read it, change it."""

    schema = framework_schema()

    permission_classes = (IsAuthenticated,)

    def get(self, request: Any) -> Response:
        return Response(HelpSettingsSerializer(HelpSettings.current()).data)

    def patch(self, request: Any) -> Response:
        if not may_change_settings(request.user):
            return Response(
                {"detail": gettext("You may not change the help settings.")},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = HelpSettingsSerializer(
            HelpSettings.current(),
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user, updated_at=timezone.now())

        return Response(serializer.data)


class HelpSettingsFormSchemaView(APIView):
    """The settings form, described for the help page that draws it."""

    schema = framework_schema()

    permission_classes = (IsAuthenticated,)

    def get(self, request: Any) -> Response:
        schema = HelpSettingsSerializer.get_form_schema(request=request)
        default = safe_link(generic_settings.BUG_REPORT_URL)

        for field in schema.get("fields", ()):
            if default and field.get("name") == "bug_report_url":
                field["placeholder"] = default

        schema.update(
            {
                "mode": "update",
                "inlines": [],
                "submitLabel": gettext("Save"),
            }
        )

        return Response(schema)
