"""Compile every ``.po`` of the repository into a ``.mo``.

``django-admin compilemessages`` does this with GNU gettext's ``msgfmt``.
Where that is not installed - a plain Windows checkout, most often -
this writes the same files with the standard library alone::

    python scripts/compile_messages.py            # the whole repository
    python scripts/compile_messages.py generic    # one package
    python scripts/compile_messages.py --check    # fail if a .mo is stale

It understands what the catalogs here use: the header, plain entries,
plural entries, contexts and the usual escapes. Anything else belongs to
``msgfmt``, and this says so rather than guessing.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

#: What ``msgfmt`` writes at the head of a little-endian catalog.
MAGIC = 0x950412DE

ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}


class CatalogError(Exception):
    """A ``.po`` this compiler will not guess at."""


def unquote(line: str, path: Path, number: int) -> str:
    """The text of one quoted ``.po`` line."""
    body = line.strip()

    if not body.startswith('"') or not body.endswith('"') or len(body) < 2:
        raise CatalogError(f"{path}:{number}: expected a quoted string.")

    text = body[1:-1]
    out: list[str] = []
    index = 0

    while index < len(text):
        character = text[index]

        if character == "\\" and index + 1 < len(text):
            following = text[index + 1]

            if following not in ESCAPES:
                raise CatalogError(
                    f"{path}:{number}: unsupported escape '\\{following}'."
                )

            out.append(ESCAPES[following])
            index += 2
            continue

        out.append(character)
        index += 1

    return "".join(out)


def parse(path: Path) -> dict[str, str]:
    """``{key: translation}``, keyed as a ``.mo`` keys entries.

    A plural entry is keyed ``singular\\0plural`` and holds its forms
    joined the same way; a context prefixes the key with ``context\\x04``.
    Both are what ``gettext`` looks up.
    """
    entries: dict[str, str] = {}
    context = ""
    singular = plural = ""
    forms: dict[int, str] = {}
    target: str | None = None
    index = 0
    start = 0
    seen: dict[str, int] = {}

    def flush() -> None:
        if target is None:
            return

        prefix = context + "\x04" if context else ""

        if plural:
            key = prefix + singular + "\0" + plural
            value = "\0".join(forms[form] for form in sorted(forms))
        elif singular or not entries:
            # The empty msgid holds the catalog's own header.
            key, value = prefix + singular, forms.get(0, "")
        else:
            return

        if key in seen:
            # msgfmt refuses this too: "duplicate message definition".
            raise CatalogError(
                f"{path}:{start}: duplicate message definition"
                f" (first defined at line {seen[key]})."
            )

        seen[key] = start
        entries[key] = value

    for number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()

        if not line or line.startswith("#"):
            continue

        if line.startswith("msgctxt"):
            flush()
            start = number
            context = unquote(line[len("msgctxt") :], path, number)
            singular = plural = ""
            forms = {}
            target = "context"
        elif line.startswith("msgid_plural"):
            plural = unquote(line[len("msgid_plural") :], path, number)
            target = "plural"
        elif line.startswith("msgid"):
            if target != "context":
                flush()
                start = number
                context = ""

            singular = unquote(line[len("msgid") :], path, number)
            plural = ""
            forms = {}
            target = "singular"
        elif line.startswith("msgstr["):
            index = int(line[line.index("[") + 1 : line.index("]")])
            forms[index] = unquote(line[line.index("]") + 1 :], path, number)
            target = "form"
        elif line.startswith("msgstr"):
            index = 0
            forms[0] = unquote(line[len("msgstr") :], path, number)
            target = "form"
        elif line.startswith('"'):
            piece = unquote(line, path, number)

            if target == "context":
                context += piece
            elif target == "singular":
                singular += piece
            elif target == "plural":
                plural += piece
            elif target == "form":
                forms[index] = forms.get(index, "") + piece
            else:
                raise CatalogError(f"{path}:{number}: text before any entry.")
        else:
            word = line.split()[0]
            raise CatalogError(f"{path}:{number}: '{word}' is not supported.")

    flush()

    # An entry left untranslated falls back to its source string, which
    # is what an absent key does; keeping it would translate to "".
    return {key: value for key, value in entries.items() if value or key == ""}


def build(entries: dict[str, str]) -> bytes:
    """The catalog as ``msgfmt`` lays it out, keys sorted."""
    keys = sorted(entries, key=lambda key: key.encode("utf-8"))
    encoded = [
        (key.encode("utf-8"), entries[key].encode("utf-8")) for key in keys
    ]
    count = len(encoded)
    keys_table = 7 * 4
    values_table = keys_table + count * 8
    offset = values_table + count * 8

    key_entries = []
    value_entries = []
    payload = bytearray()

    for key, value in encoded:
        key_entries.append((len(key), offset + len(payload)))
        payload += key + b"\0"

    for key, value in encoded:
        value_entries.append((len(value), offset + len(payload)))
        payload += value + b"\0"

    out = bytearray()
    out += struct.pack(
        "<7I",
        MAGIC,
        0,
        count,
        keys_table,
        values_table,
        0,
        offset + len(payload),
    )

    for length, position in key_entries + value_entries:
        out += struct.pack("<2I", length, position)

    return bytes(out + payload)


def compile_catalog(path: Path, check: bool) -> bool:
    """Write ``path`` as a ``.mo``; say whether anything changed."""
    target = path.with_suffix(".mo")
    data = build(parse(path))
    current = target.read_bytes() if target.exists() else b""

    if data == current:
        return False

    if not check:
        target.write_bytes(data)

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots",
        nargs="*",
        default=["."],
        help="directories to look for .po files in (default: everything)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; fail when a .mo is missing or out of date",
    )
    arguments = parser.parse_args()
    stale: list[Path] = []

    for root in arguments.roots:
        for path in sorted(Path(root).rglob("*.po")):
            if ".venv" in path.parts or "site-packages" in path.parts:
                continue

            try:
                changed = compile_catalog(path, arguments.check)
            except CatalogError as error:
                print(f"error: {error}", file=sys.stderr)
                return 2

            if changed:
                stale.append(path)
            elif not arguments.check:
                print(f"{path.with_suffix('.mo')} is up to date")

    if arguments.check and stale:
        for path in stale:
            print(f"out of date: {path.with_suffix('.mo')}", file=sys.stderr)

        return 1

    for path in stale:
        print(f"wrote {path.with_suffix('.mo')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
