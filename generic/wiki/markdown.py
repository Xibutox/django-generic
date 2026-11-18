"""A page as Markdown, and Markdown as a page.

    to_markdown(html, title)   # a page's text, for ``export.md``
    from_markdown(text)        # (title, html), for ``pages/import/``

Both cover what the editor writes: headings, paragraphs, bold, italic,
struck and inline code, links and images, lists - nested, numbered or
not -, quotes, code blocks, rules and tables. Nothing else is promised:
Markdown has many dialects, and a page imported is the start of a page,
cleaned like any other (``sanitize.clean_html``) - never raw HTML from
the file.
"""

from __future__ import annotations

import html as htmllib
import re
from html.parser import HTMLParser
from typing import Any

# -- HTML -> Markdown ---------------------------------------------------

_INLINE = {
    "strong": "**",
    "b": "**",
    "em": "*",
    "i": "*",
    "s": "~~",
    "del": "~~",
    "strike": "~~",
}


class _Markdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.line: list[str] = []
        self.lists: list[list[Any]] = []
        self.quote = 0
        self.pre = False
        self.code: list[str] = []
        self.links: list[str] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.table: list[list[str]] = []
        self.heads = 0

    # Lines -------------------------------------------------------------

    def prefix(self) -> str:
        return "> " * self.quote

    def flush(self, blank: bool = True) -> None:
        text = "".join(self.line).strip()
        self.line = []

        if text:
            indent = "   " * max(len(self.lists) - 1, 0)
            self.out.append(self.prefix() + indent + text)

            if blank:
                self.out.append(self.prefix().rstrip())

    def write(self, text: str) -> None:
        if self.cell is not None:
            self.cell.append(text)
        else:
            self.line.append(text)

    # Tags --------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        values = dict(attrs)

        if self.pre:
            return

        if re.fullmatch(r"h[1-6]", tag):
            self.flush()
            self.write("#" * int(tag[1]) + " ")
        elif tag in ("p", "div"):
            if not self.lists:
                self.flush()
        elif tag == "br":
            self.write("  \n" + self.prefix())
        elif tag == "hr":
            self.flush()
            self.out += ["---", ""]
        elif tag in _INLINE:
            self.write(_INLINE[tag])
        elif tag == "code":
            self.write("`")
        elif tag == "pre":
            self.flush()
            self.pre = True
            self.code = []
        elif tag == "a":
            self.links.append(values.get("href") or "")
            self.write("[")
        elif tag == "img":
            alt = (values.get("alt") or "").replace("]", "")
            self.write(f"![{alt}]({values.get('src') or ''})")
        elif tag in ("ul", "ol"):
            self.flush(blank=not self.lists)
            self.lists.append([tag, 0])
        elif tag == "li":
            self.flush(blank=False)
            kind: list[Any] = self.lists[-1] if self.lists else ["ul", 0]
            kind[1] += 1
            self.write(f"{kind[1]}. " if kind[0] == "ol" else "- ")
        elif tag == "blockquote":
            self.flush()
            self.quote += 1
        elif tag == "table":
            self.flush()
            self.table = []
            self.heads = 0
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []

            if tag == "th" and self.table == []:
                self.heads += 1

    def handle_endtag(self, tag: str) -> None:
        if self.pre and tag != "pre":
            return

        if re.fullmatch(r"h[1-6]", tag) or tag in ("p", "div"):
            if not self.lists:
                self.flush()
        elif tag in _INLINE:
            self.write(_INLINE[tag])
        elif tag == "code":
            self.write("`")
        elif tag == "pre":
            self.pre = False
            code = "".join(self.code).strip("\n").split("\n")
            self.out += [
                self.prefix() + "```",
                *(self.prefix() + line for line in code),
                self.prefix() + "```",
                self.prefix().rstrip(),
            ]
        elif tag == "a":
            href = self.links.pop() if self.links else ""
            self.write(f"]({href})")
        elif tag in ("ul", "ol"):
            self.flush(blank=False)

            if self.lists:
                self.lists.pop()

            if not self.lists:
                self.out.append(self.prefix().rstrip())
        elif tag == "li":
            self.flush(blank=False)
        elif tag == "blockquote":
            self.flush()
            self.quote = max(self.quote - 1, 0)

            if self.out and self.out[-1].strip() == ">":
                self.out[-1] = self.prefix().rstrip()
        elif tag in ("td", "th") and self.cell is not None:
            text = " ".join("".join(self.cell).split()).replace("|", "\\|")
            self.cell = None

            if self.row is not None:
                self.row.append(text)
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table":
            self.write_table()

    def handle_data(self, data: str) -> None:
        if self.pre:
            self.code.append(data)
            return

        # What Markdown would read as HTML stays text.
        data = data.replace("<", "&lt;")
        text = re.sub(r"\s+", " ", data)

        if not "".join(self.line).strip():
            text = text.lstrip()

        self.write(text)

    def write_table(self) -> None:
        rows = [row for row in self.table if row]
        self.table = []

        if not rows:
            return

        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        self.out.append("| " + " | ".join(rows[0]) + " |")
        self.out.append("|" + " --- |" * width)

        for row in rows[1:]:
            self.out.append("| " + " | ".join(row) + " |")

        self.out.append("")

    def close(self) -> None:
        super().close()
        self.flush()


