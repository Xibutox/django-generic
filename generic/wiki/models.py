"""Wiki pages, and the versions they went through."""

from __future__ import annotations

import re
from typing import Any

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from generic.wiki.sanitize import clean_html

#: Versions kept per page; older ones are dropped as new ones come.
MAX_REVISIONS = 50


class WikiPage(models.Model):
    title = models.CharField(_("title"), max_length=200)
    slug = models.SlugField(
        _("address"),
        max_length=120,
        unique=True,
        allow_unicode=True,
        help_text=_("The end of the page's URL."),
    )
    parent = models.ForeignKey(
        "self",
        verbose_name=_("parent page"),
        on_delete=models.SET_NULL,
        related_name="children",
        null=True,
        blank=True,
    )
    position = models.PositiveIntegerField(
        _("position"),
        default=0,
        help_text=_("Order among its sibling pages in the menu."),
    )
    #: Clean HTML: see sanitize.py.
    content = models.TextField(_("content"), blank=True, default="")
    show_on_dashboard = models.BooleanField(
        _("show on the dashboard"),
        default=False,
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("created by"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("updated by"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("position", "title")
        verbose_name = _("wiki page")
        verbose_name_plural = _("wiki pages")

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("generic_wiki:page", kwargs={"slug": self.slug})

    def save(self, *args, **kwargs) -> None:
        # Whatever the way in - the API, the admin, a script - only
        # clean HTML is stored.
        self.content = clean_html(self.content)
        super().save(*args, **kwargs)

    def get_ancestors(self) -> list["WikiPage"]:
        """From the top of the menu down to this page's parent."""
        chain = []
        seen = {self.pk}
        node = self.parent

        # A loop in the data must not hang a page.
        while node is not None and node.pk not in seen:
            chain.append(node)
            seen.add(node.pk)
            node = node.parent

        return list(reversed(chain))

    def attachments(self) -> list[dict[str, Any]]:
        """The images and files this page shows, in the page's order.

        Read from the text itself - an upload belongs to whichever page
        links to it - once each, and only those still stored in the
        database: ``{"kind", "id", "name", "size", "url"}``.
        """
        return attachments_in(self.content)


class WikiRevision(models.Model):
    """A page as it was before a change: kept to compare and restore."""

    page = models.ForeignKey(
        WikiPage,
        verbose_name=_("page"),
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    title = models.CharField(_("title"), max_length=200)
    content = models.TextField(_("content"), blank=True, default="")
    #: When this version was written, and by whom.
    created_at = models.DateTimeField(_("written at"), default=timezone.now)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("author"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("-created_at", "-pk")
        verbose_name = _("wiki revision")
        verbose_name_plural = _("wiki revisions")

    def __str__(self) -> str:
        return f"{self.title} ({self.created_at:%Y-%m-%d %H:%M})"

    @classmethod
    def keep(cls, page: WikiPage) -> "WikiRevision":
        """Record ``page`` as it stands, and drop the oldest versions."""
        revision = cls.objects.create(
            page=page,
            title=page.title,
            content=page.content,
            created_at=page.updated_at or timezone.now(),
            author_id=page.updated_by_id,
        )
        stale = list(
            cls.objects.filter(page=page).values_list("pk", flat=True)[
                MAX_REVISIONS:
            ]
        )

        if stale:
            cls.objects.filter(pk__in=stale).delete()

        return revision


class WikiImage(models.Model):
    """An image uploaded from the editor, shown in a page by its address.

    Not attached to a page: a page holds ``<img src="/wiki/images/7/">``
    like any other image, and an image may be shown by several pages -
    or by an earlier version of one, which is why nothing deletes it
    when a page stops showing it.
    """

    file = models.FileField(_("file"), upload_to="wiki/images/%Y/%m/")
    original_name = models.CharField(
        _("original name"), max_length=255, blank=True, default=""
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("uploaded by"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )
    uploaded_at = models.DateTimeField(_("uploaded at"), default=timezone.now)

    class Meta:
        ordering = ("-uploaded_at", "-pk")
        verbose_name = _("wiki image")
        verbose_name_plural = _("wiki images")

    def __str__(self) -> str:
        return self.original_name or self.file.name

    def get_absolute_url(self) -> str:
        return reverse("generic_wiki:image", kwargs={"pk": self.pk})


class WikiFile(models.Model):
    """A file attached from the editor - a PDF, a spreadsheet, an
    archive - shown in a page as a block linking to its address.

    Like :class:`WikiImage`, not attached to a page: a page holds
    ``<p class="wiki-file"><a href="/wiki/files/7/">plan.pdf</a></p>``,
    and the file stays while any version of any page may link to it.
    """

    file = models.FileField(_("file"), upload_to="wiki/files/%Y/%m/")
    original_name = models.CharField(
        _("original name"), max_length=255, blank=True, default=""
    )
    #: Bytes, kept so that a page lists its files without opening them.
    size = models.PositiveBigIntegerField(_("size"), default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("uploaded by"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )
    uploaded_at = models.DateTimeField(_("uploaded at"), default=timezone.now)

    class Meta:
        ordering = ("-uploaded_at", "-pk")
        verbose_name = _("wiki file")
        verbose_name_plural = _("wiki files")

    def __str__(self) -> str:
        return self.original_name or self.file.name

    def get_absolute_url(self) -> str:
        return reverse("generic_wiki:file", kwargs={"pk": self.pk})


def _address_pattern(kind: str) -> str:
    """The address of a ``kind`` upload, wherever the wiki is mounted, as
    a pattern whose group ``<kind>`` is its id."""
    sample = reverse(f"generic_wiki:{kind}", kwargs={"pk": 4242})

    return re.escape(sample).replace("4242", rf"(?P<{kind}>\d+)")


def attachments_in(html: str | None) -> list[dict[str, Any]]:
    """The uploads ``html`` links to or shows, in order, once each."""
    if not html:
        return []

    kinds = {"image": WikiImage, "file": WikiFile}
    addresses = "|".join(_address_pattern(kind) for kind in kinds)
    pattern = re.compile(rf"""(?:src|href)=["'](?:{addresses})["']""")
    found: list[tuple[str, int]] = []

    for match in pattern.finditer(html):
        kind = "image" if match.group("image") else "file"
        key = (kind, int(match.group(kind)))

        if key not in found:
            found.append(key)

    stored = {
        kind: model.objects.in_bulk(
            [pk for found_kind, pk in found if found_kind == kind]
        )
        for kind, model in kinds.items()
    }
    attachments = []

    for kind, pk in found:
        upload = stored[kind].get(pk)

        if upload is not None:
            attachments.append(
                {
                    "kind": kind,
                    "id": pk,
                    "name": str(upload),
                    "size": upload.size if kind == "file" else None,
                    "url": upload.get_absolute_url(),
                }
            )

    return attachments
