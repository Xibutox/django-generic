"""The wikis' pages: the list of wikis, a wiki's menu, one page, its
editor, and the whole wiki as a PDF.

A page is rendered by the server, with HTML cleaned on the way in and
on the way out, and edited in the browser: the editor saves through the
API, as JSON, like every other screen of the application.
"""

from __future__ import annotations

import mimetypes
import tempfile
from pathlib import PurePath
from typing import Any

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
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
from generic.sites.files import is_stored, may_download, protect
from generic.sites.views import SiteViewMixin
from generic.views.toolbar import Breadcrumb
from generic.wiki import archive, invitations, pdf, presence, sharing
from generic.wiki.access import (
    may_open,
    page_rights,
    roles_of,
    wiki_rights,
)
from generic.wiki.api import IMAGE_TYPES, can, readable_pages
from generic.wiki.headings import table_of_contents, with_anchors
from generic.wiki.markdown import to_markdown
from generic.wiki.models import (
    Wiki,
    WikiFile,
    WikiImage,
    WikiPage,
    WikiRedirect,
    WikiRevision,
    attachments_in,
)
from generic.wiki.sanitize import safe_html
from generic.wiki.search import search_pages_of
from generic.wiki.serializers import (
    WikiPageSerializer,
    WikiSerializer,
    display_name,
)
from generic.wiki.watching import is_watching


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


def build_menu(
    pages: list[WikiPage],
    current: WikiPage | None,
    url: Any = page_url,
) -> list:
    """The page tree as nested dicts, the current branch open; ``url``
    gives each page's address."""
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
                    "url": url(page),
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


def move_targets_of(user: Any, wiki: Wiki) -> list[Wiki]:
    """The other wikis ``user`` adds pages in: where a page of ``wiki``
    may move to."""
    roles = roles_of(user)

    return [
        other
        for other in Wiki.objects.writable_by(user)
        .exclude(pk=wiki.pk)
        .order_by("position", "name")
        if page_rights(user, other, roles, writable=True)["add"]
    ]


def list_rights(user: Any) -> dict[str, bool]:
    """What ``user`` may do on the list of wikis: make one, import one.
    What they may do to each wiki is the wiki's ``rights``."""
    add = can(user, "add", "wiki")

    # Whoever makes a wiki owns it, and so writes its pages.
    return {"add": add, "import": add}


