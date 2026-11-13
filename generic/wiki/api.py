"""The wiki's REST endpoint.

================================  ====================================
``GET    wikis/``                  the wikis, with their page counts
``POST   wikis/``                  a new wiki
``PATCH  wikis/<id>/``             rename it, describe it, move it
``DELETE wikis/<id>/``             to the trash, with its pages
``POST   wikis/<id>/duplicate/``   a copy: ``{"name", "description",
                                   "pages"}``
``POST   wikis/import/``           a new wiki from an archive
                                   (multipart ``file``, ``name``)
``GET    wikis/<id>/members/``     its access, owner and members
``PUT    wikis/<id>/members/``     replace them: ``{"access",
                                   "members", "owner"}``
``GET    wikis/<id>/candidates/``  people and groups for ``?q=``
``GET    wikis/trash/``            the wikis in the trash
``POST   wikis/<id>/undelete/``    out of the trash
``POST   wikis/<id>/purge/``       deleted for good
``GET    pages/``                  the menu: every page, no content;
                                   ``?wiki=<id>`` for one wiki's
``POST   pages/``                  a new page, in ``wiki``
``GET    pages/<id>/``             one page, with its content
``PATCH  pages/<id>/``             change it; ``version`` guards it
``DELETE pages/<id>/``             to the trash; its subpages move up
``GET    pages/trash/?wiki=<id>``  a wiki's pages in the trash
``POST   pages/<id>/undelete/``    out of the trash
``POST   pages/<id>/purge/``       deleted for good
``GET    pages/<id>/diff/``        what changed: ``?from=&to=``
``POST   pages/<id>/diff/``        ... to a text sent: ``{"content"}``
``GET    pages/<id>/revisions/``   its versions; ``current`` marks
                                   the one it was restored to
``POST   pages/<id>/restore/``     bring one back: ``{"revision"}``
``POST   pages/<id>/duplicate/``   a copy beside it: ``{"title",
                                   "subpages"}``
================================  ====================================

Reading is for any signed-in user, in the wikis
``Wiki.objects.readable_by`` lets them see; writing a page is for a
wiki's editors, managers and owner - and, in an open wiki, for whoever
holds the model permissions ``add``, ``change`` and ``delete`` on wiki
pages (``generic.wiki.access``).

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

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import FieldDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.template.defaultfilters import filesizeformat
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from generic.api.body import ObjectBodyMixin
from generic.conf import generic_settings
from generic.openapi import framework_schema
from generic.search import text_lookup
from generic.wiki.access import (
    has_perm,
    page_rights,
    roles_of,
    wiki_rights,
    writes_somewhere,
)
from generic.wiki.models import (
    ROLES,
    Wiki,
    WikiFile,
    WikiImage,
    WikiMember,
    WikiPage,
    WikiRevision,
)
from generic.wiki.serializers import (
    WikiPageListSerializer,
    WikiPageSerializer,
    WikiRevisionSerializer,
    WikiSerializer,
    display_name,
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

#: A page's actions -> the right each needs in its wiki, where the
#: method does not say it: restoring a version changes the page, and
#: the trash is for whoever may delete.
PAGE_ACTIONS = {
    "restore": "change",
    "duplicate": "add",
    "undelete": "delete",
    "purge": "delete",
}

#: Actions that answer a question and change nothing, though POSTed.
READ_ACTIONS = frozenset({"diff"})

#: A wiki's actions for whoever may delete it.
WIKI_DELETE_ACTIONS = frozenset({"destroy", "undelete", "purge"})

#: People and groups offered at once to a wiki's manager looking for a
#: member.
CANDIDATES = 10


def can(user: Any, action_name: str, model: str = "wikipage") -> bool:
    """The model permission - everywhere. What a user may do in *one*
    wiki is ``generic.wiki.access.page_rights``."""
    return has_perm(user, action_name, model)


#: A page's title, at most: the model's field.
TITLE_MAX_LENGTH = 200


def as_bool(value: Any) -> bool:
    """A JSON boolean, or the words a form would send for one."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")

    return bool(value)


def readable_pages(user: Any) -> Any:
    """The pages ``user`` may read: those of the wikis they see."""
    return WikiPage.objects.filter(wiki__in=Wiki.objects.readable_by(user))


