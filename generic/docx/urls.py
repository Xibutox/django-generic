"""The merge page. Mount it where it suits::

    path("docx/", include("generic.docx.urls")),

It sends the files to ``api/generic/docx/merge/``, in ``generic.urls``.
"""

from django.urls import path

from generic.docx import views

app_name = "generic_docx"

urlpatterns = [
    path("", views.DocxMergePage.as_view(), name="merge"),
]
