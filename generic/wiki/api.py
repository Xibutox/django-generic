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

The editor's images are uploaded to ``api/generic/wiki/images/`` - in
``generic.urls``, beside the framework's other endpoints - by whoever
may write a page (:class:`WikiImageUploadView`), and shown from the
wiki's own ``images/<id>/`` (``generic.wiki.views.WikiImageView``).
Its other files - a PDF, a spreadsheet - go to
``api/generic/wiki/files/`` (:class:`WikiFileUploadView`) and are
downloaded from ``files/<id>/``.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Any

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from generic.conf import generic_settings
from generic.openapi import framework_schema
from generic.wiki.models import WikiFile, WikiImage, WikiPage, WikiRevision
from generic.wiki.serializers import (
    WikiPageListSerializer,
    WikiPageSerializer,
    WikiRevisionSerializer,
)

#: The images a page may show: what their first bytes are, the name
#: they are stored under, and the names they may arrive with. Nothing
#: else - no SVG, which is a document that can hold a script.
IMAGE_KINDS = (
    ("png", "image/png", ("png",)),
    ("jpg", "image/jpeg", ("jpg", "jpeg")),
    ("gif", "image/gif", ("gif",)),
    ("webp", "image/webp", ("webp",)),
)

#: Every extension an uploaded image may carry.
IMAGE_EXTENSIONS = frozenset(
    name for _stored, _type, names in IMAGE_KINDS for name in names
)

#: Content type of a stored image, by the extension it was stored with.
IMAGE_TYPES = {stored: content_type for stored, content_type, _ in IMAGE_KINDS}


def sniff_image(head: bytes) -> str | None:
    """The stored extension of the image ``head`` begins, or ``None``.

    Read from the bytes, never from the name: a page saved as
    ``photo.png`` is still a page.
    """
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"

    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"

    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"

    return None


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


class WikiImagePermission(BasePermission):
    """Whoever may write a page - add one or change one - may add an
    image to it."""

    def has_permission(self, request: Any, view: Any) -> bool:
        user = request.user

        return bool(
            user
            and user.is_authenticated
            and (can(user, "add") or can(user, "change"))
        )


class WikiImageUploadView(APIView):
    """``POST`` one image - multipart, part ``file`` - for a page.

    PNG, JPEG, GIF or WebP, told by its extension and by its first
    bytes, up to ``FILE_MAX_SIZE``. Answers ``{"id", "url"}``: ``url``
    is the image's address under the wiki, where every signed-in reader
    of the wiki may see it, and what the editor puts in the page.
    """

    schema = framework_schema()
    #: What generic.openapi describes this body as.
    openapi_request = "wiki_image_upload"
    permission_classes = (WikiImagePermission,)
    parser_classes = (MultiPartParser,)

    def post(self, request: Any) -> Response:
        upload = request.FILES.get("file")

        if upload is None:
            return self.refuse(gettext("Choose an image to upload."))

        extension = PurePath(upload.name).suffix.lower().lstrip(".")

        if extension not in IMAGE_EXTENSIONS:
            return self.refuse(
                gettext("Only PNG, JPEG, GIF and WebP images can be added.")
            )

        limit = generic_settings.FILE_MAX_SIZE

        if limit and upload.size > limit:
            return self.refuse(
                gettext("The image is too large: at most %(limit)s.")
                % {"limit": filesizeformat(limit)}
            )

        head = upload.read(16)
        upload.seek(0)
        stored = sniff_image(head)

        if stored is None:
            return self.refuse(
                gettext("This file is not a PNG, JPEG, GIF or WebP image.")
            )

        stem = PurePath(upload.name).stem or "image"
        image = WikiImage(
            original_name=upload.name[:255],
            uploaded_by=request.user,
        )
        # Stored under the extension its bytes say, whatever it was
        # called: that is the type it is served as.
        image.file.save(f"{stem}.{stored}", upload, save=False)
        image.save()

        return Response(
            {"id": image.pk, "url": image.get_absolute_url()},
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def refuse(message: str) -> Response:
        return Response(
            {"detail": message}, status=status.HTTP_400_BAD_REQUEST
        )


class WikiFileUploadView(APIView):
    """``POST`` one file - multipart, part ``file`` - for a page.

    Any kind of file, up to ``FILE_MAX_SIZE``: it is only ever
    downloaded, never shown in the browser (see
    ``generic.wiki.views.WikiFileView``). Answers ``{"id", "url",
    "name", "size"}``, what the editor's file block shows.
    """

    schema = framework_schema()
    #: What generic.openapi describes this body as.
    openapi_request = "wiki_file_upload"
    permission_classes = (WikiImagePermission,)
    parser_classes = (MultiPartParser,)

    def post(self, request: Any) -> Response:
        upload = request.FILES.get("file")

        if upload is None or not upload.name:
            return WikiImageUploadView.refuse(
                gettext("Choose a file to upload.")
            )

        if not upload.size:
            return WikiImageUploadView.refuse(gettext("The file is empty."))

        limit = generic_settings.FILE_MAX_SIZE

        if limit and upload.size > limit:
            return WikiImageUploadView.refuse(
                gettext("The file is too large: at most %(limit)s.")
                % {"limit": filesizeformat(limit)}
            )

        name = PurePath(upload.name.replace("\\", "/")).name[:255]
        attachment = WikiFile(
            original_name=name,
            size=upload.size,
            uploaded_by=request.user,
        )
        attachment.file.save(name or "file", upload, save=False)
        attachment.save()

        return Response(
            {
                "id": attachment.pk,
                "url": attachment.get_absolute_url(),
                "name": attachment.original_name,
                "size": attachment.size,
            },
            status=status.HTTP_201_CREATED,
        )
