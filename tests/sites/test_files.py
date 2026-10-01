"""Files in generated forms: read, sent, downloaded, refused.

``tests.testapp.Document`` holds a required ``file``, an optional
``scan`` limited to a few extensions, and an ``archive`` no screen
shows; ``DocumentResource`` hides the "Restricted" ones from everybody
but a superuser.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import serializers
from rest_framework.test import APIClient

from generic.api.files import accept_of
from generic.api.inlines import InlineFormDefinition
from generic.api.parsers import MultiPartJSONParser
from generic.checks import check_media_root
from generic.sites import Import, ModelResource, site
from generic.sites.editable import columns_of
from generic.sites.imports import check_import, is_importable_field
from generic.sites.serializers import build_form_serializer
from tests.factories import AuthorFactory, UserFactory
from tests.testapp.models import Document, DocumentNote

pytestmark = pytest.mark.django_db

API = "/api/testapp/document/"
PDF = b"%PDF-1.4\n% a small document\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def download(pk: int, field: str) -> str:
    return f"{API}{pk}/files/{field}/"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    """Every file of this module is written under its own folder."""
    settings.MEDIA_ROOT = str(tmp_path)

    return tmp_path


def signed_in(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)

    return client


def allowed(*codenames: str):
    user = UserFactory()
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="testapp", codename__in=codenames
        )
    )

    return user


@pytest.fixture
def admin(admin_user) -> APIClient:
    return signed_in(admin_user)


@pytest.fixture
def reader() -> APIClient:
    return signed_in(allowed("view_document"))


@pytest.fixture
def editor() -> APIClient:
    """May write documents, and their notes (an inline answers to its
    own model's permissions)."""
    return signed_in(
        allowed(
            "view_document",
            "add_document",
            "change_document",
            "view_documentnote",
            "add_documentnote",
            "change_documentnote",
        )
    )


def document(title: str = "Report", **files: tuple[str, bytes]) -> Document:
    record = Document(title=title)

    for field, (name, content) in (
        {"file": ("report.pdf", PDF), **files}
    ).items():
        getattr(record, field).save(name, ContentFile(content), save=False)

    record.save()

    return record


def upload(name: str, content: bytes, kind: str = "") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=kind)


class TestDownload:
    def test_a_pdf_is_a_download(self, reader):
        record = document()

        response = reader.get(download(record.pk, "file"))

        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert response["Content-Disposition"] == (
            'attachment; filename="report.pdf"'
        )
        assert b"".join(response.streaming_content) == PDF

    def test_a_png_is_shown(self, reader):
        record = document(scan=("scan.png", PNG))

        response = reader.get(download(record.pk, "scan"))

        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"
        assert response["Content-Disposition"] == 'inline; filename="scan.png"'

    @pytest.mark.parametrize(
        "name, kind",
        [("page.html", "text/html"), ("drawing.svg", "image/svg+xml")],
    )
    def test_a_page_or_an_svg_is_never_shown(self, reader, name, kind):
        """An uploaded page must not run script in the site's origin."""
        record = document(file=(name, b"<script>alert(1)</script>"))

        response = reader.get(download(record.pk, "file"))

        assert response.status_code == 200
        assert response["Content-Type"] == kind
        assert response["Content-Disposition"].startswith("attachment;")

    @pytest.mark.parametrize("field", ["file", "scan", "archive", "nothing"])
    def test_every_answer_is_sandboxed(self, reader, field):
        record = document(scan=("scan.png", PNG))

        response = reader.get(download(record.pk, field))

        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["Content-Security-Policy"] == "sandbox"

    def test_a_refusal_is_sandboxed_too(self):
        record = document()

        response = signed_in(UserFactory()).get(download(record.pk, "file"))

        assert response.status_code == 403
        assert response["Content-Security-Policy"] == "sandbox"

    def test_a_name_outside_ascii_is_encoded(self, reader):
        record = document(file=("relevé-été.pdf", PDF))

        response = reader.get(download(record.pk, "file"))

        assert response["Content-Disposition"] == (
            "attachment; filename*=utf-8''relev%C3%A9-%C3%A9t%C3%A9.pdf"
        )

    def test_without_the_view_permission_it_is_refused(self):
        record = document()

        response = signed_in(UserFactory()).get(download(record.pk, "file"))

        assert response.status_code == 403

    def test_signed_out_it_is_refused(self):
        record = document()

        response = APIClient().get(download(record.pk, "file"))

        assert response.status_code in (401, 403)

    def test_a_record_out_of_reach_is_not_found(self, reader, admin):
        record = document(title="Restricted report")

        assert reader.get(download(record.pk, "file")).status_code == 404
        assert admin.get(download(record.pk, "file")).status_code == 200

    @pytest.mark.parametrize("field", ["archive", "title", "authors", "nope"])
    def test_only_a_file_the_screens_show_is_served(self, reader, field):
        """``archive`` is a file field no screen shows: stored, never
        downloadable. The others are not files at all."""
        record = document(archive=("old.zip", b"PK"))

        response = reader.get(download(record.pk, field))

        assert response.status_code == 404

    def test_an_empty_field_is_not_found(self, reader):
        record = document()

        assert reader.get(download(record.pk, "scan")).status_code == 404

    def test_a_file_the_storage_lost_is_not_found(self, reader, media):
        record = document()
        (media / record.file.name).unlink()

        assert reader.get(download(record.pk, "file")).status_code == 404

    def test_any_storage_serves(self, reader, monkeypatch):
        """Read through the field's own storage, not the file system."""
        monkeypatch.setattr(
            Document._meta.get_field("file"), "storage", InMemoryStorage()
        )
        record = document()

        response = reader.get(download(record.pk, "file"))

        assert response.status_code == 200
        assert b"".join(response.streaming_content) == PDF

    def test_the_resource_names_its_download(self):
        resource = site.get_resource(Document)

        assert resource.get_file_url(7, "file") == download(7, "file")