def to_markdown(html: str | None, title: str = "") -> str:
    """A page's HTML as Markdown, its title first as a heading."""
    parser = _Markdown()
    parser.feed(html or "")
    parser.close()
    lines = parser.out

    if title:
        lines = [f"# {title}", "", *lines]

    text = "\n".join(lines)

    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


# -- Markdown -> HTML ---------------------------------------------------

_FENCE = re.compile(r"^(```|~~~)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^(\*\s*){3,}$|^(-\s*){3,}$|^(_\s*){3,}$")
_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TABLE_LINE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def inline(text: str) -> str:
    """One line's Markdown as HTML: escaped first, then marked up."""
    codes: list[str] = []

    def keep(match: re.Match) -> str:
        codes.append(f"<code>{htmllib.escape(match.group(1))}</code>")

        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep, text)
    text = htmllib.escape(text, quote=True)
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)",
        r'<img src="\2" alt="\1">',
        text,
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)",
        r'<a href="\2">\1</a>',
        text,
    )
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", _strong, text)
    text = re.sub(
        r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", text
    )
    text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    text = re.sub(r" {2,}$", "<br>", text)

    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def _strong(match: re.Match) -> str:
    return f"<strong>{match.group(1) or match.group(2)}</strong>"


def _cells(line: str) -> list[str]:
    line = line.strip()

    if line.startswith("|"):
        line = line[1:]

    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]

    return [
        cell.strip().replace("\\|", "|")
        for cell in re.split(r"(?<!\\)\|", line)
    ]


def _list(lines: list[str]) -> str:
    """Consecutive list lines, nested by their indent."""
    out: list[str] = []
    stack: list[tuple[int, str]] = []

    for line in lines:
        match = _ITEM.match(line)

        if match is None:
            # A line continuing the item above.
            if out and out[-1].endswith("</li>"):
                out[-1] = (
                    out[-1][: -len("</li>")]
                    + " "
                    + inline(line.strip())
                    + "</li>"
                )

            continue

        indent = len(match.group(1).replace("\t", "    "))
        tag = "ol" if match.group(2)[0].isdigit() else "ul"

        while stack and indent < stack[-1][0]:
            out.append(f"</{stack.pop()[1]}>")

            if out and stack:
                out.append("</li>")

        if not stack or indent > stack[-1][0]:
            if stack and out and out[-1].endswith("</li>"):
                out[-1] = out[-1][: -len("</li>")]

            stack.append((indent, tag))
            out.append(f"<{tag}>")

        out.append(f"<li>{inline(match.group(3))}</li>")

    while stack:
        out.append(f"</{stack.pop()[1]}>")

        if stack:
            out.append("</li>")

    return "".join(out)


def blocks(lines: list[str]) -> list[str]:
    out: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        fence = _FENCE.match(stripped)

        if fence:
            code = []
            index += 1

            while index < len(lines) and not lines[index].strip().startswith(
                fence.group(1)
            ):
                code.append(lines[index])
                index += 1

            out.append("<pre>" + htmllib.escape("\n".join(code)) + "</pre>")
            index += 1
            continue

        heading = _HEADING.match(stripped)

        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        if _RULE.match(stripped):
            out.append("<hr>")
            index += 1
            continue

        if stripped.startswith(">"):
            quoted = []

            while index < len(lines) and lines[index].strip().startswith(">"):
                quoted.append(re.sub(r"^\s*>\s?", "", lines[index]))
                index += 1

            out.append(
                "<blockquote>" + "".join(blocks(quoted)) + "</blockquote>"
            )
            continue

        if _ITEM.match(line):
            items = []

            while index < len(lines) and lines[index].strip():
                if not _ITEM.match(lines[index]) and not lines[
                    index
                ].startswith((" ", "\t")):
                    break

                items.append(lines[index])
                index += 1

            out.append(_list(items))
            continue

        if (
            "|" in stripped
            and index + 1 < len(lines)
            and _TABLE_LINE.match(lines[index + 1])
        ):
            head = _cells(stripped)
            rows = []
            index += 2

            while index < len(lines) and "|" in lines[index]:
                rows.append(_cells(lines[index]))
                index += 1

            html = "<table><thead><tr>"
            html += "".join(f"<th>{inline(cell)}</th>" for cell in head)
            html += "</tr></thead><tbody>"

            for row in rows:
                html += (
                    "<tr>"
                    + "".join(f"<td>{inline(cell)}</td>" for cell in row)
                    + "</tr>"
                )

            out.append(html + "</tbody></table>")
            continue

        paragraph: list[str] = []

        while index < len(lines) and lines[index].strip():
            current = lines[index].strip()

            if paragraph and (
                _HEADING.match(current)
                or _FENCE.match(current)
                or current.startswith(">")
                or _ITEM.match(lines[index])
            ):
                break

            paragraph.append(inline(lines[index].rstrip("\n")).strip())
            index += 1

        out.append(
            "<p>" + " ".join(paragraph).replace("<br> ", "<br>") + "</p>"
        )

    return out


def from_markdown(text: str) -> tuple[str, str]:
    """``(title, html)`` from Markdown: a first ``# heading`` is the
    title, taken out of the text; no title otherwise."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title = ""

    for number, line in enumerate(lines):
        if not line.strip():
            continue

        heading = _HEADING.match(line.strip())

        if heading and len(heading.group(1)) == 1:
            title = heading.group(2).strip()
            lines = lines[number + 1 :]

        break

    return title, "".join(blocks(lines))