def may_write_in(user: Any, wiki_id: Any) -> bool:
    """Whether ``user`` may write pages in this wiki (its access, its
    members, ``GENERIC["WIKI_EDIT_ACCESS"]``)."""
    return Wiki.objects.writable_by(user).filter(pk=wiki_id).exists()


def to_trash(record: Any, user: Any) -> None:
    """Stamped as deleted: out of every screen, kept to be restored."""
    record.deleted_at = timezone.now()
    record.deleted_by = user if getattr(user, "pk", None) else None
    record.save(update_fields=["deleted_at", "deleted_by"])


def out_of_trash(record: Any) -> None:
    record.deleted_at = None
    record.deleted_by = None
    record.save(update_fields=["deleted_at", "deleted_by"])


def trashed_fields(record: Any) -> dict[str, Any]:
    """When a record went to the trash, and who put it there."""
    return {
        "deleted_at": record.deleted_at,
        "deleted_by_name": (
            display_name(record.deleted_by) if record.deleted_by_id else ""
        ),
    }


class WikiPermission(BasePermission):
    """Reading for anyone signed in. Writing a page: by what the user
    may do in its wiki (``access.page_rights`` - its members' roles, or
    the model permissions in an open wiki). The wikis themselves: the
    model permission to add one, then their owner, their managers and
    the model permissions (``access.wiki_rights``)."""

    def has_permission(self, request: Any, view: Any) -> bool:
        user = request.user
        model = getattr(view, "permission_model", "wikipage")

        if not (user and user.is_authenticated):
            return False

        if request.method in SAFE_METHODS or view.action in READ_ACTIONS:
            return True

        if model == "wiki":
            # A new wiki - written, copied, imported. The rest is
            # asked of the wiki itself.
            if view.action in ("create", "duplicate", "import_archive"):
                return has_perm(user, "add", "wiki")

            return True

        # Which wiki a new page lands in is known once it is written
        # (perform_create): here, only that there is one to write in.
        if view.action == "create":
            return writes_somewhere(user)

        return True

    def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
        user = request.user

        if request.method in SAFE_METHODS or view.action in READ_ACTIONS:
            return True

        if isinstance(obj, WikiPage):
            name = PAGE_ACTIONS.get(view.action) or WRITE_PERMISSIONS.get(
                request.method, "change"
            )

            return page_rights(user, obj.wiki)[name]

        if view.action == "duplicate":
            return True

        rights = wiki_rights(user, obj)

        if view.action in WIKI_DELETE_ACTIONS:
            return rights["delete"]

        if view.action == "members":
            return rights["members"]

        return rights["change"]


def user_fields() -> list[str]:
    """The fields of the user model a name is looked for in."""
    model = get_user_model()
    names = [model.USERNAME_FIELD]

    for name in ("first_name", "last_name", "email"):
        try:
            model._meta.get_field(name)
        except FieldDoesNotExist:
            continue

        if name not in names:
            names.append(name)

    return names


def member_json(member: WikiMember) -> dict[str, Any]:
    if member.user_id is not None:
        return {
            "kind": "user",
            "id": member.user_id,
            "name": display_name(member.user),
            "detail": member.user.get_username(),
            "role": member.role,
        }

    return {
        "kind": "group",
        "id": member.group_id,
        "name": member.group.name,
        "detail": gettext("Group"),
        "role": member.role,
    }