class TestReading:
    def test_the_record_reads_a_file_as_an_object(self, reader):
        record = document()

        data = reader.get(f"{API}{record.pk}/").json()

        assert data["file"] == {
            "name": "report.pdf",
            "url": download(record.pk, "file"),
            "size": len(PDF),
        }
        assert data["scan"] is None

    def test_a_table_cell_reads_it_without_its_size(self, reader):
        record = document()

        row = reader.get(API, {"draw": 1}).json()["data"][0]

        assert row["file"] == {
            "name": "report.pdf",
            "url": download(record.pk, "file"),
            "size": None,
        }

    def test_the_column_is_drawn_as_a_file(self):
        columns = site.get_resource(Document).get_table_serializer_class()
        column = {
            entry["data"]: entry for entry in columns.get_datatable_columns()
        }["file"]

        assert column["type"] == "file"
        assert column["searchable"] is False

    def test_an_export_writes_the_name(self, reader):
        document()

        response = reader.get(f"{API}export-csv/")
        text = b"".join(response.streaming_content).decode("utf-8-sig")

        assert "Report;report.pdf" in text

    def test_the_summary_links_the_download(self, reader):
        record = document()

        summary = reader.get(f"{API}{record.pk}/summary/").json()
        entries = {
            entry["name"]: entry
            for section in summary["sections"]
            for entry in section["fields"]
        }

        assert entries["file"]["type"] == "file"
        assert entries["file"]["display"] == "report.pdf"
        assert entries["file"]["url"] == download(record.pk, "file")
        assert entries["file"]["value"]["size"] == len(PDF)
        assert entries["scan"] == {
            "type": "file",
            "empty": True,
            "name": "scan",
            "label": "Scan",
            "wide": False,
        }

    def test_a_missing_file_still_shows_its_name(self, reader, media):
        record = document()
        (media / record.file.name).unlink()

        data = reader.get(f"{API}{record.pk}/").json()

        assert data["file"]["name"] == "report.pdf"
        assert data["file"]["size"] is None


class TestSchema:
    def fields(self, client) -> dict:
        schema = client.get(f"{API}form-schema/").json()

        return {field["name"]: field for field in schema["fields"]}

    def test_a_file_field_says_what_it_takes(self, reader, settings):
        settings.GENERIC = {"FILE_MAX_SIZE": 2048}
        fields = self.fields(reader)

        assert fields["file"]["type"] == "file"
        assert fields["file"]["maxSize"] == 2048
        assert fields["file"]["required"] is True
        assert "accept" not in fields["file"]
        assert fields["scan"]["accept"] == ".png,.jpg,.jpeg,.pdf"
        assert fields["scan"]["allowNull"] is True
        assert fields["scan"]["required"] is False

    def test_the_default_limit_is_ten_megabytes(self, reader):
        assert self.fields(reader)["file"]["maxSize"] == 10 * 1024 * 1024

    def test_other_fields_carry_no_file_keys(self, reader):
        title = self.fields(reader)["title"]

        assert "maxSize" not in title
        assert "accept" not in title

    def test_an_image_field_takes_images(self):
        assert accept_of(serializers.ImageField()) == "image/*"
        assert accept_of(serializers.FileField()) is None

    def test_in_an_inline_a_file_is_only_shown(self):
        """A row travels in the parent's JSON, where no file can."""
        definition = InlineFormDefinition(
            name="documents",
            serializer_class=build_form_serializer(
                Document, fields=["title", "file"]
            ),
            related_name="documents",
            parent_field="title",
            title="Documents",
        )

        fields = {
            field["name"]: field for field in definition.get_form_fields()
        }

        assert fields["file"]["readOnly"] is True


