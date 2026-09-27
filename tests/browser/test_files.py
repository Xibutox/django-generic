"""Files: a ticket's attachment, and the images of a wiki page."""

from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path

import pytest
from django.core.files.base import ContentFile
from playwright.sync_api import expect

from generic.wiki.models import WikiImage, WikiPage

NOTES = b"The customer's notes: the reset link expired twice.\n"
SECOND = b"Second thoughts: it was the mail filter.\n"


def tiny_png() -> bytes:
    """A real PNG, one red pixel, that a browser can draw."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


def upload(name: str, content: bytes, kind: str = "text/plain") -> dict:
    """A file for ``set_input_files``, made in memory."""
    return {"name": name, "mimeType": kind, "buffer": content}


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    """Every file these tests write, in a folder of the test's own."""
    settings.MEDIA_ROOT = str(tmp_path)

    return tmp_path


@pytest.fixture
def attached(desk):
    """SD-1001, with a file attached already."""
    ticket = desk["login"]
    ticket.attachment.save("first.txt", ContentFile(NOTES))

    return ticket


def attachment(page):
    """The attachment's box on the ticket's form."""
    return page.locator('.sf-field[data-field="attachment"]')


def change_page(ticket) -> str:
    return f"/example/ticket/{ticket.pk}/change/"


def record_page(ticket) -> str:
    return f"/example/ticket/{ticket.pk}/"


def summary_attachment(page):
    """The Attachment line of a ticket's page."""
    return page.locator(".summary-field").filter(
        has=page.locator("dt", has_text="Attachment")
    )


def save(page, ticket):
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page).to_have_url(re.compile(re.escape(record_page(ticket)) + "$"))


# -- a ticket's attachment ------------------------------------------------


def test_a_file_is_attached_shown_and_downloaded(page, desk, admin, sign_in):
    sign_in(admin)
    ticket = desk["login"]
    page.goto(change_page(ticket))
    field = attachment(page)
    expect(field.locator(".sf-file__current")).to_contain_text("No file")

    field.locator(".sf-file__input").set_input_files(
        upload("notes.txt", NOTES)
    )

    # Named, and weighed, before anything is sent.
    chosen = field.locator(".sf-file__chosen")
    expect(chosen.locator(".sf-file__name")).to_have_text("notes.txt")
    expect(chosen.locator(".sf-file__size")).to_have_text(
        f"{len(NOTES)} bytes"
    )

    save(page, ticket)

    link = summary_attachment(page).get_by_role("link", name="notes.txt")
    expect(link).to_have_attribute(
        "href", f"/api/example/ticket/{ticket.pk}/files/attachment/"
    )
    with page.expect_download() as download:
        link.click()

    assert download.value.suggested_filename == "notes.txt"
    assert Path(download.value.path()).read_bytes() == NOTES

    ticket.refresh_from_db()
    assert ticket.attachment.name.startswith("tickets/")
    assert ticket.attachment.name.endswith(".txt")
    with ticket.attachment.open("rb") as stored:
        assert stored.read() == NOTES


def test_a_file_is_replaced_then_removed(page, attached, admin, sign_in):
    sign_in(admin)
    page.goto(change_page(attached))
    field = attachment(page)
    expect(field.locator(".sf-file__current")).to_contain_text("first.txt")

    field.locator(".sf-file__input").set_input_files(
        upload("second.txt", SECOND)
    )
    expect(field.locator(".sf-file__current")).to_contain_text(
        "Replaced when you save."
    )
    save(page, attached)

    line = summary_attachment(page)
    expect(line.get_by_role("link", name="second.txt")).to_be_visible()
    expect(line.get_by_role("link", name="first.txt")).to_have_count(0)
    attached.refresh_from_db()
    assert attached.attachment.name.endswith(".txt")
    with attached.attachment.open("rb") as stored:
        assert stored.read() == SECOND

    page.goto(change_page(attached))
    expect(field.locator(".sf-file__current")).to_contain_text("second.txt")
    field.get_by_role("button", name="Remove").click()
    expect(field.locator(".sf-file__current")).to_contain_text(
        "Removed when you save."
    )
    save(page, attached)

    expect(line).to_be_visible()
    expect(line.get_by_role("link")).to_have_count(0)
    expect(page.locator(".summary-file")).to_have_count(0)
    attached.refresh_from_db()
    assert attached.attachment.name == ""


