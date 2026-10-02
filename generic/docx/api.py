"""The merge endpoint: ``POST api/generic/docx/merge/``.

Multipart, the files in the order they are merged:

==================  ===================================================
``documents``       one part per document, ``.docx`` or ``.dotx``
``template``        optional: the ``.docx`` or ``.dotx`` the result is
                    made from
``name``            optional: the name of the file sent back
``page_breaks``     optional, ``true`` by default: each document on a
                    new page
==================  ===================================================

Answers the merged ``.docx`` as a download, or ``400`` with
``{"detail"}`` saying what is wrong. Nothing is stored.
"""

from __future__ import annotations

from typing import Any

from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from generic.conf import generic_settings
from generic.docx.merge import DocxMergeError, docx_response, merge_docx
from generic.docx.permissions import MayMerge
from generic.openapi import framework_schema

#: What a form sends for "no".
FALSE_VALUES = ("0", "false", "no", "off")


class DocxMergeView(APIView):
    schema = framework_schema()
    #: What generic.openapi describes this body as; the answer is a file.
    openapi_request = "docx_merge"
    openapi_binary = True
    permission_classes = (MayMerge,)
    parser_classes = (MultiPartParser,)

    @staticmethod
    def refuse(message: str) -> Response:
        return Response(
            {"detail": message}, status=status.HTTP_400_BAD_REQUEST
        )

    def check_upload(self, upload: Any) -> str:
        """What is wrong with one file, or ``""``."""
        if not upload.size:
            return gettext("%(name)s is empty.") % {"name": upload.name}

        limit = generic_settings.FILE_MAX_SIZE

        if limit and upload.size > limit:
            return gettext("%(name)s is too large: at most %(limit)s.") % {
                "name": upload.name,
                "limit": filesizeformat(limit),
            }

        return ""

    def post(self, request: Any) -> Any:
        documents = request.FILES.getlist("documents")
        template = request.FILES.get("template")

        if not documents:
            return self.refuse(gettext("Choose at least one document."))

        most = generic_settings.DOCX_MERGE_MAX_FILES

        if most and len(documents) > most:
            return self.refuse(
                gettext("At most %(count)s documents can be merged at once.")
                % {"count": most}
            )

        for upload in [*documents, *([template] if template else [])]:
            problem = self.check_upload(upload)

            if problem:
                return self.refuse(problem)

        page_breaks = (
            str(request.data.get("page_breaks", "true")).strip().lower()
            not in FALSE_VALUES
        )

        try:
            content = merge_docx(
                documents, template=template, page_breaks=page_breaks
            )
        except DocxMergeError as error:
            return self.refuse(str(error))

        return docx_response(
            content, str(request.data.get("name") or "") or "merged.docx"
        )