class TestSending:
    def payload(self, client, method: str, url: str, data: dict, **parts):
        """What the form sends when a file was chosen: its JSON as
        ``_payload``, and one part per file (``HTTP_*``: headers)."""
        headers = {
            name: value
            for name, value in parts.items()
            if name.startswith("HTTP_")
        }
        files = {
            name: value for name, value in parts.items() if name not in headers
        }

        return getattr(client, method)(
            url,
            {"_payload": json.dumps(data), **files},
            format="multipart",
            **headers,
        )

    def test_a_new_record_is_written_with_its_file(self, editor, media):
        austen, bronte = AuthorFactory(), AuthorFactory()

        response = self.payload(
            editor,
            "post",
            API,
            {
                "title": "Minutes",
                "authors": [austen.pk, bronte.pk],
                "details": {"pages": 3, "tags": ["a", "b"]},
                "_inlines": {"notes": [{"text": "Read twice"}]},
            },
            file=upload("minutes.pdf", PDF, "application/pdf"),
        )

        assert response.status_code == 201, response.json()
        record = Document.objects.get(title="Minutes")
        assert (media / record.file.name).read_bytes() == PDF
        assert set(record.authors.all()) == {austen, bronte}
        assert record.details == {"pages": 3, "tags": ["a", "b"]}
        assert list(record.notes.values_list("text", flat=True)) == [
            "Read twice"
        ]
        assert response.json()["file"]["name"] == "minutes.pdf"

    def test_json_and_payload_write_the_same_record(self, editor):
        author = AuthorFactory()
        fields = {"authors": [author.pk], "details": {"n": 1}}
        record = document()

        json_answer = editor.patch(
            f"{API}{record.pk}/", {"title": "By JSON", **fields}, format="json"
        ).json()
        payload_answer = self.payload(
            editor,
            "patch",
            f"{API}{record.pk}/",
            {"title": "By payload", **fields},
            scan=upload("scan.png", PNG, "image/png"),
        ).json()

        for key in ("authors", "details"):
            assert payload_answer[key] == json_answer[key]

    def test_a_file_is_replaced_and_the_old_one_kept(self, editor, media):
        record = document()
        old = record.file.name

        response = self.payload(
            editor,
            "patch",
            f"{API}{record.pk}/",
            {},
            file=upload("second.pdf", PDF + b"2", "application/pdf"),
        )

        assert response.status_code == 200
        record.refresh_from_db()
        assert record.file.name != old
        assert (media / record.file.name).read_bytes() == PDF + b"2"
        # The history keeps versions naming it.
        assert (media / old).exists()

    def test_null_empties_an_optional_file(self, editor, media):
        record = document(scan=("scan.png", PNG))
        old = record.scan.name

        response = editor.patch(
            f"{API}{record.pk}/", {"scan": None}, format="json"
        )

        assert response.status_code == 200
        record.refresh_from_db()
        assert record.scan.name == ""
        assert response.json()["scan"] is None
        assert (media / old).exists()

    def test_null_in_a_payload_empties_it_too(self, editor):
        record = document(scan=("scan.png", PNG))

        response = self.payload(
            editor,
            "patch",
            f"{API}{record.pk}/",
            {"scan": None},
            file=upload("new.pdf", PDF, "application/pdf"),
        )

        assert response.status_code == 200
        record.refresh_from_db()
        assert record.scan.name == ""
        assert record.file.name.endswith(".pdf")

    def test_a_required_file_cannot_be_emptied(self, editor):
        record = document()

        response = editor.patch(
            f"{API}{record.pk}/", {"file": None}, format="json"
        )

        assert response.status_code == 400
        assert "file" in response.json()

    def test_a_new_record_needs_its_required_file(self, editor):
        response = editor.post(API, {"title": "No file"}, format="json")

        assert response.status_code == 400
        assert "file" in response.json()

    def test_a_file_over_the_limit_is_refused(self, editor, settings):
        settings.GENERIC = {"FILE_MAX_SIZE": 10}

        response = self.payload(
            editor,
            "post",
            API,
            {"title": "Big"},
            file=upload("big.pdf", PDF, "application/pdf"),
        )

        assert response.status_code == 400
        assert "10\xa0bytes" in response.json()["file"][0]
        assert not Document.objects.filter(title="Big").exists()

    def test_the_limit_is_translated(self, editor, settings):
        settings.GENERIC = {"FILE_MAX_SIZE": 10}

        response = self.payload(
            editor,
            "post",
            API,
            {"title": "Big"},
            file=upload("big.pdf", PDF, "application/pdf"),
            HTTP_ACCEPT_LANGUAGE="fr",
        )

        assert "trop volumineux" in response.json()["file"][0]

    def test_an_extension_the_field_refuses_is_refused(self, editor):
        record = document()

        response = self.payload(
            editor,
            "patch",
            f"{API}{record.pk}/",
            {},
            scan=upload("scan.exe", b"MZ", "application/octet-stream"),
        )

        assert response.status_code == 400
        assert "scan" in response.json()

    def test_json_alone_changes_nothing_of_the_file(self, editor):
        record = document()
        name = record.file.name

        response = editor.patch(
            f"{API}{record.pk}/", {"title": "Renamed"}, format="json"
        )

        assert response.status_code == 200
        record.refresh_from_db()
        assert (record.title, record.file.name) == ("Renamed", name)

    def test_classic_multipart_still_works(self, editor):
        """A script posting form fields and files, no ``_payload``."""
        austen, bronte = AuthorFactory(), AuthorFactory()

        response = editor.post(
            API,
            {
                "title": "Classic",
                "authors": [austen.pk, bronte.pk],
                "file": upload("classic.pdf", PDF, "application/pdf"),
                "_inlines": json.dumps({"notes": [{"text": "By a script"}]}),
            },
            format="multipart",
        )

        assert response.status_code == 201, response.json()
        record = Document.objects.get(title="Classic")
        assert set(record.authors.all()) == {austen, bronte}
        assert record.file.name.endswith(".pdf")
        assert DocumentNote.objects.filter(document=record).count() == 1

    @pytest.mark.parametrize("raw", ["{not json", "[1, 2]"])
    def test_a_payload_that_is_not_an_object_is_refused(self, editor, raw):
        response = editor.post(
            API,
            {"_payload": raw, "file": upload("x.pdf", PDF)},
            format="multipart",
        )

        assert response.status_code == 400
        assert "_payload" in response.json()["detail"]


