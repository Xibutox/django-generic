"""Word files merged with a template (generic.docx)."""

from __future__ import annotations

import io
import zipfile

import pytest
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.fields.files import FieldFile, FileField
from docx import Document

from generic.docx import (
    DOCX_CONTENT_TYPE,
    DocxMergeError,
    docx_name,
    docx_response,
    merge_docx,
)
from generic.docx.merge import DOCUMENT_MAIN, MAX_UNPACKED_SIZE, TEMPLATE_MAIN
from tests.factories import UserFactory

MERGE = "/api/generic/docx/merge/"
PAGE = "/docx/"


def word(*paragraphs: str, header: str = "", table: bool = False) -> bytes:
    """A .docx holding ``paragraphs``, a header, a table."""
    document = Document()

    if header:
        document.sections[0].header.paragraphs[0].text = header

    for text in paragraphs:
        document.add_paragraph(text)

    if table:
        document.add_table(rows=1, cols=2).cell(0, 0).text = "cell"

    output = io.BytesIO()
    document.save(output)

    return output.getvalue()


def as_template(data: bytes) -> bytes:
    """``data`` turned into a .dotx: its main part's type renamed."""
    source = zipfile.ZipFile(io.BytesIO(data))
    output = io.BytesIO()

    with zipfile.ZipFile(output, "w") as copy:
        for info in source.infolist():
            content = source.read(info)

            if info.filename == "[Content_Types].xml":
                content = (
                    content.decode()
                    .replace(DOCUMENT_MAIN, TEMPLATE_MAIN)
                    .encode()
                )

            copy.writestr(info, content)

    return output.getvalue()


def read(data: bytes):
    return Document(io.BytesIO(data))


def texts(data: bytes) -> list[str]:
    return [paragraph.text for paragraph in read(data).paragraphs]


def breaks(data: bytes) -> int:
    return sum(
        1
        for paragraph in read(data).paragraphs
        for run in paragraph.runs
        if 'w:type="page"' in run._r.xml
    )


