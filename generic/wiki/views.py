"""The wiki's pages: the menu, one page, and its editor.

A page is rendered by the server, with HTML cleaned on the way in and
on the way out, and edited in the browser: the editor saves through the
API, as JSON, like every other screen of the application.
"""

from __future__ import annotations

import mimetypes
from pathlib import PurePath
from typing import Any

from django.contrib.auth.views import redirect_to_login
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext
from django.views import View
from django.views.generic import TemplateView

from generic.api.files import file_name
from generic.conf import generic_settings
from generic.sites import site
from generic.sites.files import is_stored, protect
from generic.sites.views import SiteViewMixin
from generic.views.toolbar import Breadcrumb
from generic.wiki.api import IMAGE_TYPES, can
from generic.wiki.models import WikiFile, WikiImage, WikiPage
from generic.wiki.sanitize import safe_html
from generic.wiki.serializers import WikiPageSerializer


def upload_url(name: str) -> str:
    """Where the editor uploads an image or a file (``name``:
    ``wiki-images``, ``wiki-files``); empty when not mounted."""
    try:
        return reverse(f"generic:{name}")
    except NoReverseMatch:
        return ""


def image_upload_url() -> str:
    """Where the editor uploads an image; empty when not mounted."""
    return upload_url("wiki-images")


def build_menu(pages: list[WikiPage], current: WikiPage | None) -> list:
    """The page tree as nested dicts, the current branch open."""
    children: dict[Any, list[WikiPage]] = {}

    for page in pages:
        children.setdefault(page.parent_id, []).append(page)

    open_ids = (
        {page.pk for page in current.get_ancestors()} if current else set()
    )

    if current is not None:
        open_ids.add(current.pk)

    seen: set[Any] = set()

    def branch(parent_id: Any, depth: int) -> list[dict[str, Any]]:
        entries = []

        for page in children.get(parent_id, []):
            # A loop in the data would recurse for ever.
            if page.pk in seen:
                continue

            seen.add(page.pk)
            kids = branch(page.pk, depth + 1)
            entries.append(
                {
                    "id": page.pk,
                    "title": page.title,
                    "url": page.get_absolute_url(),
                    "depth": depth,
                    "is_current": current is not None
                    and page.pk == current.pk,
                    "is_open": page.pk in open_ids,
                    "children": kids,
                    # What the menu filter matches: a page stays in
                    # sight while one of its subpages does.
                    "search": " ".join(
                        [page.title, *(kid["search"] for kid in kids)]
                    ).lower(),
                }
            )

        return entries

    return branch(None, 0)


def descendants_of(pages: list[WikiPage], root: WikiPage) -> set[Any]:
    """``root`` and every page under it: where it cannot be moved."""
    children: dict[Any, list[Any]] = {}

    for page in pages:
        children.setdefault(page.parent_id, []).append(page.pk)

    found = {root.pk}
    queue = [root.pk]

    while queue:
        for child in children.get(queue.pop(), []):
            if child not in found:
                found.add(child)
                queue.append(child)

    return found


class WikiViewMixin(SiteViewMixin, TemplateView):
    site = site
    template_name = "generic/wiki/page.html"
    page: WikiPage | None = None

    def get_page_title(self) -> str:
        return self.page.title if self.page is not None else gettext("Wiki")

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        crumbs = [
            Breadcrumb(
                label=gettext("Wiki"), url=reverse("generic_wiki:index")
            )
        ]

        if self.page is not None:
            crumbs += [
                Breadcrumb(
                    label=ancestor.title, url=ancestor.get_absolute_url()
                )
                for ancestor in self.page.get_ancestors()
            ]
            crumbs.append(Breadcrumb(label=self.page.title))

        return crumbs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        request = self.request
        page = self.page
        pages = list(
            WikiPage.objects.only(
                "id", "title", "slug", "parent_id", "position"
            ).order_by("position", "title")
        )
        rights = {
            name: can(request.user, name)
            for name in ("add", "change", "delete")
        }
        excluded = descendants_of(pages, page) if page is not None else set()

        context.update(
            page=page,
            menu=build_menu(pages, page),
            content=safe_html(page.content) if page else "",
            attachments=page.attachments() if page else [],
            can=rights,
            wiki_config={
                "page": (
                    WikiPageSerializer(page, context={"request": request}).data
                    if page is not None
                    else None
                ),
                "api": reverse("generic_wiki:page-list"),
                "pageUrl": reverse(
                    "generic_wiki:page", kwargs={"slug": "__slug__"}
                ),
                "indexUrl": reverse("generic_wiki:index"),
                # Images uploaded from the editor, when the framework's
                # endpoints are mounted; the address is offered anyway.
                "imagesUrl": image_upload_url(),
                "filesUrl": upload_url("wiki-files"),
                "imageMaxSize": generic_settings.FILE_MAX_SIZE,
                "can": rights,
                "parents": [
                    {"id": entry.pk, "title": entry.title}
                    for entry in pages
                    if entry.pk not in excluded
                ],
                # A new page opens straight in the editor.
                "edit": request.GET.get("edit") == "1" and rights["change"],
            },
        )

        return context


class WikiIndexView(WikiViewMixin):
    """The first page of the menu, or an invitation to write it."""

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        first = (
            WikiPage.objects.filter(parent__isnull=True)
            .order_by("position", "title")
            .first()
        )

        if first is not None:
            return redirect(first.get_absolute_url())

        return super().get(request, *args, **kwargs)


class WikiPageView(WikiViewMixin):
    def get(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        self.page = get_object_or_404(
            WikiPage.objects.select_related("parent", "updated_by"),
            slug=kwargs["slug"],
        )

        return super().get(request, *args, **kwargs)


class WikiImageView(View):
    """An image of the wiki, for whoever may read its pages.

    Shown in the page (``inline``), as the image type its bytes were
    found to be when it was uploaded, never sniffed as anything else,
    and kept by the reader's browser for a day - never by a shared
    cache, since it is only for signed-in readers.
    """

    def get(self, request: Any, pk: int) -> Any:
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(), site.get_login_url()
            )

        image = get_object_or_404(WikiImage, pk=pk)
        name = file_name(image.file)
        content_type = IMAGE_TYPES.get(PurePath(name).suffix.lstrip("."))

        if content_type is None or not is_stored(image.file):
            raise Http404

        response = FileResponse(
            image.file.open("rb"),
            filename=name,
            content_type=content_type,
        )
        protect(response)
        response["Cache-Control"] = "private, max-age=86400"

        return response


class WikiFileView(View):
    """A file of the wiki, for whoever may read its pages.

    Always a download (``attachment``), under the name it was uploaded
    with, and never sniffed: whatever somebody uploaded, it never runs
    in the site's origin. Not kept by a shared cache either.
    """

    def get(self, request: Any, pk: int) -> Any:
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(), site.get_login_url()
            )

        attachment = get_object_or_404(WikiFile, pk=pk)

        if not is_stored(attachment.file):
            raise Http404

        name = attachment.original_name or file_name(attachment.file)
        response = FileResponse(
            attachment.file.open("rb"),
            as_attachment=True,
            filename=name,
            content_type=mimetypes.guess_type(name)[0]
            or "application/octet-stream",
        )
        protect(response)
        response["Cache-Control"] = "private, max-age=86400"

        return response
