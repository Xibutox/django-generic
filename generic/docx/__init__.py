"""Word files merged with a template (the ``docx`` extra).

:func:`merge_docx` puts ``.docx`` / ``.dotx`` files together into one
document made from a template; :func:`docx_response` sends the result.
Both work in any view, on any model's files. Installed as an app -
``"generic.docx"`` in ``INSTALLED_APPS`` - it adds a page where people
merge files they upload, and its endpoint (``docs/docx.md``).
"""

from generic.docx.merge import (
    DOCX_CONTENT_TYPE,
    PLACEHOLDER,
    DocxMergeError,
    docx_name,
    docx_response,
    merge_docx,
)

__all__ = [
    "DOCX_CONTENT_TYPE",
    "PLACEHOLDER",
    "DocxMergeError",
    "docx_name",
    "docx_response",
    "merge_docx",
]