class TestMerge:
    def test_without_a_template_the_first_document_is_the_base(self):
        merged = merge_docx(
            [word("A1", "A2", header="First"), word("B1")],
            page_breaks=False,
        )

        assert texts(merged) == ["A1", "A2", "B1"]
        assert read(merged).sections[0].header.paragraphs[0].text == "First"

    def test_a_template_gives_its_header_and_receives_them_in_order(self):
        template = word(header="Letterhead")

        merged = merge_docx(
            [word("B"), word("A"), word("C")],
            template=template,
            page_breaks=False,
        )

        # The template's one empty paragraph is not left at the top.
        assert texts(merged) == ["B", "A", "C"]
        header = read(merged).sections[0].header.paragraphs[0].text
        assert header == "Letterhead"

    def test_a_dotx_template_is_taken(self):
        template = as_template(word(header="From a .dotx"))

        merged = merge_docx([word("A")], template=template)

        assert texts(merged) == ["A"]
        header = read(merged).sections[0].header.paragraphs[0].text
        assert header == "From a .dotx"

    def test_a_dotx_document_is_taken(self):
        merged = merge_docx([word("A"), as_template(word("B"))])

        assert [text for text in texts(merged) if text] == ["A", "B"]

    def test_the_placeholder_marks_where_they_go(self):
        template = word("Dear all,", "{{documents}}", "Regards")

        merged = merge_docx(
            [word("A"), word("B")], template=template, page_breaks=False
        )

        assert texts(merged) == ["Dear all,", "A", "B", "Regards"]

    def test_a_template_with_text_has_them_after_it(self):
        merged = merge_docx(
            [word("A")], template=word("Cover"), page_breaks=False
        )

        assert texts(merged) == ["Cover", "A"]

    def test_each_document_starts_a_new_page(self):
        # Two documents after a template's text: one break each.
        assert breaks(merge_docx([word("A"), word("B")], word("Cover"))) == 2
        # The first one at the top of an empty template needs none.
        assert breaks(merge_docx([word("A"), word("B")], word())) == 1
        assert breaks(merge_docx([word("A"), word("B")])) == 1
        assert (
            breaks(merge_docx([word("A"), word("B")], page_breaks=False)) == 0
        )

    def test_tables_come_along(self):
        merged = merge_docx([word("A"), word("B", table=True)])

        assert len(read(merged).tables) == 1

    def test_paths_files_and_field_files_are_read(self, tmp_path):
        path = tmp_path / "a.docx"
        path.write_bytes(word("From a path"))
        storage = FileSystemStorage(location=tmp_path)
        storage.save("stored.docx", ContentFile(word("From a field")))
        field = FileField(storage=storage)
        stored = FieldFile(None, field, "stored.docx")
        upload = SimpleUploadedFile("c.docx", word("From an upload"))
        upload.read()  # left at its end: read again from the start

        merged = merge_docx(
            [path, str(path), stored, upload, io.BytesIO(word("Bytes"))],
            page_breaks=False,
        )

        assert texts(merged) == [
            "From a path",
            "From a path",
            "From a field",
            "From an upload",
            "Bytes",
        ]

    def test_nothing_to_merge_is_refused(self):
        with pytest.raises(DocxMergeError):
            merge_docx([])

    @pytest.mark.parametrize(
        "content",
        [b"not a zip", b"PK\x03\x04broken", b"\xd0\xcf\x11\xe0 an old .doc"],
    )
    def test_what_is_no_word_file_is_refused_by_name(self, content):
        upload = SimpleUploadedFile("notes.doc", content)

        with pytest.raises(DocxMergeError, match="notes.doc"):
            merge_docx([upload])

    def test_a_spreadsheet_is_refused(self):
        output = io.BytesIO()

        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<Types><Override ContentType="application/vnd.'
                'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"'
                "/></Types>",
            )

        with pytest.raises(DocxMergeError, match="not a Word file"):
            merge_docx([SimpleUploadedFile("t.xlsx", output.getvalue())])

    def test_a_file_claiming_to_be_a_document_and_broken_is_refused(self):
        output = io.BytesIO()

        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                f'<Types><Override ContentType="{DOCUMENT_MAIN}"/></Types>',
            )

        with pytest.raises(DocxMergeError, match="could not be read"):
            merge_docx([SimpleUploadedFile("x.docx", output.getvalue())])

    def test_a_file_inflating_too_far_is_refused(self, monkeypatch):
        assert MAX_UNPACKED_SIZE > 1000
        monkeypatch.setattr("generic.docx.merge.MAX_UNPACKED_SIZE", 1000)

        with pytest.raises(DocxMergeError, match="too large"):
            merge_docx([SimpleUploadedFile("big.docx", word("A" * 2000))])

    def test_an_empty_field_is_refused(self, tmp_path):
        field = FileField(storage=FileSystemStorage(location=tmp_path))

        with pytest.raises(DocxMergeError, match="no file"):
            merge_docx([FieldFile(None, field, "")])


class TestResponse:
    def test_it_is_a_download(self):
        response = docx_response(b"content", "Rapport final")

        assert response["Content-Type"] == DOCX_CONTENT_TYPE
        assert response["Content-Disposition"] == (
            'attachment; filename="Rapport final.docx"'
        )
        assert response["X-Content-Type-Options"] == "nosniff"

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("", "merged.docx"),
            ("report", "report.docx"),
            ("report.docx", "report.docx"),
            ("letter.DOTX", "letter.docx"),
            ("../../etc/passwd", "passwd.docx"),
            ("C:\\Users\\me\\a.docx", "a.docx"),
            ('a"b<c>.docx', "abc.docx"),
            ("...", "merged.docx"),
        ],
    )
    def test_names_are_made_safe(self, name, expected):
        assert docx_name(name) == expected


def upload(name: str, content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=DOCX_CONTENT_TYPE)


