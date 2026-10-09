"""The *Merge uploaded Word files* page: files uploaded for the
occasion, put in order, merged with an uploaded template, sent back.
Nothing is kept.

Off unless ``DOCUMENT_UPLOAD_MERGE = True`` in the settings: the page
answers 404 and the navigation does not offer it. On, any signed-in
person may use it. The merging itself is :mod:`documents.merge`.

A GET draws the page. The page keeps the chosen files in the browser,
in the order the reader puts them, and sends them all in one POST with
the template: the answer is the merged ``.docx``, or ``{"detail": ...}``
saying what went wrong, every file still chosen.

The uploads are read into memory - never into Django's temporary
files, whatever ``FILE_UPLOAD_MAX_MEMORY_SIZE`` says - up to
``DOCUMENT_UPLOAD_MERGE_MAX_SIZE`` for the whole request, merged, and
dropped with the request.

To take it to another project on the framework, copy this file,
``merge.py``, ``templates/documents/upload_merge.html`` and
``static/documents/upload_merge.js`` and ``merge.css`` into an app of
its own, keeping those paths (``merge.py`` is imported relatively);
then mount the page before ``site.urls`` and call :func:`add_link`
from a ``resources.py`` (see ``docsite/urls.py`` and ``resources.py``
here).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.files.uploadhandler import (
    MemoryFileUploadHandler,
    StopUpload,
)
from django.http import Http404, JsonResponse
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.generic import TemplateView

from generic.sites.views import SiteViewMixin
from generic.views.toolbar import Breadcrumb

from .merge import PLACEHOLDER

#: Documents merged at once, at most, the template aside.
MAX_FILES = 50

#: Bytes one merge may upload, every file together, unless the settings
#: say ``DOCUMENT_UPLOAD_MERGE_MAX_SIZE``.
MAX_SIZE = 50 * 1024 * 1024

#: What the file pickers offer; the server reads the files themselves.
ACCEPT = ".docx,.dotx"

#: What the page's script says, translated here: the framework's
#: JavaScript catalog does not hold this project's sentences.
TEXTS = (
    gettext_noop("%(count)s file(s), %(size)s"),
    gettext_noop("Not a Word file (.docx or .dotx): %(names)s"),
    gettext_noop("At most %(count)s files can be merged at once."),
    gettext_noop("The files weigh more than %(size)s together."),
    gettext_noop("The merged file is ready."),
    gettext_noop("The request failed. Please try again."),
)

#: The page's route name, mounted by the project's urls.py.
ROUTE = "documents-upload-merge"


def is_enabled() -> bool:
    return bool(getattr(settings, "DOCUMENT_UPLOAD_MERGE", False))


def max_size() -> int:
    return int(getattr(settings, "DOCUMENT_UPLOAD_MERGE_MAX_SIZE", MAX_SIZE))


def may_use(user: Any) -> bool:
    """Whether ``user`` is offered the page: it is on and they are
    signed in."""
    return is_enabled() and bool(user is not None and user.is_authenticated)


def add_link(site: Any, group: Any = "") -> None:
    """The page's entry in the navigation, for whoever :func:`may_use`
    lets in - nobody while the setting is off."""
    site.add_link(
        _("Merge uploaded Word files"),
        route=ROUTE,
        icon="upload_file",
        group=group,
        permission=may_use,
    )


class InMemoryUploadHandler(MemoryFileUploadHandler):
    """Every uploaded file held in memory, up to a total for the request.

    Django's own handler steps aside above ``FILE_UPLOAD_MAX_MEMORY_SIZE``
    and the next one writes a temporary file: here nothing reaches the
    disk, and a request beyond ``limit`` is read no further.
    """

    def __init__(self, request: Any = None, limit: int = 0) -> None:
        super().__init__(request)
        self.limit = limit
        self.received = 0
        self.exceeded = False

    def handle_raw_input(self, *args: Any, **kwargs: Any) -> None:
        super().handle_raw_input(*args, **kwargs)
        self.activated = True

    def receive_data_chunk(self, raw_data: bytes, start: int) -> Any:
        self.received += len(raw_data)

        if self.received > self.limit:
            self.exceeded = True
            raise StopUpload(connection_reset=False)

        return super().receive_data_chunk(raw_data, start)


def error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"detail": message}, status=status)


class UploadMergePage(SiteViewMixin, TemplateView):
    """Word files uploaded, in order, merged with a template."""

    template_name = "documents/upload_merge.html"
    page_title = _("Merge uploaded Word files")
    page_subtitle = _(
        "Upload Word files, put them in order, add a template: the "
        "merged file comes back, and nothing is kept."
    )

    @classmethod
    def as_view(cls, **initkwargs: Any) -> Any:
        # The CSRF check reads the POST, which parses the uploads: it
        # runs in dispatch(), once the upload handler is in place.
        return csrf_exempt(super().as_view(**initkwargs))

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        if not is_enabled():
            raise Http404

        if request.method == "POST":
            request.upload_handlers = [
                InMemoryUploadHandler(request, max_size())
            ]

        protected = csrf_protect(super().dispatch)

        return protected(request, *args, **kwargs)

    def has_permission(self) -> bool:
        return may_use(self.request.user)

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [Breadcrumb(label=gettext("Merge uploaded Word files"))]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "upload_merge_config": {
                    "url": self.request.path,
                    "maxFiles": MAX_FILES,
                    "maxSize": max_size(),
                    "texts": {text: gettext(text) for text in TEXTS},
                },
                "accept": ACCEPT,
                "placeholder": PLACEHOLDER,
            }
        )

        return context

    def post(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        from .merge import DocxMergeError, docx_response, merge_docx

        documents = request.FILES.getlist("documents")
        template = request.FILES.get("template")

        if getattr(request.upload_handlers[0], "exceeded", False):
            return error(
                gettext("The files weigh more than %(size)s MB together.")
                % {"size": round(max_size() / 1024 / 1024)},
                status=413,
            )

        if not documents:
            return error(gettext("Choose at least one document."))

        if len(documents) > MAX_FILES:
            return error(
                gettext("At most %(count)s files can be merged at once.")
                % {"count": MAX_FILES}
            )

        try:
            content = merge_docx(
                documents,
                template=template,
                page_breaks=bool(request.POST.get("page_breaks")),
            )
        except DocxMergeError as problem:
            return error(str(problem))

        return docx_response(content, request.POST.get("name", ""))