def test_a_file_too_large_or_of_another_kind_is_refused_before_sending(
    page, desk, admin, sign_in, settings
):
    # A small limit keeps the file too large a small one.
    settings.GENERIC = {**settings.GENERIC, "FILE_MAX_SIZE": 1024}
    sign_in(admin)
    ticket = desk["login"]
    page.goto(change_page(ticket))
    field = attachment(page)
    expect(field.locator(".sf-file__current")).to_contain_text("No file")

    # From here on, nothing may reach the ticket's endpoint.
    sent = []
    page.on(
        "request",
        lambda request: (
            sent.append(f"{request.method} {request.url}")
            if f"/api/example/ticket/{ticket.pk}/" in request.url
            else None
        ),
    )
    errors = field.locator(".sf-errors")

    field.locator(".sf-file__input").set_input_files(
        upload("big.txt", b"x" * 2048)
    )
    expect(errors).to_contain_text("big.txt is too large")
    expect(errors).to_contain_text("the limit is 1")
    expect(field).to_have_class(re.compile(r"\bhas-error\b"))
    expect(field.locator(".sf-file__chosen")).to_be_hidden()

    field.locator(".sf-file__input").set_input_files(
        upload("tool.exe", b"MZ\x90\x00", "application/octet-stream")
    )
    expect(errors).to_contain_text(
        "tool.exe is not a kind of file this field takes"
    )
    expect(field.locator(".sf-file__chosen")).to_be_hidden()

    # Neither was kept for later: the form has nothing to send.
    page.get_by_role("button", name="Save and continue editing").click()
    expect(page.locator(".toast")).to_contain_text("There is nothing to save.")
    assert sent == []
    ticket.refresh_from_db()
    assert ticket.attachment.name == ""


def test_a_reader_downloads_the_attachment(page, attached, viewer, sign_in):
    sign_in(viewer)
    page.goto(record_page(attached))

    link = summary_attachment(page).get_by_role("link", name="first.txt")
    with page.expect_download() as download:
        link.click()

    assert Path(download.value.path()).read_bytes() == NOTES


def test_the_download_is_refused_without_the_view_permission(
    page, attached, sign_in, django_user_model
):
    stranger = django_user_model.objects.create_user(
        username="stranger",
        email="stranger@example.test",
        password="demo",
    )
    sign_in(stranger)

    # Signed in, as the session proves...
    preferences = page.request.get("/api/generic/account/preferences/")
    assert preferences.status == 200

    # ...and still refused the ticket's file.
    response = page.request.get(
        f"/api/example/ticket/{attached.pk}/files/attachment/"
    )

    assert response.status in (403, 404)
    assert response.body() != NOTES


# -- the wiki's images ----------------------------------------------------


@pytest.fixture
def handbook(transactional_db):
    return WikiPage.objects.create(
        title="Handbook",
        slug="handbook",
        content="<p>How the desk works.</p>",
    )


def open_image_dialog(page):
    """Edit the handbook, and ask the editor for an image."""
    page.goto("/wiki/handbook/")
    page.get_by_role("button", name="Edit").click()
    editor = page.locator("#wiki-editor .ql-editor")
    expect(editor).to_contain_text("How the desk works.")
    editor.click()
    page.locator(".ql-toolbar .ql-image").click()

    dialog = page.get_by_role("dialog")
    expect(
        dialog.get_by_role("heading", name="Insert an image")
    ).to_be_visible()
    expect(dialog).to_contain_text("Upload an image")

    return editor, dialog


def test_an_uploaded_image_is_drawn_on_the_page(
    page, handbook, admin, sign_in
):
    sign_in(admin)
    editor, dialog = open_image_dialog(page)

    with page.expect_response(
        lambda response: response.url.endswith("/api/generic/wiki/images/")
        and response.request.method == "POST"
    ) as uploaded:
        dialog.locator('input[type="file"]').set_input_files(
            upload("dot.png", tiny_png(), "image/png")
        )

    assert uploaded.value.status == 201
    image = WikiImage.objects.get()
    address = f"/wiki/images/{image.pk}/"
    expect(editor.locator("img")).to_have_attribute("src", address)

    page.locator(".wiki__editor-actions").get_by_role(
        "button", name="Save"
    ).click()

    # The page as a reader gets it, drawn by the server again.
    expect(page.locator(".toast")).to_contain_text("The page was saved.")
    picture = page.locator(".wiki-content img")
    expect(picture).to_have_attribute("src", address)
    page.wait_for_function(
        "() => {"
        "  const img = document.querySelector('.wiki-content img');"
        "  return img && img.complete;"
        "}"
    )
    assert picture.evaluate("img => img.naturalWidth") > 0
    handbook.refresh_from_db()
    assert address in handbook.content


def test_a_text_file_is_refused_as_an_image(page, handbook, admin, sign_in):
    sign_in(admin)
    editor, dialog = open_image_dialog(page)
    sent = []
    page.on(
        "request",
        lambda request: (
            sent.append(request.url)
            if "/wiki/images/" in request.url
            else None
        ),
    )

    dialog.locator('input[type="file"]').set_input_files(
        upload("notes.txt", NOTES)
    )

    expect(page.locator(".toast")).to_contain_text(
        "Only PNG, JPEG, GIF and WebP images can be added."
    )
    expect(editor.locator("img")).to_have_count(0)
    assert sent == []
    assert not WikiImage.objects.exists()
