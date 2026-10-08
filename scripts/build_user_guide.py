"""The user guide as a Word document, from the wiki's own text.

The guide the wiki starts with (``generic/wiki/guide/<language>.html``)
is the one source: this script lays it out as a ``.docx`` - a cover, a
table of contents, the screenshots of ``docs/user-guide/images/`` under
the sections they show - so the document and the wiki page never say
two different things. Run it after changing the guide::

    pip install python-docx
    python scripts/build_user_guide.py            # French
    python scripts/build_user_guide.py --language en

Word fills the table of contents when the document is opened (it asks
to update the fields), or with F9.
"""

from __future__ import annotations

import argparse
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE_DIR = ROOT / "generic" / "wiki" / "guide"
IMAGES = ROOT / "docs" / "user-guide" / "images"

TEXTS = {
    "fr": {
        "title": "Guide utilisateur",
        "subtitle": "Les actions usuelles d'une application django-generic",
        "contents": "Sommaire",
        "file": "guide-utilisateur.docx",
        "update": "Clic droit puis « Mettre à jour les champs » "
        "pour afficher le sommaire.",
    },
    "en": {
        "title": "User guide",
        "subtitle": "The everyday actions of a django-generic application",
        "contents": "Contents",
        "file": "user-guide.docx",
        "update": "Right click, then Update Field, to show the contents.",
    },
}

#: Screenshots (of the example, in French) under the heading they
#: illustrate - matched by the start of the French heading - with their
#: caption.
FIGURES = {
    "Le cadre de chaque page": [
        (
            "11-menu-compte",
            "Le cadre : la navigation à gauche, la barre "
            "du haut et le menu du compte ouvert.",
        ),
    ],
    "2. Le tableau de bord": [
        (
            "01-tableau-de-bord",
            "Un tableau de bord : page épinglée, "
            "raccourcis et chiffres clés.",
        ),
    ],
    "3. Retrouver": [
        (
            "10-palette",
            "La recherche (Ctrl+K) : écrans, enregistrements "
            "et pages du wiki.",
        ),
    ],
    "4. Les listes": [
        (
            "02-liste",
            "Une liste : recherche, barre d'outils, ligne de "
            "recherche sous les en-têtes.",
        ),
    ],
    "Filtrer": [
        (
            "03-filtre-editeur-coche",
            "L'éditeur de filtre d'une colonne : "
            "les valeurs à cocher et leur nombre.",
        ),
        (
            "04-filtre-puces",
            "Le filtre en place, en pastille sous la barre " "d'outils.",
        ),
    ],
    "Les vues": [("05-vues", "Le menu Vues.")],
    "Choisir les colonnes": [("06-colonnes", "Le menu Colonnes.")],
    "Exporter": [("07-export", "Le menu Exporter.")],
    "Agir sur plusieurs lignes": [
        (
            "08-selection",
            "Deux lignes sélectionnées et la barre des " "actions.",
        ),
    ],
    "Le menu d'une ligne": [
        ("09-menu-ligne", "Le menu d'une ligne, ouvert d'un clic droit."),
    ],
    "5. La fiche": [
        (
            "12-fiche",
            "La fiche d'un enregistrement : actions, chiffres, " "graphiques.",
        ),
        (
            "13-fiche-onglets",
            "Ses valeurs et les onglets des " "enregistrements liés.",
        ),
    ],
    "Remplir un formulaire": [
        ("15-formulaire", "Un formulaire et ses boutons d'enregistrement."),
    ],
    "Supprimer": [
        (
            "17-suppression",
            "Avant de supprimer : tout ce qui part avec " "l'enregistrement.",
        ),
    ],
    "7. L'historique": [
        (
            "14-historique",
            "L'onglet Historique : chaque modification, " "avant et après.",
        ),
    ],
    "Calendrier": [("18-calendrier", "Une vue calendrier, par mois.")],
    "Arborescence": [("19-arborescence", "Une arborescence dépliée.")],
    "10. Rester informé": [
        ("22-notifications", "Le menu de la cloche des notifications."),
    ],
    "11. Le wiki": [("20-wiki", "Une page du wiki et son menu.")],
    "12. Votre compte": [("21-compte", "Les paramètres du compte.")],
}


class Guide(HTMLParser):
    """The guide's HTML - headings, paragraphs, lists, bold, italics,
    code - as a list of blocks: ``(kind, runs)``, a run being ``(text,
    bold, italic, code)``."""

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[tuple[str, list]] = []
        self.lists: list[list] = []
        self.styles: list[str] = []
        self.runs: list | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("ul", "ol"):
            self.lists.append([tag, 0])
        elif tag in ("p", "h2", "h3", "li"):
            self.runs = []
            self.kind = tag

            if tag == "li":
                # A numbered list counts from 1 again: its numbers are
                # written, not Word's, which would carry on from the
                # list before.
                self.lists[-1][1] += 1
                self.kind, number = self.lists[-1]

                if self.kind == "ol":
                    self.runs.append((f"{number}. ", True, False, False))
        elif tag in ("strong", "b", "em", "i", "code"):
            self.styles.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("ul", "ol"):
            self.lists.pop()
        elif tag in ("p", "h2", "h3", "li") and self.runs is not None:
            self.blocks.append((self.kind, self.runs))
            self.runs = None
        elif tag in ("strong", "b", "em", "i", "code") and self.styles:
            self.styles.pop()

    def handle_data(self, data: str) -> None:
        if self.runs is None or not data.strip("\n"):
            return

        self.runs.append(
            (
                data.replace("\n", " "),
                bool({"strong", "b"} & set(self.styles)),
                bool({"em", "i"} & set(self.styles)),
                "code" in self.styles,
            )
        )


