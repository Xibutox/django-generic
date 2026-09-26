"""Wiki pages, and the versions they went through."""

from __future__ import annotations

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