class WikiListView(SiteViewMixin, TemplateView):
    """The wikis, each with its pages' count and its PDF.

    A reader who sees one wiki and may not add another goes straight
    to it: one wiki reads as it did before there could be several.
    """

    site = site
    template_name = "generic/wiki/index.html"

    def get_page_title(self) -> str:
        if getattr(self, "term", ""):
            return gettext("Search the wikis")

        return gettext("Wikis")

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [Breadcrumb(label=gettext("Wiki"))]

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        wikis = list(self.wikis())
        #: ``?q=``: the pages holding these words, in ``?wiki=`` or all.
        self.term = (request.GET.get("q") or "").strip()[:200]

        if (
            not self.term
            and len(wikis) == 1
            and not can(request.user, "add", "wiki")
        ):
            return redirect(wikis[0].get_absolute_url())

        self.wiki_list = wikis

        return super().get(request, *args, **kwargs)

    def wikis(self) -> Any:
        return (
            Wiki.objects.readable_by(self.request.user)
            .with_page_count()
            .select_related("owner")
            .order_by("position", "name")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        request = self.request
        user = request.user
        rights = list_rights(user)
        roles = roles_of(user)

        # What the reader may do to each: the card's buttons.
        for wiki in self.wiki_list:
            wiki.rights = wiki_rights(user, wiki, roles)

        trashed = [
            wiki
            for wiki in Wiki.all_objects.filter(
                deleted_at__isnull=False
            ).readable_by(user)
            if wiki_rights(user, wiki, roles)["delete"]
        ]

        scope = None

        if self.term and request.GET.get("wiki"):
            scope = next(
                (w for w in self.wiki_list if w.slug == request.GET["wiki"]),
                None,
            )

        context.update(
            term=self.term,
            scope=scope,
            results=(
                search_pages_of(request.user, self.term, wiki=scope)
                if self.term
                else None
            ),
            wikis=self.wiki_list,
            can=rights,
            trash_count=len(trashed),
            pdf_available=pdf.available(),
            archive_available=may_download(request),
            wikis_config={
                "api": reverse("generic_wiki:wiki-list"),
                "importUrl": reverse("generic_wiki:wiki-import"),
                "importMaxSize": generic_settings.WIKI_ARCHIVE_MAX_SIZE,
                "trashDays": generic_settings.TRASH_DAYS,
                "wikis": WikiSerializer(
                    self.wiki_list,
                    many=True,
                    context={"request": request, "roles": roles},
                ).data,
                # A copy of a wiki is its maker's: its pages come along.
                "can": {**rights, "addPage": rights["add"]},
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
        rights = page_rights(request.user, wiki)
        manages = wiki_rights(request.user, wiki)
        excluded = descendants_of(pages, page) if page is not None else set()
        others = Wiki.objects.readable_by(request.user).exclude(pk=wiki.pk)

        move_targets = (
            move_targets_of(request.user, wiki)
            if page is not None and rights["delete"]
            else []
        )

        content, headings = with_anchors(
            safe_html(page.content) if page else ""
        )

        context.update(
            content=content,
            contents=table_of_contents(headings),
            wiki=wiki,
            other_wikis=list(others.order_by("position", "name")),
            pdf_url=wiki.get_pdf_url() if pdf.available() else "",
            archive_url=(
                wiki.get_archive_url() if may_download(request) else ""
            ),
            page=page,
            menu=build_menu(pages, page),
            attachments=page.attachments() if page else [],
            can=rights,
            can_wiki=manages,
            move_targets=move_targets,
            page_pdf_url=(
                reverse(
                    "generic_wiki:page-pdf",
                    kwargs={"wiki": wiki.slug, "slug": page.slug},
                )
                if page is not None and pdf.available()
                else ""
            ),
            page_markdown_url=(
                reverse(
                    "generic_wiki:page-markdown",
                    kwargs={"wiki": wiki.slug, "slug": page.slug},
                )
                if page is not None
                else ""
            ),
            wiki_config={
                "wiki": wiki.pk,
                "wikiApi": reverse("generic_wiki:wiki-list"),
                "wikiName": wiki.name,
                "trashDays": generic_settings.TRASH_DAYS,
                "canWiki": manages,
                # Whether the reader is told when this page, or any page
                # of the wiki, changes.
                "watching": {
                    "page": page is not None
                    and is_watching(request.user, page),
                    "wiki": is_watching(request.user, wiki),
                },
                # Who reads it hears who edits it, and its comments.
                "me": request.user.pk,
                "topic": (
                    presence.TOPIC.format(page_id=page.pk)
                    if page is not None
                    else ""
                ),
                "editors": (
                    presence.editors(page, exclude=request.user.pk)
                    if page is not None
                    else []
                ),
                "editingBeat": presence.BEAT,
                # What a new page may start from.
                "templates": [
                    {"id": entry.pk, "title": entry.title}
                    for entry in WikiPage.objects.filter(
                        wiki=wiki, is_template=True
                    ).order_by("title")
                ],
                "importUrl": reverse("generic_wiki:page-import"),
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
                # What a copy of the page may take along.
                "subpages": len(excluded) - 1 if page is not None else 0,
                # The wikis the page may move to.
                "moveTargets": [
                    {"id": other.pk, "name": other.name}
                    for other in move_targets
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
        self.page = (
            WikiPage.objects.select_related("wiki", "parent", "updated_by")
            .filter(wiki=self.wiki, slug=kwargs["slug"])
            .first()
        )

        if self.page is None:
            # An address the page had before it was renamed.
            moved = (
                WikiRedirect.objects.filter(
                    wiki=self.wiki,
                    slug=kwargs["slug"],
                    page__deleted_at__isnull=True,
                )
                .select_related("page__wiki")
                .first()
            )

            if moved is None:
                raise Http404

            return redirect(moved.page.get_absolute_url(), permanent=True)

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        readable = Wiki.objects.readable_by(self.request.user)
        # The pages linking here, of the wikis the reader reads.
        context["backlinks"] = (
            list(self.page.backlinks().filter(wiki__in=readable)[:50])
            if self.page is not None
            else []
        )

        return context


class WikiRevisionView(WikiPageView):
    """One version of a page from its history, read-only: the page's
    layout with that version's title and text, a word saying so, and
    the way back to the page - or, for a writer, to restore it."""

    page: WikiPage
    revision: WikiRevision

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        self.wiki = self.get_wiki(kwargs["wiki"])
        self.page = get_object_or_404(
            WikiPage.objects.select_related("wiki", "parent", "updated_by"),
            wiki=self.wiki,
            slug=kwargs["slug"],
        )
        self.revision = get_object_or_404(
            self.page.revisions.select_related("author"),
            pk=kwargs["revision"],
        )

        return TemplateView.get(self, request, *args, **kwargs)

    def get_page_title(self) -> str:
        return self.revision.title

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        crumbs = super().get_breadcrumbs()
        crumbs[-1] = Breadcrumb(
            label=self.page.title, url=self.page.get_absolute_url()
        )
        crumbs.append(Breadcrumb(label=gettext("Earlier version")))

        return crumbs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        revision = self.revision
        current = self.page.current_revision()
        author = revision.author

        content, headings = with_anchors(safe_html(revision.content))
        context.update(
            revision=revision,
            revision_author=(
                (author.get_full_name() or author.get_username())
                if author is not None
                else ""
            ),
            revision_is_current=current is not None
            and current.pk == revision.pk,
            content=content,
            # This version's headings, not the page's.
            contents=table_of_contents(headings),
            attachments=attachments_in(revision.content),
        )
        # A version is read, not edited.
        context["wiki_config"]["edit"] = False
        # A version is not commented, nor edited.
        context["wiki_config"]["topic"] = ""

        return context


class WikiPdfView(View):
    """A whole wiki as one PDF, for whoever may read it - or one of its
    pages, under the page's address.

    Downloaded, never cached by a shared cache, and written each time:
    it is the wiki as it stands. ``?orientation=landscape`` turns the
    paper; anything else is portrait.
    """

    def get(self, request: Any, wiki: str, slug: str = "") -> Any:
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(), site.get_login_url()
            )

        if not pdf.available():
            raise Http404

        found = get_object_or_404(
            Wiki.objects.readable_by(request.user), slug=wiki
        )
        # ``wiki/<wiki>/<page>/export.pdf``: that page alone.
        page = (
            get_object_or_404(WikiPage, wiki=found, slug=slug)
            if slug
            else None
        )
        orientation = request.GET.get("orientation", "")

        if orientation not in pdf.ORIENTATIONS:
            orientation = pdf.ORIENTATIONS[0]

        content = pdf.render(
            found,
            base_url=request.build_absolute_uri("/"),
            orientation=orientation,
            page=page,
        )
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = content_disposition_header(
            True, f"{page.slug if page else found.slug}.pdf"
        )
        protect(response)
        response["Cache-Control"] = "private, no-cache"

        return response


class WikiMarkdownView(View):
    """A page as Markdown (``generic.wiki.markdown``), downloaded, for
    whoever may read it."""

    def get(self, request: Any, wiki: str, slug: str) -> Any:
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(), site.get_login_url()
            )

        page = get_object_or_404(
            readable_pages(request.user), wiki__slug=wiki, slug=slug
        )
        response = HttpResponse(
            to_markdown(page.content, page.title),
            content_type="text/markdown; charset=utf-8",
        )
        response["Content-Disposition"] = content_disposition_header(
            True, f"{page.slug}.md"
        )
        protect(response)
        response["Cache-Control"] = "private, no-cache"

        return response


class WikiArchiveView(View):
    """A whole wiki as an archive - its pages, images and files - that
    any site running the wiki imports (``generic.wiki.archive``).

    For whoever may read the wiki and download files: the archive holds
    the wiki's files.
    """

    def get(self, request: Any, wiki: str) -> Any:
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(), site.get_login_url()
            )

        found = get_object_or_404(
            Wiki.objects.readable_by(request.user), slug=wiki
        )

        if not may_download(request):
            raise PermissionDenied

        # On disk past a few megabytes: a wiki's files can be many.
        output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        archive.write_archive(found, output)
        output.seek(0)
        response = FileResponse(
            output,
            as_attachment=True,
            filename=archive.archive_name(found),
            content_type="application/zip",
        )
        protect(response)
        response["Cache-Control"] = "private, no-cache"

        return response


def serve_image(image: WikiImage) -> FileResponse:
    """An image, shown in the page (``inline``) as the type its bytes
    were found to be when uploaded, never sniffed as anything else."""
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


def serve_file(attachment: WikiFile) -> FileResponse:
    """A file, always downloaded, under the name it was uploaded with."""
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


class WikiImageView(View):
    """An image of a wiki, for whoever may read that wiki - or a page
    showing it (``generic.wiki.access.may_open``).

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

        # Not there, for whoever reads no wiki showing it.
        if not may_open(request.user, image):
            raise Http404

        return serve_image(image)


class WikiFileView(View):
    """A file of a wiki, for whoever may read that wiki - or a page
    linking to it (``generic.wiki.access.may_open``).

    Always a download (``attachment``), under the name it was uploaded
    with, and never sniffed: whatever somebody uploaded, it never runs
    in the site's origin. Not kept by a shared cache either.
    """

    def get(self, request: Any, pk: int) -> Any:
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(), site.get_login_url()
            )

        # Downloads given on request (ACCESS_ON_REQUEST) cover the
        # wiki's files too.
        if not may_download(request):
            raise PermissionDenied

        attachment = get_object_or_404(WikiFile, pk=pk)

        if not may_open(request.user, attachment):
            raise Http404

        return serve_file(attachment)


class WikiInvitationView(SiteViewMixin, TemplateView):
    """An invitation to join a wiki, from the link of its e-mail: who
    sent it, for which role, and the button to accept it."""

    site = site
    template_name = "generic/wiki/invitation.html"

    def get_page_title(self) -> str:
        return gettext("Invitation")

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [
            Breadcrumb(
                label=gettext("Wiki"), url=reverse("generic_wiki:index")
            ),
            Breadcrumb(label=gettext("Invitation")),
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        invitation = invitations.find(kwargs["secret"])
        context.update(
            invitation=invitation,
            problem=invitations.problem(invitation, self.request.user),
            role=(
                invitations.role_label(invitation.role) if invitation else ""
            ),
            invited_by=(
                display_name(invitation.invited_by)
                if invitation and invitation.invited_by_id
                else ""
            ),
        )

        return context

    def post(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        invitation = invitations.find(kwargs["secret"])

        try:
            wiki = invitations.accept(invitation, request.user)
        except invitations.InvitationError:
            return self.get(request, *args, **kwargs)

        messages.success(
            request,
            gettext("Welcome to the wiki \u201c%(name)s\u201d.")
            % {"name": wiki.name},
        )

        return redirect(wiki.get_absolute_url())


#: A shared page tells no other site its address, and is never indexed.
SHARED_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "private, no-store",
}


def shared_or_404(secret: str) -> Wiki:
    wiki = sharing.shared_wiki(secret)

    if wiki is None:
        raise Http404

    return wiki


class WikiSharedView(TemplateView):
    """A wiki's page from its public link (generic.wiki.sharing), for
    anyone: read-only, its menu and its text, nothing else."""

    template_name = "generic/wiki/shared.html"

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        self.wiki = wiki = shared_or_404(kwargs["secret"])
        slug = kwargs.get("slug")
        pages = WikiPage.objects.filter(wiki=wiki)

        if slug is None:
            self.page = (
                pages.filter(parent__isnull=True)
                .order_by("position", "title")
                .first()
            )
        else:
            self.page = pages.filter(slug=slug).first()

            if self.page is None:
                moved = WikiRedirect.objects.filter(
                    wiki=wiki, slug=slug, page__deleted_at__isnull=True
                ).first()

                # A page moved to another wiki is not shared with it.
                if moved is None or moved.page.wiki_id != wiki.pk:
                    raise Http404

                return redirect(sharing.link_of(wiki, moved.page.slug))

        response = super().get(request, *args, **kwargs)

        for header, value in SHARED_HEADERS.items():
            response[header] = value

        return response

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        wiki, page = self.wiki, self.page
        pages = list(
            WikiPage.objects.filter(wiki=wiki)
            .only("id", "title", "slug", "parent_id", "position")
            .order_by("position", "title")
        )
        content, headings = with_anchors(
            sharing.rewrite(safe_html(page.content), wiki) if page else ""
        )
        context.update(
            wiki=wiki,
            page=page,
            content=content,
            contents=table_of_contents(headings),
            menu=build_menu(
                pages,
                page,
                url=lambda entry: sharing.link_of(wiki, entry.slug),
            ),
            home=sharing.link_of(wiki),
        )

        return context


class WikiSharedImageView(View):
    """An image a page of a shared wiki shows, from under its link."""

    def get(self, request: Any, secret: str, pk: int) -> Any:
        wiki = shared_or_404(secret)
        image = get_object_or_404(WikiImage, pk=pk)

        if not sharing.shows(wiki, image):
            raise Http404

        response = serve_image(image)
        response["Referrer-Policy"] = "no-referrer"

        return response


class WikiSharedFileView(View):
    """A file a page of a shared wiki links to, from under its link."""

    def get(self, request: Any, secret: str, pk: int) -> Any:
        wiki = shared_or_404(secret)
        attachment = get_object_or_404(WikiFile, pk=pk)

        if not sharing.shows(wiki, attachment):
            raise Http404

        response = serve_file(attachment)
        response["Referrer-Policy"] = "no-referrer"

        return response