def add_field(paragraph, instruction: str) -> None:
    """A Word field - the table of contents - filled when opened."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = paragraph.add_run()

    for kind, text in (("begin", None), (None, instruction), ("end", None)):
        if kind:
            element = OxmlElement("w:fldChar")
            element.set(qn("w:fldCharType"), kind)
        else:
            element = OxmlElement("w:instrText")
            element.set(qn("xml:space"), "preserve")
            element.text = text

        run._r.append(element)


def build(language: str, output: Path) -> Path:
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    texts = TEXTS[language]
    accent = RGBColor(0x25, 0x63, 0xEB)
    parser = Guide()
    parser.feed((GUIDE_DIR / f"{language}.html").read_text("utf-8"))

    document = Document()
    section = document.sections[0]
    section.page_height, section.page_width = Cm(29.7), Cm(21)

    for side in ("left_margin", "right_margin"):
        setattr(section, side, Cm(2.2))

    styles = document.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(10.5)
    styles["Normal"].paragraph_format.space_after = Pt(6)
    styles["Normal"].paragraph_format.line_spacing = 1.15

    for name, size in (("Heading 1", 18), ("Heading 2", 13)):
        style = styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = accent if name == "Heading 1" else None
        style.paragraph_format.space_before = Pt(18 if size > 13 else 12)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.keep_with_next = True

    # The cover.
    for _blank in range(8):
        document.add_paragraph()

    title = document.add_paragraph()
    run = title.add_run(texts["title"])
    run.font.size, run.font.bold, run.font.color.rgb = Pt(32), True, accent
    subtitle = document.add_paragraph()
    run = subtitle.add_run(texts["subtitle"])
    run.font.size = Pt(14)
    run.font.color.rgb = RGBColor(0x55, 0x5B, 0x66)
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # The contents, filled by Word.
    document.add_paragraph(texts["contents"], style="Heading 1")
    add_field(document.add_paragraph(), 'TOC \\o "1-2" \\h \\z \\u')
    hint = document.add_paragraph()
    hint_run = hint.add_run(texts["update"])
    hint_run.font.size, hint_run.font.italic = Pt(9), True
    document.add_section(WD_SECTION.NEW_PAGE)

    # Page numbers at the foot of the guide itself.
    footer = document.sections[-1].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_field(footer, "PAGE")

    width = Cm(15)

    for kind, runs in parser.blocks:
        text = "".join(run[0] for run in runs).strip()

        if kind == "h2":
            paragraph = document.add_paragraph(text, style="Heading 1")
        elif kind == "h3":
            paragraph = document.add_paragraph(text, style="Heading 2")
        else:
            style = "List Bullet" if kind == "ul" else None
            paragraph = document.add_paragraph(style=style)

            if kind == "ol":
                paragraph.paragraph_format.left_indent = Cm(0.95)
                paragraph.paragraph_format.first_line_indent = Cm(-0.5)

            for content, bold, italic, code in runs:
                run = paragraph.add_run(content)
                run.bold, run.italic = bold, italic

                if code:
                    run.font.name = "Consolas"
                    run.font.size = Pt(9.5)
                    run._r.get_or_add_rPr().append(shading("F1F3F7"))

        if kind in ("h2", "h3") and language == "fr":
            for start, figures in FIGURES.items():
                if text.startswith(start):
                    for name, caption in figures:
                        picture = document.add_paragraph()
                        picture.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        picture.paragraph_format.keep_with_next = True
                        picture.add_run().add_picture(
                            str(IMAGES / f"{name}.png"), width=width
                        )
                        legend = document.add_paragraph()
                        legend.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        legend_run = legend.add_run(caption)
                        legend_run.italic = True
                        legend_run.font.size = Pt(9)
                        legend_run.font.color.rgb = RGBColor(0x55, 0x5B, 0x66)

    # Word asks to update the fields - the contents - on opening.
    settings = document.settings.element
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    settings.append(update)

    document.core_properties.title = texts["title"]
    document.core_properties.subject = texts["subtitle"]
    document.save(output)

    return output


def shading(fill: str):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    element = OxmlElement("w:shd")
    element.set(qn("w:val"), "clear")
    element.set(qn("w:color"), "auto")
    element.set(qn("w:fill"), fill)

    return element


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--language", choices=sorted(TEXTS), default="fr")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    output = args.output or (
        ROOT / "docs" / "user-guide" / TEXTS[args.language]["file"]
    )

    try:
        import docx  # noqa: F401
    except ImportError:
        print("python-docx is needed: pip install python-docx")
        return 1

    print(build(args.language, output))

    return 0


if __name__ == "__main__":
    sys.exit(main())
