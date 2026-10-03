"""The wikis' pages: the list of wikis, a wiki's menu, one page, its
editor, and the whole wiki as a PDF.

A page is rendered by the server, with HTML cleaned on the way in and
on the way out, and edited in the browser: the editor saves through the
API, as JSON, like every other screen of the application.
"""

from __future__ import annotations

import mimetypes
from pathlib import PurePath
from typing import Any

from django.contrib.auth.views import redirect_to_login
from django.db.models import Count
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import NoReverseMatch, reverse
from django.utils.http import content_disposition_header
from django.utils.translation import gettext
from django.views import View
from django.views.generic import TemplateView

from generic.api.files import file_name
from generic.conf import generic_settings
from generic.sites import site
from generic.sites.files import is_stored, protect
from generic.sites.views import SiteViewMixin
from generic.views.toolbar import Breadcrumb
from generic.wiki import pdf
from generic.wiki.api import IMAGE_TYPES, can, readable_pages
from generic.wiki.models import Wiki, WikiFile, WikiImage, WikiPage
from generic.wiki.sanitize import safe_html
from generic.wiki.serializers import WikiPageSerializer, WikiSerializer


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


def page_url(page: WikiPage) -> str:
    """A page's address, from a page loaded with its wiki's slug."""
    return reverse(
        "generic_wiki:page",
        kwargs={"wiki": page.wiki.slug, "slug": page.slug},
    )


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
                    "url": page_url(page),
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


def wiki_rights(user: Any) -> dict[str, bool]:
    """What ``user`` may do to the wikis themselves."""
    return {
        name: can(user, name, "wiki") for name in ("add", "change", "delete")
    }


class WikiListView(SiteViewMixin, TemplateView):
    """The wikis, each with its pages' count and its PDF.

    A reader who sees one wiki and may not add another goes straight
    to it: one wiki reads as it did before there could be several.
    """

    site = site
    template_name = "generic/wiki/index.html"

    def get_page_title(self) -> str:
        return gettext("Wikis")

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [Breadcrumb(label=gettext("Wiki"))]

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        wikis = list(self.wikis())

        if len(wikis) == 1 and not can(request.user, "add", "wiki"):
            return redirect(wikis[0].get_absolute_url())

        self.wiki_list = wikis

        return super().get(request, *args, **kwargs)

    def wikis(self) -> Any:
        return (
            Wiki.objects.readable_by(self.request.user)
            .annotate(page_count=Count("pages"))
            .order_by("position", "name")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        request = self.request
        rights = wiki_rights(request.user)

        context.update(
            wikis=self.wiki_list,
            can=rights,
            pdf_available=pdf.available(),
            wikis_config={
                "api": reverse("generic_wiki:wiki-list"),
                "wikis": WikiSerializer(
                    self.wiki_list, many=True, context={"request": request}
                ).data,
                "can": rights,
            },
        )

        return context


class WikiViewMixin(SiteViewMixin, TemplateView):
    site = site
    template_name = "generic/wiki/page.html"
    wiki: Wiki
    page: WikiPage | None = None

    def get_wiki(self, slug: str) -> Wiki:
        return get_object_or_404(
            Wiki.objects.readable_by(self.request.user), slug=slug
        )

    def get_page_title(self) -> str:
        return self.page.title if self.page is not None else self.wiki.name

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        crumbs = [
            Breadcrumb(
                label=gettext("Wiki"), url=reverse("generic_wiki:index")
            )
        ]

        if self.page is None:
            crumbs.append(Breadcrumb(label=self.wiki.name))
            return crumbs

        crumbs.append(
            Breadcrumb(label=self.wiki.name, url=self.wiki.get_absolute_url())
        )
        crumbs += [
            Breadcrumb(label=ancestor.title, url=ancestor.get_absolute_url())
            for ancestor in self.page.get_ancestors()
        ]
        crumbs.append(Breadcrumb(label=self.page.title))

        return crumbs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        request = self.request
        wiki = self.wiki
        page = self.page
        pages = list(
            WikiPage.objects.filter(wiki=wiki)
            .select_related("wiki")
            .only("id", "title", "slug", "parent_id", "position", "wiki__slug")
            .order_by("position", "title")
        )
        rights = {
            name: can(request.user, name)
            for name in ("add", "change", "delete")
        }
        excluded = descendants_of(pages, page) if page is not None else set()
        others = Wiki.objects.readable_by(request.user).exclude(pk=wiki.pk)

        context.update(
            wiki=wiki,
            other_wikis=list(others.order_by("position", "name")),
            pdf_url=wiki.get_pdf_url() if pdf.available() else "",
            page=page,
            menu=build_menu(pages, page),
            content=safe_html(page.content) if page else "",
            attachments=page.attachments() if page else [],
            can=rights,
            wiki_config={
                "wiki": wiki.pk,
                "page": (
                    WikiPageSerializer(page, context={"request": request}).data
                    if page is not None
                    else None
                ),
                "api": reverse("generic_wiki:page-list"),
                "pageUrl": reverse(
                    "generic_wiki:page",
                    kwargs={"wiki": wiki.slug, "slug": "__slug__"},
                ),
                "indexUrl": wiki.get_absolute_url(),
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
    """A wiki's first page, or an invitation to write it.

    The address of a page from before there were several wikis -
    ``wiki/<page>/`` - is no wiki's: it leads to that page, in the
    first wiki holding one by that address.
    """

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        slug = kwargs["wiki"]
        readable = Wiki.objects.readable_by(request.user)
        wiki = readable.filter(slug=slug).first()

        if wiki is None:
            page = (
                readable_pages(request.user)
                .filter(slug=slug)
                .select_related("wiki")
                .order_by("wiki__position", "wiki__name", "wiki__pk")
                .first()
            )

            if page is None:
                raise Http404

            return redirect(page.get_absolute_url(), permanent=True)

        self.wiki = wiki
        first = (
            WikiPage.objects.filter(wiki=wiki, parent__isnull=True)
            .select_related("wiki")
            .order_by("position", "title")
            .first()
        )

        if first is not None:
            return redirect(first.get_absolute_url())

        return super().get(request, *args, **kwargs)


class WikiPageView(WikiViewMixin):
    def get(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        self.wiki = self.get_wiki(kwargs["wiki"])
        self.page = get_object_or_404(
            WikiPage.objects.select_related("wiki", "parent", "updated_by"),
            wiki=self.wiki,
            slug=kwargs["slug"],
        )

        return super().get(request, *args, **kwargs)


class WikiPdfView(View):
    """A whole wiki as one PDF, for whoever may read it.

    Downloaded, never cached by a shared cache, and written each time:
    it is the wiki as it stands.
    """

    def get(self, request: Any, wiki: str) -> Any:
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(), site.get_login_url()
            )

        if not pdf.available():
            raise Http404

        found = get_object_or_404(
            Wiki.objects.readable_by(request.user), slug=wiki
        )
        content = pdf.render(found, base_url=request.build_absolute_uri("/"))
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = content_disposition_header(
            True, f"{found.slug}.pdf"
        )
        protect(response)
        response["Cache-Control"] = "private, no-cache"

        return response


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
