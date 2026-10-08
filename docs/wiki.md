# The wiki

`generic.wiki` is a small wiki inside the application - or several:
each wiki has its own pages in its own menu
([Several wikis](#several-wikis)), and downloads as one PDF
([PDF](#pdf)). Pages in a menu,
written with a rich-text editor by the people allowed to, read by
everyone signed in, with a history of every version. A page can be
pinned to the dashboard, which makes the wiki the natural home for
announcements and how-tos.

It is optional, and deliberately modest: no workflow, no comments.
Images and files are uploaded into a page from the editor - its
toolbar, a drop, a paste - and land where the writer puts them
([Images](#images), [Files](#files)); every line, image and file moves
up and down the page ([Ordering a page](#ordering-a-page)).

## Enabling it

The `wiki` extra - nh3, which cleans the pages' HTML, and fpdf2, which
writes a wiki as a PDF - in the brackets
after the framework's wheel in `requirements.txt` (see
[Extras](installation.md#extras)), then:

```python
INSTALLED_APPS = [
    ...,
    "generic",
    "generic.wiki",
]

urlpatterns = [
    ...,
    path("wiki/", include("generic.wiki.urls")),
    path("", site.urls),
]
```

```bash
python manage.py migrate
```

That is all: the sidebar gets a *Wiki* entry, the dashboard shows the
pinned pages, and the command palette finds pages by title and text.
The first wiki already holds a page: the [user guide](#the-user-guide).

## The user guide

What every screen of the framework lets a reader do - find their way,
search, filter a list, save a view, export, act on several rows, open
a record's page, add, change and delete, read the history, follow a
record, write in the wiki, set up their account - written once for
every application built on it, not for one of them. A migration
(`0007_user_guide`) puts it in the first wiki, after the pages a
project writes (position 1000), one page per language of `LANGUAGES`
it is written in - *User guide* (`user-guide`) in English, *Guide
utilisateur* (`guide-utilisateur`) in French; a site in neither gets
the English one. From then on it is a page like any other: edited,
moved, pinned, deleted, in the PDF.

```bash
python manage.py wiki_user_guide                     # put it back, if deleted
python manage.py wiki_user_guide --update            # the framework's latest text
python manage.py wiki_user_guide --wiki handbook --language fr
```

A page already at the guide's address is left alone, unless
`--update`: then it takes the framework's text, and the text it held
goes to its history, to be restored. From code:
`generic.wiki.guide.install_user_guide(wiki=None, languages=None,
update=False)`.

The text is `generic/wiki/guide/<language>.html` - only what the
editor writes, so the cleaning keeps all of it. The same guide as a
Word document, with screenshots of the example, is
[`docs/user-guide/guide-utilisateur.docx`](user-guide/guide-utilisateur.docx),
built from the French text by `scripts/build_user_guide.py`
(`pip install python-docx`; `--language en` for an English one): run
it again after changing the guide.

## Several wikis

A **wiki** (`generic_wiki.Wiki`: `name`, `slug`, `description`,
`position`) is a set of pages with a menu of its own - a team's
handbook, a product's documentation, the runbooks of a site. Every page
belongs to one wiki, and its address is unique within it.

| Address | Shows |
| --- | --- |
| `wiki/` | The wikis, as cards: name, description, page count, *PDF*, *Open*; *New wiki*, *Edit* and *Delete* for those allowed |
| `wiki/<wiki>/` | The wiki's first page, or an invitation to write it |
| `wiki/<wiki>/<page>/` | A page, with its wiki's menu |
| `wiki/<wiki>/export.pdf` | The whole wiki as a PDF, portrait; `?orientation=landscape` turns the paper ([PDF](#pdf)) |

- A reader who sees **one** wiki and may not add one goes from `wiki/`
  straight into it: a site with one wiki reads as before.
- The menu of a page shows its wiki's name, the PDF button and, folded,
  the **other wikis** and *All wikis*.
- **Upgrading**: the migration puts every existing page in a first
  wiki, *Wiki*, at `main` - rename it from the list. An address from
  before, `wiki/<page>/`, leads (`301`) to the page in the first wiki
  holding it, so links in pages, bookmarks and e-mails keep working;
  a wiki whose address is the same takes precedence.
- A page saved without a wiki - from code written before there were
  several - goes to its parent's wiki, or to the first one.
- A page stays in the wiki it was created in; its subpages are in the
  same wiki. Deleting a wiki deletes its pages and their history,
  after a confirmation that counts them.
- `api`, `images` and `files` are the wiki's own routes: no wiki takes
  them (a wiki named "Files" gets `files-wiki`).

### Who sees which wiki

Anyone signed in reads every wiki, unless `GENERIC["WIKI_ACCESS"]`
narrows them: a function `(user, wikis) -> wikis`, or its dotted path,
given the queryset of wikis and returning the part of it the user may
read.

```python
# myproject/wikis.py
def wikis_of_my_teams(user, wikis):
    if user.is_superuser:
        return wikis

    return wikis.filter(team__members=user)  # a field the project adds


GENERIC = {"WIKI_ACCESS": "myproject.wikis.wikis_of_my_teams"}
```

The document manager (`docmanager/documents/wikis.py`) does this with
teams: a `TeamWiki` row makes a wiki one team's, and a wiki of no team
is everyone's.

Everything goes through it (`Wiki.objects.readable_by(user)`): the
list, the pages (a hidden wiki's page answers `404`), the API, the
dashboard's pinned pages, the command palette and the PDF. Writing is
decided by the model permissions below, in the wikis the user may
write in.

### Who writes in which wiki

By default whoever reads a wiki may write in it - with the page
permissions. `GENERIC["WIKI_EDIT_ACCESS"]` narrows that, wiki by wiki:
the same kind of function, given the wikis the user **reads** and
returning those they may **write** in.

```python
# myproject/wikis.py
def wikis_my_teams_write(user, wikis):
    if user.is_superuser:
        return wikis

    return wikis.filter(editors__members=user)  # a field the project adds


GENERIC = {"WIKI_EDIT_ACCESS": "myproject.wikis.wikis_my_teams_write"}
```

In a wiki the user may not write in, the page has no *Edit*,
*Subpage* or *Delete*, and the API refuses with `403` every change to
one of its pages - created (in the wiki, or under one of its pages),
changed, moved, deleted, restored. `Wiki.objects.writable_by(user)`
answers the question anywhere; it is always a part of `readable_by`.
The wikis themselves - created, renamed, deleted - keep answering to
the wiki permissions alone.

The document manager gives each wiki its **editing teams**
(`TeamWiki.editing_teams`): they read and write it, nobody else
writes in it; a wiki with none is written by whoever reads it.

## Who may do what

| Who | May |
| --- | --- |
| Anyone signed in | Read every page, its menu and its history |
| `generic_wiki.add_wikipage` | Create pages and subpages - in the wikis they write in (`WIKI_EDIT_ACCESS`) |
| `generic_wiki.change_wikipage` | Edit a page, move it in the menu, pin it, restore a version |
| `add_wikipage` or `change_wikipage` | Upload an image or a file into a page |
| `generic_wiki.delete_wikipage` | Delete a page |
| `generic_wiki.add_wiki` | Create a wiki |
| `generic_wiki.change_wiki` | Rename a wiki, change its description |
| `generic_wiki.delete_wiki` | Delete a wiki, with its pages |

Superusers hold all of them. For editors who are not superusers, give a
group the three page permissions; the wiki permissions are for whoever
organises the wikis.

## The page

The menu lists the pages as a tree, with a filter; a page stays in
sight while one of its subpages matches. The page shows its text, when
it was last changed and by whom, and - for editors - *Edit*, *Subpage*,
*History* and *Delete*.

*Edit* turns the page into the editor: its title, its parent page, its
position among its siblings, its address, whether it is pinned to the
dashboard, and the text, in [Quill](https://quilljs.com): headings,
bold and italics, lists, quotes, code, links, images - uploaded or
by address - files, and alignment. *Save* sends everything to the API as JSON and reloads the
page as the server draws it; *Cancel* and leaving the page ask first
when something changed.

Under its text, the page lists its **attachments** - the images and
files it shows, in its order, a file with its size - each a link.

**History** lists the earlier versions, newest first, with their author
and size; *Restore* brings one back. Restoring saves the current text
as a version first, so it can be undone like any other change. The last
50 versions of a page are kept.

**Conflicts**: the editor sends the version it started from. If
someone saved the page in between, the save is refused with their name
- rather than silently overwriting their change - and the text stays in
the editor to be copied.

**Deleting** a page deletes its history; its subpages move up a level
rather than disappearing with it.

## The HTML

Pages are written by trusted people, but what they paste comes from
anywhere, and a page is shown to everyone. The HTML is cleaned by
[nh3](https://nh3.readthedocs.io) - on every save, whatever the way in
(the API, the Django admin, a script), and again every time a page is
shown - against an allowlist of what the editor produces:

- tags: paragraphs, headings, emphasis, lists, quotes, code, links,
  images, rules, tables;
- a file block: `<p class="wiki-file"><a href="/wiki/files/7/">plan.pdf</a></p>`;
- no `script`, no `style`, no event handler, no inline style;
- links and images to `http`, `https`, `mailto` and `tel` only, or
  relative - another wiki page, a record of the application; links get
  `rel="noopener noreferrer"`;
- no image data: an image is an address - an uploaded one under the
  wiki (`/wiki/images/<id>/`, relative, so it is kept), or on the
  web - never inlined in the page;
- only the editor's own classes (alignment, indentation, code blocks,
  `wiki-file` on a paragraph), so a page cannot borrow the
  application's styles.

On the page, the content also sits under `x-ignore`: Alpine never reads
anything in it as a directive.

## The API

Under `wiki/api/`, JSON, like every other screen:

| Request | Does |
| --- | --- |
| `GET wikis/` | The wikis: `id`, `name`, `slug`, `description`, `position`, `url`, `pdf_url`, `page_count` |
| `POST wikis/` | A new wiki; the address comes from the name when not given |
| `PATCH wikis/<id>/` | Rename it, describe it, move it among the wikis |
| `DELETE wikis/<id>/` | Delete it, with its pages |
| `GET pages/` | The menu: every page, without its text; `?wiki=<id>` for one wiki's |
| `POST pages/` | A new page in `wiki` (left out: its parent's wiki, or the first); the address comes from the title when not given |
| `GET pages/<id>/` | One page, with its text, its `version` and its `attachments` |
| `PATCH pages/<id>/` | Change it; send `version` to be protected from overwriting |
| `DELETE pages/<id>/` | Delete it; its subpages move up |
| `GET pages/<id>/revisions/` | Its earlier versions |
| `POST pages/<id>/restore/` | Bring one back: `{"revision": <id>}` |

A page carries its `wiki`; naming another one in a `PATCH`, or a
`parent` from another wiki, answers `400`, and so does an address
another page of the wiki has. `attachments` is read from the text,
never written: `[{"kind":
"image" | "file", "id", "name", "size", "url"}]`, in the page's order,
once each, leaving out an upload no longer in the database. A save
against an old version answers `409 Conflict`. The address
`api` is reserved; a page titled "API" gets `api-page`.

## Images

*Insert an image*, in the editor's toolbar, offers **Upload an image**
- a file chooser - beside the image's address. The file is checked in
the browser, then sent to the framework's endpoint, and what comes back
is put in the page as an ordinary image:

| Request | Does |
| --- | --- |
| `POST api/generic/wiki/images/` | Multipart, part `file`: answers `201 {"id", "url"}`, `url` being `/wiki/images/<id>/` wherever the wiki is mounted (built with `reverse`) |
| `GET wiki/images/<id>/` | The image, for any signed-in reader of the wiki |

- **Who**: an upload needs `generic_wiki.add_wikipage` or
  `generic_wiki.change_wikipage`; reading one, being signed in - the
  rule of the pages themselves (signed out, the sign-in page).
- **What**: PNG, JPEG, GIF or WebP only, told by the name's extension
  **and** by the file's first bytes - a `.png` that is really a page is
  refused; never SVG, a document that can hold a script. The image is
  stored under the extension its bytes say (`upload_to=
  "wiki/images/%Y/%m/"`), and served as that type.
- **How big**: up to `GENERIC["FILE_MAX_SIZE"]` (10 MB).
- **Served** `inline`, with its image type, `X-Content-Type-Options:
  nosniff`, `Content-Security-Policy: sandbox` and `Cache-Control:
  private, max-age=86400` - the reader's browser keeps it a day, a
  shared cache never.
- A refused file (its type, its size) is said in a toast, and nothing
  is inserted.

Images can also be dropped on the editor or pasted into it (a
screenshot): they are uploaded the same way and land where they fell
- never inlined in the page as data.

An image is a `generic_wiki.WikiImage` (`file`, `original_name`,
`uploaded_by`, `uploaded_at`), not attached to a page: several pages -
or earlier versions of one - may show it, so nothing deletes it when a
page stops doing so. The files live in `MEDIA_ROOT`, which has to be
set (`generic.W010`) and backed up with the database
([deployment](deployment.md#backups)).

## Files

The paperclip in the editor's toolbar attaches files - a PDF, a
spreadsheet, an archive, several at once - and so does dropping them
on the text or pasting them. Each is uploaded, then put in the page
as a **block of its own** where the cursor (or the drop) was: a file
icon and its name, linking to where readers download it. Dropped with
images, each lands in turn, in the order they were dropped; an image
goes in the text, any other file as a block.

| Request | Does |
| --- | --- |
| `POST api/generic/wiki/files/` | Multipart, part `file`: answers `201 {"id", "url", "name", "size"}`, `url` being `/wiki/files/<id>/` wherever the wiki is mounted |
| `GET wiki/files/<id>/` | The file, downloaded under the name it was sent with, for any signed-in reader of the wiki |

- **Who**: like images - `add_wikipage` or `change_wikipage` to
  upload, being signed in to download.
- **What**: any kind of file, because it is never shown: always served
  as an `attachment`, with `X-Content-Type-Options: nosniff`,
  `Content-Security-Policy: sandbox` and `Cache-Control: private,
  max-age=86400`. An HTML page or an SVG uploaded as a file is a
  download, not a page of the site.
- **How big**: up to `GENERIC["FILE_MAX_SIZE"]`, checked in the browser
  and again by the server; an empty file is refused.
- In the page, the block is `<p class="wiki-file"><a
  href="/wiki/files/7/">plan.pdf</a></p>`, which the cleaning keeps.

A file is a `generic_wiki.WikiFile` (`file`, `original_name`, `size`,
`uploaded_by`, `uploaded_at`, stored under `wiki/files/%Y/%m/`). Like
an image, it is not attached to a page but linked from it, so nothing
deletes it when a page stops linking to it; a page's attachments are
read from its text.

## PDF

*PDF* on a wiki's card, or the PDF button beside its name in the menu,
offers *Portrait* or *Landscape* and downloads the whole wiki as one
A4 PDF, `<wiki>.pdf`, written there and then from the pages as they
stand:

- a **cover** - the wiki's name, its description, its number of pages
  and the date - then a **table of contents**, the PDF's bookmarks
  following the same tree;
- every **page**, from its own page of paper, in the menu's order: a
  page, then its subpages, siblings by position and title; the title's
  size says its depth;
- the text with its headings, emphasis, lists, quotes, code, tables and
  alignment; links stay links, made absolute;
- the **images** uploaded into a page, drawn where the page shows them
  at the size the page shows them, never wider than the text nor taller
  than a page - a larger one is shrunk, its shape kept, and a wide
  screenshot reads better in landscape; an image on the web is named,
  `[Image: ...]`, never downloaded - writing a PDF never makes the
  server call an address a page holds;
- each **file** block as *File: plan.pdf*, and the page's files listed
  by name and size under *Attached files*.

Who may read the wiki may download it; signed out, the sign-in page.
The answer is an `attachment`, `X-Content-Type-Options: nosniff`,
`Cache-Control: private, no-cache`.

It is written by [fpdf2](https://py-pdf.github.io/fpdf2/), pure Python
with Pillow: `pip install` is all it needs, on Windows as on Linux, no
system library. Without it installed, no PDF is offered and
`export.pdf` answers `404`.

**Fonts.** Any character a page holds is drawn with a TrueType font:
the first of DejaVu Sans, Liberation Sans (Linux) or Arial (Windows,
macOS) found where the system keeps it, or those named by
`GENERIC["WIKI_PDF_FONTS"]`:

```python
GENERIC = {
    "WIKI_PDF_FONTS": {
        "regular": BASE_DIR / "fonts/Inter-Regular.ttf",
        "bold": BASE_DIR / "fonts/Inter-Bold.ttf",
        "italic": BASE_DIR / "fonts/Inter-Italic.ttf",
        "bold_italic": BASE_DIR / "fonts/Inter-BoldItalic.ttf",
        "mono": BASE_DIR / "fonts/JetBrainsMono-Regular.ttf",
    },
}
```

With none found, the PDF's own fonts are used: Latin-1 only - French,
Spanish, German are whole; typographic quotes and dashes become plain
ones, and other characters `?`. The Docker image installs DejaVu
(`fonts-dejavu-core`).

## Ordering a page

The editor's **up and down arrows** - or **Alt+Up** and **Alt+Down** -
move the line holding the cursor above the one before it, or below
the one after: a paragraph, a heading, a list item, a line with an
image, a file block. The cursor moves with it, so pressing again keeps
going; Ctrl+Z undoes a move like any other change. Moving a block is
how a writer orders the page's images and files among its text.

## Why Quill

The editor had to be vendored like the other libraries - no build step,
no CDN - and to carry a licence a closed project can ship. Quill 2 is a
single BSD-licensed file with a clean, themeable UI and semantic HTML
output. TinyMCE and CKEditor are both GPL, or commercial, since their
last major versions; Trix is lighter but has a single heading level;
editors built on ProseMirror need a bundler.

## Changing it

- The page is `generic/wiki/page.html`, the list of wikis
  `generic/wiki/index.html`; a project overrides them like any
  template.
- The PDF is written by `generic/wiki/pdf.py`: `render(wiki,
  base_url=...)` returns its bytes, for a script or a scheduled task
  that files it somewhere.
- The pinned pages are drawn by `generic/wiki/includes/pinned.html`, in
  the `dashboard_pinned` block of `generic/site/index.html`.
- The editor's toolbar is `TOOLBAR` in `generic/js/wiki.js`. Adding a
  format there means allowing its HTML in `generic/wiki/sanitize.py`
  too - the server has the last word. The file block is the Quill blot
  `wikiFile`, registered there too.
- Without the framework's endpoints mounted (`generic.urls`), the
  editor offers no upload: images by address only, no paperclip.
