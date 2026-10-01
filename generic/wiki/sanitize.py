"""The only HTML a wiki page may hold.

Pages are written by trusted people, but what they paste comes from
anywhere - another site, an e-mail, a document - and a page is shown to
everyone. So the HTML is cleaned when it is saved, and again when it is
shown, against an allowlist of what the editor itself produces: no
script, no style, no event handler, no ``javascript:`` link, no inline
image data.
"""

from __future__ import annotations

import nh3
from django.utils.safestring import SafeString, mark_safe

TAGS = frozenset(
    {
        "a",
        "b",
        "blockquote",
        "br",
        "code",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "hr",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "s",
        "span",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    }
)

ATTRIBUTES = {
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "title", "width", "height"},
    "ol": {"start"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}

#: The editor's alignment and indentation classes, and nothing else:
#: an arbitrary class could borrow the application's own styles.
_EDITOR_CLASSES = {
    "ql-align-center",
    "ql-align-right",
    "ql-align-justify",
    *(f"ql-indent-{level}" for level in range(1, 9)),
}

CLASSES = {
    **{
        tag: _EDITOR_CLASSES
        for tag in ("h1", "h2", "h3", "h4", "li", "blockquote")
    },
    # A file attached from the editor is a paragraph of its own, holding
    # the link to it: ``<p class="wiki-file"><a href=...>``.
    "p": _EDITOR_CLASSES | {"wiki-file"},
    "pre": {"ql-syntax"},
}

#: Links and images point at the web, a mailbox or a phone; relative
#: URLs - other wiki pages - are always allowed.
URL_SCHEMES = frozenset({"http", "https", "mailto", "tel"})


def clean_html(html: str | None) -> str:
    """``html``, with everything outside the allowlist removed."""
    if not html:
        return ""

    return nh3.clean(
        html,
        tags=set(TAGS),
        attributes={tag: set(names) for tag, names in ATTRIBUTES.items()},
        allowed_classes={tag: set(names) for tag, names in CLASSES.items()},
        url_schemes=set(URL_SCHEMES),
        link_rel="noopener noreferrer",
        strip_comments=True,
    )


def safe_html(html: str | None) -> SafeString:
    """``html`` cleaned, and marked safe for a template to render.

    The one place a page's HTML becomes markup: whatever shows a page
    goes through here, so nothing can mark it safe uncleaned.
    """
    return mark_safe(clean_html(html))  # nosec B308 B703 - cleaned
