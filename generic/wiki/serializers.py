"""The wiki's JSON."""

from __future__ import annotations

from typing import Any

from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import APIException

from generic.wiki.models import WikiPage, WikiRevision

#: Addresses the wiki's own routes need.
RESERVED_SLUGS = frozenset({"api"})


class Conflict(APIException):
    status_code = 409
    default_detail = _("This page was changed since you opened it.")
    default_code = "conflict"


def display_name(user: Any) -> str:
    if user is None:
        return ""

    return user.get_full_name() or user.get_username()


def unique_slug(title: str, exclude_pk: Any = None) -> str:
    """An address for ``title`` no other page uses."""
    base = slugify(title, allow_unicode=True)[:100] or "page"

    if base in RESERVED_SLUGS:
        base = f"{base}-page"

    pages = WikiPage.objects.all()

    if exclude_pk is not None:
        pages = pages.exclude(pk=exclude_pk)

    slug = base
    index = 2

    while pages.filter(slug=slug).exists():
        slug = f"{base}-{index}"
        index += 1

    return slug


class WikiPageListSerializer(serializers.ModelSerializer):
    """A page in the menu: no content."""

    url = serializers.SerializerMethodField()

    class Meta:
        model = WikiPage
        fields = (
            "id",
            "title",
            "slug",
            "parent",
            "position",
            "show_on_dashboard",
            "url",
        )
        read_only_fields = fields

    def get_url(self, page: WikiPage) -> str:
        return page.get_absolute_url()


class WikiPageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    #: The version the client edits: a save made against an older one is
    #: refused rather than silently overwriting someone else's change.
    version = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()
    #: The images and files the page shows, in its order (read-only).
    attachments = serializers.SerializerMethodField()

    class Meta:
        model = WikiPage
        fields = (
            "id",
            "title",
            "slug",
            "parent",
            "position",
            "content",
            "show_on_dashboard",
            "url",
            "version",
            "updated_at",
            "updated_by_name",
            "attachments",
        )
        read_only_fields = ("updated_at",)
        extra_kwargs = {"slug": {"required": False, "allow_blank": True}}

    def get_url(self, page: WikiPage) -> str:
        return page.get_absolute_url() if page.pk else ""

    def get_version(self, page: WikiPage) -> str:
        return page.updated_at.isoformat() if page.updated_at else ""

    def get_updated_by_name(self, page: WikiPage) -> str:
        return display_name(page.updated_by) if page.updated_by_id else ""

    def get_attachments(self, page: WikiPage) -> list[dict[str, Any]]:
        return page.attachments() if page.pk else []

    def to_representation(self, page: WikiPage) -> dict[str, Any]:
        from generic.wiki.sanitize import clean_html

        data = super().to_representation(page)
        # Cleaned on the way out too, like the page itself: a row written
        # around save() - a raw update, an import - never leaks through.
        data["content"] = clean_html(data.get("content"))

        return data

    def validate_slug(self, value: str) -> str:
        value = (value or "").strip()

        if value in RESERVED_SLUGS:
            raise serializers.ValidationError(_("This address is reserved."))

        return value

    def validate_parent(self, parent: WikiPage | None) -> WikiPage | None:
        node = parent

        while self.instance is not None and node is not None:
            if node.pk == self.instance.pk:
                raise serializers.ValidationError(
                    _("A page cannot be placed under itself.")
                )

            node = node.parent

        return parent

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        request = self.context.get("request")
        expected = (
            request.data.get("version")
            if request is not None and hasattr(request, "data")
            else None
        )

        if (
            self.instance is not None
            and expected
            and expected != self.get_version(self.instance)
        ):
            raise Conflict(
                _(
                    "%(name)s changed this page since you opened it. Copy "
                    "your text, reload the page and apply it again."
                )
                % {
                    "name": self.get_updated_by_name(self.instance)
                    or _("Someone")
                }
            )

        if not attrs.get("slug"):
            if self.instance is None:
                attrs["slug"] = unique_slug(attrs.get("title", ""))
            else:
                attrs.pop("slug", None)

        return attrs


class WikiRevisionSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    size = serializers.SerializerMethodField()

    class Meta:
        model = WikiRevision
        fields = ("id", "title", "created_at", "author_name", "size")
        read_only_fields = fields

    def get_author_name(self, revision: WikiRevision) -> str:
        return display_name(revision.author) if revision.author_id else ""

    def get_size(self, revision: WikiRevision) -> int:
        return len(revision.content)
