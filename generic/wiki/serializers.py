"""The wiki's JSON."""

from __future__ import annotations

from typing import Any

from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import APIException

from generic.wiki.models import (
    RESERVED_WIKI_SLUGS,
    Wiki,
    WikiPage,
    WikiRevision,
)

#: Page addresses the wiki's own routes need.
RESERVED_SLUGS = frozenset({"api"})


class Conflict(APIException):
    status_code = 409
    default_detail = _("This page was changed since you opened it.")
    default_code = "conflict"


def display_name(user: Any) -> str:
    if user is None:
        return ""

    return user.get_full_name() or user.get_username()


def unique_slug(title: str, exclude_pk: Any = None, wiki: Any = None) -> str:
    """An address for ``title`` no other page of ``wiki`` uses."""
    base = slugify(title, allow_unicode=True)[:100] or "page"

    if base in RESERVED_SLUGS:
        base = f"{base}-page"

    pages = WikiPage.objects.all()

    if wiki is not None:
        pages = pages.filter(wiki=wiki)

    if exclude_pk is not None:
        pages = pages.exclude(pk=exclude_pk)

    slug = base
    index = 2

    while pages.filter(slug=slug).exists():
        slug = f"{base}-{index}"
        index += 1

    return slug


def unique_wiki_slug(name: str) -> str:
    """An address for a wiki called ``name`` no other wiki uses."""
    base = slugify(name, allow_unicode=True)[:100] or "wiki"

    if base in RESERVED_WIKI_SLUGS:
        base = f"{base}-wiki"

    slug = base
    index = 2

    while Wiki.objects.filter(slug=slug).exists():
        slug = f"{base}-{index}"
        index += 1

    return slug


class WikiSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    #: Where the whole wiki is downloaded as a PDF; empty when it cannot.
    pdf_url = serializers.SerializerMethodField()
    page_count = serializers.SerializerMethodField()

    class Meta:
        model = Wiki
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "position",
            "url",
            "pdf_url",
            "page_count",
        )
        extra_kwargs = {"slug": {"required": False, "allow_blank": True}}

    def get_url(self, wiki: Wiki) -> str:
        return wiki.get_absolute_url() if wiki.pk else ""

    def get_pdf_url(self, wiki: Wiki) -> str:
        from generic.wiki.pdf import available

        return wiki.get_pdf_url() if wiki.pk and available() else ""

    def get_page_count(self, wiki: Wiki) -> int:
        count = getattr(wiki, "page_count", None)

        if count is None:
            count = wiki.pages.count() if wiki.pk else 0

        return count

    def validate_slug(self, value: str) -> str:
        value = (value or "").strip()

        if value in RESERVED_WIKI_SLUGS:
            raise serializers.ValidationError(_("This address is reserved."))

        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("slug"):
            if self.instance is None:
                attrs["slug"] = unique_wiki_slug(attrs.get("name", ""))
            else:
                attrs.pop("slug", None)

        return attrs


class WikiPageListSerializer(serializers.ModelSerializer):
    """A page in the menu: no content."""

    url = serializers.SerializerMethodField()

    class Meta:
        model = WikiPage
        fields = (
            "id",
            "wiki",
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
            "wiki",
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
        extra_kwargs = {
            "slug": {"required": False, "allow_blank": True},
            # Left out, the parent's wiki, or the first one.
            "wiki": {"required": False},
        }
        # An address is unique within its wiki: checked in validate(),
        # where the wiki a new page goes to is known.
        validators: list = []

    def get_fields(self) -> dict[str, Any]:
        fields = super().get_fields()
        request = self.context.get("request")

        # Only the wikis the writer sees can be named.
        if request is not None and "wiki" in fields:
            fields["wiki"].queryset = Wiki.objects.readable_by(request.user)

        return fields

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

        instance = self.instance
        parent = attrs.get("parent", instance.parent if instance else None)
        wiki = attrs.get("wiki")

        if instance is not None:
            if wiki is not None and wiki.pk != instance.wiki_id:
                raise serializers.ValidationError(
                    {"wiki": _("A page cannot move to another wiki.")}
                )

            wiki = instance.wiki
        elif wiki is None:
            wiki = (
                parent.wiki if parent is not None else Wiki.objects.default()
            )
            attrs["wiki"] = wiki

        if parent is not None and parent.wiki_id != wiki.pk:
            raise serializers.ValidationError(
                {"parent": _("The parent page is in another wiki.")}
            )

        if not attrs.get("slug"):
            if instance is None:
                attrs["slug"] = unique_slug(attrs.get("title", ""), wiki=wiki)
            else:
                attrs.pop("slug", None)
        elif (
            WikiPage.objects.filter(wiki=wiki, slug=attrs["slug"])
            .exclude(pk=instance.pk if instance else None)
            .exists()
        ):
            raise serializers.ValidationError(
                {"slug": _("Another page of this wiki has this address.")}
            )

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
