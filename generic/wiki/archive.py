"""A wiki as one file, and back: ``export.zip``.

The archive is a zip any site running the wiki can import - another
project, the same one after a reinstall, a test server:

``wiki.json``
    What the wiki is (``format``, ``version``), its name, address and
    description, and its pages: title, address, parent, position,
    pinned or not, dates and text.
``images/<n>.<ext>``, ``files/<n>-<name>``
    The images the pages show and the files they link to, each once.

In the pages' text an upload's address - ``/wiki/images/7/`` - is
written as its place in the archive - ``images/1.png`` - so the text
names nothing of the site it came from; an import writes the address
each upload gets there instead. The history of the pages stays behind:
an archive is the wiki as it stands.

Importing makes a new wiki, never merges into one: nothing that exists
changes. Everything read from an archive is checked as if a person had
typed it - pages cleaned by ``WikiPage.save``, images told by their
bytes, sizes held to ``WIKI_ARCHIVE_MAX_SIZE`` and ``FILE_MAX_SIZE`` -
and a member is only ever read by the name the manifest gives it, never
unpacked to disk.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import IO, Any, Callable

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import get_valid_filename, slugify
from django.utils.translation import gettext

import generic
from generic.conf import generic_settings
from generic.wiki.models import (
    RESERVED_WIKI_SLUGS,
    Wiki,
    WikiFile,
    WikiImage,
    WikiPage,
    _address_pattern,
)

#: What ``wiki.json`` says it is, and the version of its layout: an
#: archive of a later version is refused rather than half read.
FORMAT = "django-generic.wiki"
VERSION = 1

MANIFEST = "wiki.json"

#: More members than any wiki holds: what is beyond is not a wiki.
MAX_MEMBERS = 10_000

#: The manifest is text; this is far more than any wiki writes.
MAX_MANIFEST_SIZE = 20 * 1024 * 1024

#: An upload's place in the archive, as the pages' text names it.
ARCHIVE_PATH = re.compile(
    r"""(?P<attr>src|href)=(?P<quote>["'])"""
    r"""(?P<path>(?:images|files)/[^"'/]+)(?P=quote)"""
)


#: A link from a page to another page of the archive, as the text
#: names it: ``pages/<id>/``, maybe followed by ``#part`` or ``?query``.
ARCHIVE_PAGE = re.compile(
    r"""href=(?P<quote>["'])pages/(?P<page>[^"'/]+)/"""
    r"""(?P<rest>[#?][^"']*)?(?P=quote)"""
)


class ArchiveError(ValueError):
    """The file is not a wiki archive this site can import; the message
    says why, to the person who sent it."""


@dataclass
class ImportResult:
    wiki: Wiki
    pages: int = 0
    images: int = 0
    files: int = 0
    #: Members left out - an image that is not one, a file too large -
    #: by their name in the archive.
    skipped: list[str] = field(default_factory=list)


def archive_name(wiki: Wiki) -> str:
    """What the downloaded archive is called."""
    return f"{wiki.slug}.zip"


# --- Export ------------------------------------------------------------


def _upload_pattern() -> re.Pattern:
    addresses = "|".join(_address_pattern(kind) for kind in ("image", "file"))

    return re.compile(
        rf"""(?P<attr>src|href)=(?P<quote>["'])(?:{addresses})(?P=quote)"""
    )


def _page_link_pattern(wiki: Wiki) -> re.Pattern:
    """A link to a page of ``wiki``, as the editor writes it: its
    address on this site, ``/wiki/<wiki>/<page>/``, maybe absolute."""
    sample = reverse(
        "generic_wiki:page", kwargs={"wiki": wiki.slug, "slug": "__page__"}
    )
    address = re.escape(sample).replace("__page__", r"(?P<slug>[^/\"'#?]+)")

    return re.compile(
        rf"""href=(?P<quote>["'])(?:https?://[^/"']+)?{address}"""
        rf"""(?P<rest>[#?][^"']*)?(?P=quote)"""
    )


def _member_name(kind: str, index: int, upload: Any) -> str:
    """Where an upload goes in the archive: numbered, so that two
    uploads never meet, and named, so that the unpacked archive reads."""
    if kind == "image":
        extension = PurePath(upload.file.name).suffix.lower()

        return f"images/{index}{extension}"

    name = get_valid_filename(upload.original_name or "") or "file"

    return f"files/{index}-{name[:120]}"


def write_archive(wiki: Wiki, output: IO[bytes]) -> dict[str, Any]:
    """Write ``wiki`` as an archive to ``output``; returns the manifest.

    Only the uploads the pages show and still stored go in; a link to
    one no longer stored is left as it was.
    """
    from generic.sites.files import is_stored

    pages = list(wiki.pages.order_by("position", "title", "pk"))
    pattern = _upload_pattern()
    wanted: dict[str, list[int]] = {"image": [], "file": []}

    for page in pages:
        for match in pattern.finditer(page.content or ""):
            kind = "image" if match.group("image") else "file"
            pk = int(match.group(kind))

            if pk not in wanted[kind]:
                wanted[kind].append(pk)

    stored = {
        "image": WikiImage.objects.in_bulk(wanted["image"]),
        "file": WikiFile.objects.in_bulk(wanted["file"]),
    }
    members: dict[tuple[str, int], str] = {}
    entries: dict[str, list[dict[str, Any]]] = {"images": [], "files": []}

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for kind in ("image", "file"):
            for pk in wanted[kind]:
                upload = stored[kind].get(pk)

                if upload is None or not is_stored(upload.file):
                    continue

                name = _member_name(kind, len(members) + 1, upload)

                with upload.file.open("rb") as source:
                    archive.writestr(name, source.read())

                members[(kind, pk)] = name
                entry = {"path": name, "name": str(upload)}

                if kind == "file":
                    entry["size"] = upload.size

                entries[f"{kind}s"].append(entry)

        def portable(match: re.Match) -> str:
            kind = "image" if match.group("image") else "file"
            name = members.get((kind, int(match.group(kind))))

            if name is None:
                return match.group(0)

            quote = match.group("quote")

            return f"{match.group('attr')}={quote}{name}{quote}"

        numbers = {page.pk: index for index, page in enumerate(pages, 1)}
        by_slug = {page.slug: numbers[page.pk] for page in pages}
        links = _page_link_pattern(wiki)

        def portable_link(match: re.Match) -> str:
            number = by_slug.get(match.group("slug"))

            if number is None:
                return match.group(0)

            quote = match.group("quote")
            rest = match.group("rest") or ""

            return f"href={quote}pages/{number}/{rest}{quote}"

        def portable_text(html: str) -> str:
            return links.sub(portable_link, pattern.sub(portable, html))

        manifest = {
            "format": FORMAT,
            "version": VERSION,
            "generator": f"django-generic {generic.__version__}",
            "exported_at": timezone.now().isoformat(),
            "wiki": {
                "name": wiki.name,
                "slug": wiki.slug,
                "description": wiki.description,
            },
            "pages": [
                {
                    "id": numbers[page.pk],
                    # A parent in another wiki - only data written by
                    # hand - is no parent here.
                    "parent": (
                        numbers.get(page.parent_id)
                        if page.parent_id is not None
                        else None
                    ),
                    "title": page.title,
                    "slug": page.slug,
                    "position": page.position,
                    "show_on_dashboard": page.show_on_dashboard,
                    "created_at": page.created_at.isoformat(),
                    "updated_at": page.updated_at.isoformat(),
                    "content": portable_text(page.content or ""),
                }
                for page in pages
            ],
            **entries,
        }
        archive.writestr(
            MANIFEST,
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )

    return manifest


# --- Import ------------------------------------------------------------


def _text(value: Any, limit: int, what: str) -> str:
    if value is None:
        return ""

    if not isinstance(value, str):
        raise ArchiveError(gettext("The archive's wiki.json is invalid."))

    return value[:limit]


def _number(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0

    return value


def read_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    """The archive's manifest, checked to be one this site reads."""
    infos = archive.infolist()

    if len(infos) > MAX_MEMBERS:
        raise ArchiveError(gettext("The archive holds too many files."))

    limit = generic_settings.WIKI_ARCHIVE_MAX_SIZE

    if limit and sum(info.file_size for info in infos) > limit:
        raise ArchiveError(gettext("The archive is too large once unpacked."))

    try:
        info = archive.getinfo(MANIFEST)
    except KeyError:
        raise ArchiveError(
            gettext("This is not a wiki archive: it has no wiki.json.")
        ) from None

    if info.file_size > MAX_MANIFEST_SIZE:
        raise ArchiveError(gettext("The archive's wiki.json is too large."))

    try:
        manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ArchiveError(
            gettext("The archive's wiki.json cannot be read.")
        ) from None

    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise ArchiveError(gettext("This is not a wiki archive."))

    version = manifest.get("version")

    if not isinstance(version, int) or version < 1 or version > VERSION:
        raise ArchiveError(
            gettext(
                "This archive was written by a later version of the "
                "wiki: update this site to import it."
            )
        )

    if not isinstance(manifest.get("wiki"), dict) or not isinstance(
        manifest.get("pages"), list
    ):
        raise ArchiveError(gettext("The archive's wiki.json is incomplete."))

    return manifest


def _read_member(
    archive: zipfile.ZipFile, path: str, limit: int
) -> bytes | None:
    """A member's bytes, or ``None`` when it is missing or larger than
    ``limit`` - counted as it is read, not as the archive claims."""
    try:
        with archive.open(path) as member:
            data = member.read(limit + 1 if limit else -1)
    except (KeyError, zipfile.BadZipFile, OSError):
        return None

    if limit and len(data) > limit:
        return None

    return data


def _uploads(
    archive: zipfile.ZipFile,
    manifest: dict[str, Any],
    user: Any,
    result: ImportResult,
    saved: list[Any],
) -> dict[str, str]:
    """Store the archive's images and files; returns, for each place in
    the archive, the address it now has."""
    from generic.wiki.api import sniff_image

    limit = generic_settings.FILE_MAX_SIZE
    addresses: dict[str, str] = {}

    for key, prefix in (("images", "images/"), ("files", "files/")):
        entries = manifest.get(key) or []

        if not isinstance(entries, list):
            raise ArchiveError(gettext("The archive's wiki.json is invalid."))

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            path = entry.get("path")

            if (
                not isinstance(path, str)
                or not path.startswith(prefix)
                or "/" in path[len(prefix) :]
                or path in addresses
            ):
                continue

            data = _read_member(archive, path, limit)

            if not data:
                result.skipped.append(path)
                continue

            name = (
                PurePath(
                    _text(entry.get("name"), 255, "name").replace("\\", "/")
                ).name
                or PurePath(path).name
            )

            if key == "images":
                stored = sniff_image(data[:16])

                if stored is None:
                    result.skipped.append(path)
                    continue

                upload: Any = WikiImage(original_name=name, uploaded_by=user)
                stem = PurePath(name).stem or "image"
                upload.file.save(
                    f"{stem}.{stored}", ContentFile(data), save=False
                )
                result.images += 1
            else:
                upload = WikiFile(
                    original_name=name, size=len(data), uploaded_by=user
                )
                upload.file.save(name or "file", ContentFile(data), save=False)
                result.files += 1

            saved.append(upload.file)
            upload.save()
            addresses[path] = upload.get_absolute_url()

    return addresses


def _wiki_slug(manifest_slug: Any, name: str) -> str:
    from generic.wiki.serializers import unique_wiki_slug

    slug = slugify(manifest_slug or "", allow_unicode=True)[:120]

    if (
        slug
        and slug not in RESERVED_WIKI_SLUGS
        and not Wiki.objects.filter(slug=slug).exists()
    ):
        return slug

    return unique_wiki_slug(name)


def _pages(
    wiki: Wiki,
    manifest: dict[str, Any],
    addresses: dict[str, str],
    user: Any,
) -> int:
    from generic.wiki.serializers import RESERVED_SLUGS

    def local(match: re.Match) -> str:
        address = addresses.get(match.group("path"))

        if address is None:
            return match.group(0)

        quote = match.group("quote")

        return f"{match.group('attr')}={quote}{address}{quote}"

    entries: list[tuple[Any, dict[str, Any], str, str]] = []
    keys: set[str] = set()
    slugs: set[str] = set()

    for entry in manifest["pages"]:
        if not isinstance(entry, dict):
            raise ArchiveError(gettext("The archive's wiki.json is invalid."))

        key = entry.get("id")

        if not isinstance(key, (int, str)) or str(key) in keys:
            raise ArchiveError(gettext("The archive's wiki.json is invalid."))

        keys.add(str(key))

        title = _text(entry.get("title"), 200, "title").strip()
        title = title or gettext("Untitled")
        base = (
            slugify(_text(entry.get("slug"), 120, "slug"), allow_unicode=True)
            or slugify(title, allow_unicode=True)[:100]
            or "page"
        )

        if base in RESERVED_SLUGS:
            base = f"{base}-page"

        slug = base
        index = 2

        while slug in slugs:
            slug = f"{base[:110]}-{index}"
            index += 1

        slugs.add(slug)
        entries.append((key, entry, title, slug))

    # Where each page of the archive now is: what its links to one
    # another become.
    targets = {
        str(key): reverse(
            "generic_wiki:page", kwargs={"wiki": wiki.slug, "slug": slug}
        )
        for key, _entry, _title, slug in entries
    }

    def link(match: re.Match) -> str:
        address = targets.get(match.group("page"))

        if address is None:
            return match.group(0)

        quote = match.group("quote")

        return f"href={quote}{address}{match.group('rest') or ''}{quote}"

    created: dict[Any, WikiPage] = {}
    parents: dict[Any, Any] = {}

    for key, entry, title, slug in entries:
        written = (
            parse_datetime(_text(entry.get("created_at"), 64, "date"))
            or timezone.now()
        )

        if timezone.is_naive(written):
            written = timezone.make_aware(written)

        content = _text(entry.get("content"), 10_000_000, "content")
        page = WikiPage(
            wiki=wiki,
            title=title,
            slug=slug,
            position=_number(entry.get("position")),
            show_on_dashboard=entry.get("show_on_dashboard") is True,
            content=ARCHIVE_PAGE.sub(link, ARCHIVE_PATH.sub(local, content)),
            created_at=written,
            created_by=user,
            updated_by=user,
        )
        # Cleaned on the way in, like a page typed in the editor.
        page.save()
        created[key] = page
        parents[key] = entry.get("parent")

    def parent_of(key: Any) -> Any:
        parent = parents[key]

        return parent if isinstance(parent, (int, str)) else None

    for key, page in created.items():
        parent = parent_of(key)

        if parent not in created:
            continue

        # A page in a loop of the archive's pages goes to the top, and
        # so does every other page of the loop.
        node, seen = parent, {key}

        while node in created and node not in seen:
            seen.add(node)
            node = parent_of(node)

        if node != key:
            WikiPage.objects.filter(pk=page.pk).update(parent=created[parent])

    return len(created)


def import_archive(
    source: Any,
    *,
    user: Any = None,
    name: str = "",
    check: Callable[[Wiki], None] | None = None,
) -> ImportResult:
    """Make a new wiki from the archive ``source`` - a path or a file
    open in binary mode - and return what was made.

    ``name`` names the wiki; left empty, the archive's name. ``check``,
    given the wiki once made, may raise to undo it all. Raises
    :class:`ArchiveError`, having stored nothing, when the archive
    cannot be imported.
    """
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError):
        raise ArchiveError(
            gettext("This is not a wiki archive: it is not a zip file.")
        ) from None

    saved: list[Any] = []

    with archive:
        manifest = read_manifest(archive)
        about = manifest["wiki"]
        wiki_name = (
            (name or "").strip()[:200]
            or _text(about.get("name"), 200, "name").strip()
            or gettext("Imported wiki")
        )

        try:
            with transaction.atomic():
                last = Wiki.objects.aggregate(last=Max("position"))["last"]
                wiki = Wiki.objects.create(
                    name=wiki_name,
                    slug=_wiki_slug(about.get("slug"), wiki_name),
                    description=_text(
                        about.get("description"), 100_000, "description"
                    ),
                    position=0 if last is None else last + 1,
                )
                result = ImportResult(wiki=wiki)
                addresses = _uploads(archive, manifest, user, result, saved)
                result.pages = _pages(wiki, manifest, addresses, user)

                if check is not None:
                    check(wiki)
        except BaseException:
            # The rows are rolled back; the files they named go too.
            for stored in saved:
                try:
                    stored.storage.delete(stored.name)
                except Exception:  # noqa: BLE001 - any storage
                    pass

            raise

    return result