class WikiViewSet(ObjectBodyMixin, viewsets.ModelViewSet):
    """The wikis: each a menu of pages of its own."""

    permission_classes = (WikiPermission,)
    permission_model = "wiki"
    serializer_class = WikiSerializer
    pagination_class = None

    def get_queryset(self) -> Any:
        wikis = Wiki.objects.all()

        if self.action in ("trash", "undelete", "purge"):
            wikis = Wiki.all_objects.filter(deleted_at__isnull=False)

        return (
            wikis.readable_by(self.request.user)
            .with_page_count()
            .select_related("owner", "deleted_by")
            .order_by("position", "name")
        )

    def perform_create(self, serializer: Any) -> None:
        # Whoever makes a wiki is its owner.
        serializer.save(owner=self.request.user)

    def perform_destroy(self, instance: Wiki) -> None:
        """To the trash, with its pages as they are: restored whole, or
        deleted for good from there."""
        to_trash(instance, self.request.user)

    @action(detail=False, methods=["get"])
    def trash(self, request: Any) -> Response:
        """The wikis in the trash the user may delete: theirs to
        restore, or to delete for good."""
        roles = roles_of(request.user)
        context = {"request": request, "roles": roles}
        rows = []

        for wiki in self.get_queryset():
            if wiki_rights(request.user, wiki, roles)["delete"]:
                row = WikiSerializer(wiki, context=context).data
                row.update(trashed_fields(wiki))
                rows.append(row)

        return Response(rows)

    @action(detail=True, methods=["post"])
    def undelete(self, request: Any, pk: Any = None) -> Response:
        wiki = self.get_object()
        out_of_trash(wiki)

        return Response(
            WikiSerializer(wiki, context={"request": request}).data
        )

    @action(detail=True, methods=["post"])
    def purge(self, request: Any, pk: Any = None) -> Response:
        """Deleted for good, with its pages and their history."""
        self.get_object().delete()

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get", "put"])
    def members(self, request: Any, pk: Any = None) -> Response:
        """Who the wiki's members are, for whoever manages it. ``PUT``
        ``{"access", "members": [{"user" | "group": id, "role"}],
        "owner": id}`` replaces them: each part is optional."""
        wiki = self.get_object()
        user = request.user
        rights = wiki_rights(user, wiki)

        if not rights["members"]:
            raise PermissionDenied(
                gettext("You may not manage this wiki's members.")
            )

        # Handing a wiki to somebody else is its owner's to do - or
        # whoever may change every wiki.
        may_own = bool(
            user.is_superuser
            or wiki.owner_id == user.pk
            or has_perm(user, "change", "wiki")
        )

        if request.method == "PUT":
            self.write_members(wiki, request.data, may_own)

        rows = wiki.members.select_related("user", "group").order_by("pk")

        return Response(
            {
                "access": wiki.access,
                "owner": (
                    {"id": wiki.owner_id, "name": display_name(wiki.owner)}
                    if wiki.owner_id
                    else None
                ),
                "members": [member_json(member) for member in rows],
                "can": {"owner": may_own},
            }
        )

    def write_members(self, wiki: Wiki, data: Any, may_own: bool) -> None:
        if not isinstance(data, dict):
            raise ValidationError(
                {"detail": gettext("An object is expected.")}
            )

        accesses = {value for value, _label in Wiki.ACCESS}
        access = data.get("access", wiki.access)

        if access not in accesses:
            raise ValidationError({"access": gettext("Unknown access.")})

        rows = data.get("members")
        wanted: dict[tuple[str, int], str] = {}

        if rows is not None:
            if not isinstance(rows, list):
                raise ValidationError(
                    {"members": gettext("A list is expected.")}
                )

            for row in rows:
                kind = next(
                    (
                        name
                        for name in ("user", "group")
                        if isinstance(row, dict) and row.get(name)
                    ),
                    None,
                )

                if kind is None or row.get("role") not in ROLES:
                    raise ValidationError(
                        {"members": gettext("A member is not valid.")}
                    )

                try:
                    wanted[(kind, int(row[kind]))] = row["role"]
                except (TypeError, ValueError):
                    raise ValidationError(
                        {"members": gettext("A member is not valid.")}
                    ) from None

            users = {pk for kind, pk in wanted if kind == "user"}
            groups = {pk for kind, pk in wanted if kind == "group"}

            if get_user_model().objects.filter(
                pk__in=users, is_active=True
            ).count() != len(users) or Group.objects.filter(
                pk__in=groups
            ).count() != len(
                groups
            ):
                raise ValidationError(
                    {"members": gettext("A member no longer exists.")}
                )

        owner = wiki.owner

        if "owner" in data and data["owner"] != wiki.owner_id:
            if not may_own:
                raise PermissionDenied(
                    gettext("Only its owner hands a wiki to someone else.")
                )

            owner = (
                get_object_or_404(
                    get_user_model().objects.filter(is_active=True),
                    pk=data["owner"],
                )
                if data["owner"]
                else None
            )

        with transaction.atomic():
            wiki.access = access
            wiki.owner = owner
            wiki.save(update_fields=["access", "owner"])

            if rows is not None:
                wiki.members.all().delete()
                WikiMember.objects.bulk_create(
                    WikiMember(
                        wiki=wiki,
                        role=role,
                        **{f"{kind}_id": pk},
                    )
                    for (kind, pk), role in wanted.items()
                )

    @action(detail=True, methods=["get"])
    def candidates(self, request: Any, pk: Any = None) -> Response:
        """People and groups matching ``?q=``, for a manager adding a
        member: a few, by name - never the whole directory."""
        wiki = self.get_object()

        if not wiki_rights(request.user, wiki)["members"]:
            raise PermissionDenied(
                gettext("You may not manage this wiki's members.")
            )

        term = (request.query_params.get("q") or "").strip()

        if not term:
            return Response([])

        match = Q()

        for name in user_fields():
            match |= Q(**{text_lookup(name): term})

        users = (
            get_user_model()
            .objects.filter(match, is_active=True)
            .order_by(get_user_model().USERNAME_FIELD)[:CANDIDATES]
        )
        groups = Group.objects.filter(**{text_lookup("name"): term}).order_by(
            "name"
        )[:CANDIDATES]

        return Response(
            [
                {
                    "kind": "user",
                    "id": found.pk,
                    "name": display_name(found),
                    "detail": found.get_username(),
                }
                for found in users
            ]
            + [
                {
                    "kind": "group",
                    "id": group.pk,
                    "name": group.name,
                    "detail": gettext("Group"),
                }
                for group in groups
            ]
        )

    @action(detail=True, methods=["post"])
    def duplicate(self, request: Any, pk: Any = None) -> Response:
        """A copy of the wiki: ``{"name", "description", "pages"}``, for
        whoever may add a wiki - they own the copy
        (generic.wiki.duplicates)."""
        from generic.wiki.duplicates import duplicate_wiki

        source = self.get_object()
        pages = as_bool(request.data.get("pages", True))

        serializer = WikiSerializer(
            data={
                "name": request.data.get("name") or source.name,
                "description": request.data.get(
                    "description", source.description
                ),
            },
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        copy = duplicate_wiki(source, request.user, serializer, pages=pages)

        return Response(
            WikiSerializer(copy, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="import",
        url_name="import",
        parser_classes=(MultiPartParser,),
    )
    def import_archive(self, request: Any) -> Response:
        """A new wiki from an archive another site - or this one -
        exported (``generic.wiki.archive``): for whoever may add a
        wiki, who owns it."""
        from generic.wiki.archive import ArchiveError, import_archive

        user = request.user
        upload = request.FILES.get("file")

        if upload is None:
            return WikiImageUploadView.refuse(
                gettext("Choose a wiki archive to import.")
            )

        limit = generic_settings.WIKI_ARCHIVE_MAX_SIZE

        if limit and upload.size > limit:
            return WikiImageUploadView.refuse(
                gettext("The archive is too large: at most %(limit)s.")
                % {"limit": filesizeformat(limit)}
            )

        name = request.data.get("name")

        def writable(wiki: Wiki) -> None:
            # Made where the project's rules would not let them write:
            # as if never imported.
            if not may_write_in(user, wiki.pk):
                raise PermissionDenied(
                    gettext("You may not write in this wiki.")
                )

        try:
            result = import_archive(
                upload,
                user=user,
                name=name if isinstance(name, str) else "",
                check=writable,
            )
        except ArchiveError as error:
            return WikiImageUploadView.refuse(str(error))

        data = WikiSerializer(result.wiki, context={"request": request}).data
        data.update(
            pages=result.pages,
            images=result.images,
            files=result.files,
            skipped=result.skipped,
        )

        return Response(data, status=status.HTTP_201_CREATED)


class WikiPageViewSet(ObjectBodyMixin, viewsets.ModelViewSet):
    permission_classes = (WikiPermission,)
    pagination_class = None

    def get_queryset(self) -> Any:
        user = self.request.user

        if self.action in ("trash", "undelete", "purge"):
            return (
                WikiPage.all_objects.filter(
                    deleted_at__isnull=False,
                    wiki__in=Wiki.objects.readable_by(user),
                )
                .select_related("wiki", "deleted_by")
                .order_by("-deleted_at", "-pk")
            )

        pages = (
            readable_pages(user)
            .select_related("wiki", "updated_by")
            .order_by("position", "title")
        )
        wiki = self.request.query_params.get("wiki")

        if self.action == "list" and wiki:
            pages = pages.filter(wiki_id=wiki if wiki.isdigit() else None)

        return pages

    def get_serializer_class(self) -> Any:
        if self.action == "list":
            return WikiPageListSerializer

        return WikiPageSerializer

    def perform_create(self, serializer: Any) -> None:
        user = self.request.user

        with transaction.atomic():
            page = serializer.save(created_by=user, updated_by=user)

            # Wherever it landed - the wiki sent, its parent's, the
            # first - it must be a wiki the user adds pages in.
            if not page_rights(user, page.wiki)["add"]:
                raise PermissionDenied(
                    gettext("You may not write in this wiki.")
                )

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

    def perform_destroy(self, instance: WikiPage) -> None:
        """To the trash, with its history; its subpages move up a
        level, to the page it was under."""
        with transaction.atomic():
            WikiPage.objects.filter(parent=instance).update(
                parent=instance.parent_id
            )
            to_trash(instance, self.request.user)

    @action(detail=False, methods=["get"])
    def trash(self, request: Any) -> Response:
        """The pages of ``?wiki=<id>`` in the trash, newest first, for
        whoever may delete pages there."""
        wiki = (
            Wiki.objects.readable_by(request.user)
            .filter(pk=as_id(request.query_params.get("wiki")))
            .first()
        )

        if wiki is None or not page_rights(request.user, wiki)["delete"]:
            raise PermissionDenied(
                gettext("You may not delete pages in this wiki.")
            )

        return Response(
            [
                {
                    "id": page.pk,
                    "title": page.title,
                    "slug": page.slug,
                    **trashed_fields(page),
                }
                for page in self.get_queryset().filter(wiki=wiki)
            ]
        )

    @action(detail=True, methods=["post"])
    def undelete(self, request: Any, pk: Any = None) -> Response:
        """Back from the trash, under the page it was under if that
        one is still there - at the top of the menu otherwise."""
        page = self.get_object()

        if (
            page.parent_id is not None
            and not WikiPage.objects.filter(pk=page.parent_id).exists()
        ):
            page.parent = None
            page.save(update_fields=["parent"])

        out_of_trash(page)

        return Response(
            WikiPageSerializer(page, context={"request": request}).data
        )

    @action(detail=True, methods=["post"])
    def purge(self, request: Any, pk: Any = None) -> Response:
        """Deleted for good, with its history."""
        self.get_object().delete()

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get", "post"])
    def diff(self, request: Any, pk: Any = None) -> Response:
        """What changed between two texts of the page, as lines
        (``generic.wiki.diff``).

        ``GET ?from=<version>&to=<version>``: ``to`` left out, the page
        as it stands; ``from`` left out, the version before ``to``.
        ``POST {"title", "content"}``: from the page as it stands to
        the text sent - what a writer refused by a conflict is about to
        overwrite. Answers ``{"lines", "added", "removed", "before",
        "after", "version"}``.
        """
        from generic.wiki.diff import diff
        from generic.wiki.sanitize import clean_html

        page = self.get_object()
        current = {
            "title": page.title,
            "content": page.content,
            "created_at": page.updated_at,
            "author_name": (
                display_name(page.updated_by) if page.updated_by_id else ""
            ),
        }

        def version(key: str) -> dict[str, Any] | None:
            value = request.query_params.get(key)

            if not value:
                return None

            revision = get_object_or_404(
                page.revisions.select_related("author"), pk=as_id(value)
            )

            return {
                "id": revision.pk,
                "title": revision.title,
                "content": revision.content,
                "created_at": revision.created_at,
                "author_name": (
                    display_name(revision.author) if revision.author_id else ""
                ),
            }

        if request.method == "POST":
            before = current
            after = {
                "title": str(request.data.get("title") or page.title),
                "content": clean_html(str(request.data.get("content") or "")),
                "created_at": None,
                "author_name": display_name(request.user),
            }
        else:
            after = version("to") or current
            before = version("from")

            if before is None:
                # The version written just before ``after``.
                older = page.revisions.select_related("author")

                if "id" in after:
                    older = older.filter(
                        Q(created_at__lt=after["created_at"])
                        | Q(created_at=after["created_at"], pk__lt=after["id"])
                    )

                previous = older.first()
                before = (
                    {
                        "id": previous.pk,
                        "title": previous.title,
                        "content": previous.content,
                        "created_at": previous.created_at,
                        "author_name": (
                            display_name(previous.author)
                            if previous.author_id
                            else ""
                        ),
                    }
                    if previous is not None
                    else {
                        "title": "",
                        "content": "",
                        "created_at": None,
                        "author_name": "",
                    }
                )

        result = diff(before["content"], after["content"])

        def about(side: dict[str, Any]) -> dict[str, Any]:
            return {
                name: side.get(name)
                for name in ("id", "title", "created_at", "author_name")
            }

        result.update(
            before=about(before),
            after=about(after),
            # What a save over the page as it stands must be sent with.
            version=page.updated_at.isoformat() if page.updated_at else "",
        )

        return Response(result)

    @action(detail=True, methods=["post"])
    def duplicate(self, request: Any, pk: Any = None) -> Response:
        """A copy of the page beside it: ``{"title", "subpages"}``, for
        whoever may add pages in its wiki (generic.wiki.duplicates)."""
        from generic.wiki.duplicates import duplicate_page

        page = self.get_object()
        title = str(request.data.get("title") or "").strip()

        if not title:
            return Response(
                {"title": [gettext("This field is required.")]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(title) > TITLE_MAX_LENGTH:
            return Response(
                {"title": [gettext("This title is too long.")]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        copy = duplicate_page(
            page,
            request.user,
            title,
            subpages=as_bool(request.data.get("subpages", False)),
        )

        return Response(
            WikiPageSerializer(copy, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"])
    def revisions(self, request: Any, pk: Any = None) -> Response:
        page = self.get_object()
        current = page.current_revision()
        serializer = WikiRevisionSerializer(
            page.revisions.select_related("page__wiki", "author"),
            many=True,
            context={"current": current.pk if current else None},
        )

        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def restore(self, request: Any, pk: Any = None) -> Response:
        page = self.get_object()
        revision = get_object_or_404(
            page.revisions,
            pk=as_id(request.data.get("revision")),
        )

        with transaction.atomic():
            # The current text becomes a version too, unless it is one
            # already: restoring can be undone like any other change,
            # and the restored version is not written twice - the page
            # points back at its entry (``current_revision``).
            WikiRevision.keep(page)
            page.title = revision.title
            page.content = revision.content
            page.updated_by = request.user
            page.save()

        return Response(
            WikiPageSerializer(page, context={"request": request}).data
        )


def as_id(value: Any) -> int | None:
    """A key sent by a client, or ``None`` for anything that is not
    one: looked up, it finds nothing."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def upload_wiki(request: Any) -> Wiki | None:
    """The wiki an upload is for - the ``wiki`` sent with it - which
    the user must write pages in. Sent without one, by an editor from
    before uploads had a wiki: the user must write somewhere, and the
    upload is theirs alone until a page shows it."""
    user = request.user
    value = request.data.get("wiki")

    if value in (None, ""):
        if not writes_somewhere(user):
            raise PermissionDenied(gettext("You may not write in a wiki."))

        return None

    wiki = Wiki.objects.readable_by(user).filter(pk=as_id(value)).first()
    rights = page_rights(user, wiki) if wiki is not None else {}

    if not (rights.get("add") or rights.get("change")):
        raise PermissionDenied(gettext("You may not write in this wiki."))

    return wiki


class WikiImagePermission(BasePermission):
    """Anyone signed in gets to ask: whether they may write a page of
    the wiki the upload is for is :func:`upload_wiki`'s to say."""

    def has_permission(self, request: Any, view: Any) -> bool:
        user = request.user

        return bool(user and user.is_authenticated)


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
        wiki = upload_wiki(request)
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
            wiki=wiki,
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
        wiki = upload_wiki(request)
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
            wiki=wiki,
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