@pytest.mark.django_db
class TestEndpoint:
    def test_a_signed_in_user_merges_in_the_order_sent(self, auth_client):
        response = auth_client.post(
            MERGE,
            {
                "documents": [
                    upload("b.docx", word("B")),
                    upload("a.docx", word("A")),
                ],
                "template": upload("t.dotx", as_template(word(header="H"))),
                "name": "Dossier",
                "page_breaks": "false",
            },
        )

        assert response.status_code == 200
        assert response["Content-Type"] == DOCX_CONTENT_TYPE
        assert "Dossier.docx" in response["Content-Disposition"]
        assert texts(response.content) == ["B", "A"]

    def test_page_breaks_are_the_default(self, auth_client):
        response = auth_client.post(
            MERGE,
            {
                "documents": [
                    upload("a.docx", word("A")),
                    upload("b.docx", word("B")),
                ]
            },
        )

        assert response.status_code == 200
        assert breaks(response.content) == 1
        assert "merged.docx" in response["Content-Disposition"]

    def test_signed_out_nobody_merges(self, client):
        response = client.post(
            MERGE, {"documents": [upload("a.docx", word("A"))]}
        )

        assert response.status_code == 403

    def test_the_setting_restricts_who_merges(self, client, settings):
        settings.GENERIC = {
            "DOCX_MERGE_PERMISSION": "generic_wiki.change_wikipage"
        }
        user = UserFactory()
        client.force_login(user)
        body = lambda: {"documents": [upload("a.docx", word("A"))]}  # noqa

        assert client.post(MERGE, body()).status_code == 403
        assert client.get(PAGE).status_code == 403

        user.user_permissions.add(
            Permission.objects.get(codename="change_wikipage")
        )
        client.force_login(user)

        assert client.post(MERGE, body()).status_code == 200
        assert client.get(PAGE).status_code == 200

    def test_without_documents_it_says_so(self, auth_client):
        response = auth_client.post(
            MERGE, {"template": upload("t.docx", word())}
        )

        assert response.status_code == 400
        assert "at least one" in response.json()["detail"]

    def test_too_many_documents_are_refused(self, auth_client, settings):
        settings.GENERIC = {"DOCX_MERGE_MAX_FILES": 2}

        response = auth_client.post(
            MERGE,
            {
                "documents": [
                    upload(f"{index}.docx", word(str(index)))
                    for index in range(3)
                ]
            },
        )

        assert response.status_code == 400
        assert "At most 2" in response.json()["detail"]

    def test_a_file_over_the_limit_is_refused(self, auth_client, settings):
        content = word("A")
        settings.GENERIC = {"FILE_MAX_SIZE": len(content) - 1}

        response = auth_client.post(
            MERGE,
            {
                "documents": [upload("a.docx", word("A"))],
            },
        )

        assert response.status_code == 400
        assert "a.docx is too large" in response.json()["detail"]

    def test_a_template_over_the_limit_is_refused(self, auth_client, settings):
        settings.GENERIC = {"FILE_MAX_SIZE": len(word("A")) + 10}

        response = auth_client.post(
            MERGE,
            {
                "documents": [upload("a.docx", word("A"))],
                "template": upload("t.docx", word("Cover" * 5000)),
            },
        )

        assert response.status_code == 400
        assert "t.docx is too large" in response.json()["detail"]

    def test_an_empty_file_is_refused(self, auth_client):
        response = auth_client.post(
            MERGE, {"documents": [upload("a.docx", b"")]}
        )

        assert response.status_code == 400

    def test_what_is_no_word_file_is_named(self, auth_client):
        response = auth_client.post(
            MERGE,
            {
                "documents": [
                    upload("a.docx", word("A")),
                    upload("photo.png", b"\x89PNG\r\n\x1a\n"),
                ]
            },
        )

        assert response.status_code == 400
        assert "photo.png" in response.json()["detail"]

    def test_only_post_is_answered(self, auth_client):
        assert auth_client.get(MERGE).status_code == 405


@pytest.mark.django_db
class TestPage:
    def test_it_offers_the_endpoint(self, auth_client):
        response = auth_client.get(PAGE)

        assert response.status_code == 200
        assert response.context["merge_config"] == {
            "url": MERGE,
            "maxFiles": 50,
            "maxSize": 10 * 1024 * 1024,
        }
        assert b"generic/js/docx.js" in response.content
        assert b"{{ documents }}" in response.content

    def test_signed_out_it_asks_to_sign_in(self, client):
        response = client.get(PAGE)

        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_it_is_in_the_navigation(self, auth_client):
        response = auth_client.get("/")

        assert b'href="/docx/"' in response.content