class TestTheParser:
    def test_it_is_multipart(self):
        assert MultiPartJSONParser.media_type == "multipart/form-data"

    def test_the_resource_endpoint_reads_json_payloads_and_forms(self):
        from generic.api.viewsets import FORM_PARSERS

        viewset = site.get_resource(Document).get_viewset_class()

        assert viewset.parser_classes == FORM_PARSERS
        assert MultiPartJSONParser in FORM_PARSERS


class TestWhatFilesCannotDo:
    def test_a_grid_cannot_edit_a_file(self):
        class FileGrid(ModelResource):
            list_display = ("title", "file")
            editable_fields = ("file",)

        with pytest.raises(ImproperlyConfigured) as refusal:
            columns_of(FileGrid(Document, site))

        assert "FileGrid" in str(refusal.value)
        assert "file field" in str(refusal.value)

    def test_an_import_cannot_fill_a_file(self):
        class FileImport(ModelResource):
            imports = Import(fields=("title", "file"))

        assert not is_importable_field(Document._meta.get_field("file"))

        with pytest.raises(ImproperlyConfigured) as refusal:
            check_import(FileImport(Document, site))

        assert "FileImport" in str(refusal.value)


class TestTheCheck:
    def test_an_empty_media_root_is_named(self, settings):
        settings.MEDIA_ROOT = ""

        messages = check_media_root()

        assert [message.id for message in messages] == ["generic.W010"]
        assert "testapp.Document" in messages[0].msg
        # The wiki's images and files are files too; a model without any is not
        # named.
        assert "generic_wiki.WikiImage" in messages[0].msg
        assert "generic_wiki.WikiFile" in messages[0].msg
        assert "testapp.Manuscript" not in messages[0].msg

    def test_a_media_root_says_nothing(self, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)

        assert check_media_root() == []
