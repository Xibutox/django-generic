# The wiki

`generic.wiki` is a small wiki inside the application - or several:
each wiki has its own pages in its own menu
([Several wikis](#several-wikis)), downloads as one PDF
([PDF](#pdf)), and moves to another site as one zip
([Export and import](#export-and-import)). Pages in a menu,
written with a rich-text editor by the people allowed to, read by
everyone signed in, with a history of every version. A page can be
pinned to the dashboard, which makes the wiki the natural home for
announcements and how-tos.

Each wiki says who reads it and who writes in it - its access, its
owner, its members ([Access, owner and members](#access-owner-and-members)).
What is deleted waits in a trash ([The trash](#the-trash)), the history
says what each version changed, and the editor keeps what is being
written ([Drafts and conflicts](#drafts-and-conflicts)).

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
| `wiki/` | The wikis, as cards: name, description, page count, *Private* or *Protected*, *PDF*, *Open*; *New wiki*, *Access and members*, *Edit*, *Delete* and the *Trash* for those allowed |
| `wiki/<wiki>/` | The wiki's first page, or an invitation to write it |
| `wiki/<wiki>/<page>/` | A page, with its wiki's menu |
| `wiki/<wiki>/export.pdf` | The whole wiki as a PDF, portrait; `?orientation=landscape` turns the paper ([PDF](#pdf)) |
| `wiki/<wiki>/export.zip` | The whole wiki as an archive another site imports ([Export and import](#export-and-import)) |

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
  same wiki. Deleting a wiki moves it to the trash with its pages and
  their history, after a confirmation that counts them
  ([The trash](#the-trash)).
- `api`, `images` and `files` are the wiki's own routes: no wiki takes
  them (a wiki named "Files" gets `files-wiki`).

### Access, owner and members

A wiki's people are named on the wiki - not in a settings file, not in
a group every wiki shares. *Access and members*, on a wiki's card or
under its menu, sets three things:

| Access | Reads it | Writes its pages |
| --- | --- | --- |
| **Open** (the default, what a wiki was before) | everyone signed in | whoever holds the page permissions - and its editors, managers and owner |
| **Protected** | everyone signed in | its editors, managers and owner only |
| **Private** | its members and its owner only | its editors, managers and owner only |

- The **owner** is whoever made the wiki - created, copied or imported
  it. They read it, write in it, manage its members and may delete it,
  whatever their groups say. A wiki from before has none.
- A **member** is a person or a group - each of its people - with a
  role: a **reader** reads it, an **editor** adds, changes and deletes
  its pages, a **manager** also renames it and says who its members
  are. Someone with two roles - their own, their group's - has the
  higher.
- **The role is enough**: an editor of a wiki needs no group giving
  `add_wikipage`. In a protected or private wiki the page permissions
  give nothing - only the people named write there.
- Superusers read and write every wiki.

Members are found by name in the dialog: a few people and groups
matching what is typed (`GET wikis/<id>/candidates/?q=`), never the
whole directory - and only for whoever manages the wiki.

```python
from generic.wiki.access import page_rights, role_in, wiki_rights

page_rights(user, wiki)   # {"add": True, "change": True, "delete": True}
wiki_rights(user, wiki)   # {"change": ..., "members": ..., "delete": ...}
role_in(user, wiki)       # "owner", "manager", "editor", "reader" or ""
```

`generic_wiki.WikiMember` holds them (`wiki`, `user` or `group`,
`role`); `Wiki.access` and `Wiki.owner` the rest.

### Narrowing it from the project

On top of that, `GENERIC["WIKI_ACCESS"]` narrows the wikis anyone
reads: a function `(user, wikis) -> wikis`, or its dotted path,
given the queryset of wikis the rules above let the user read and
returning the part of it they may read.

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

`GENERIC["WIKI_EDIT_ACCESS"]` narrows where pages are written, wiki by
wiki: the same kind of function, given the wikis the user **writes
in** by the wiki's own access and members, and returning those they
may still write in.

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
The wikis themselves - renamed, deleted - answer to their owner, their
managers and the wiki permissions.

The document manager gives each wiki its **editing teams**
(`TeamWiki.editing_teams`): they read and write it, nobody else
writes in it; a wiki with none is written by whoever reads it.

## Who may do what

| Who | May |
| --- | --- |
| Anyone signed in | Read the pages, menu and history of every open and protected wiki, and of the private ones they are a member of |
| A wiki's **editor**, **manager** or **owner** | Create, edit, move, pin, restore, delete its pages, upload into them, and see to its trash - no permission needed |
| `generic_wiki.add_wikipage` | Create pages and subpages - in the **open** wikis |
| `generic_wiki.change_wikipage` | Edit a page of an open wiki, move it in the menu, pin it, restore a version |
| `generic_wiki.delete_wikipage` | Delete a page of an open wiki, restore it from the trash or delete it for good |
| A wiki's **manager** or **owner**, or `generic_wiki.change_wiki` | Rename a wiki they read, change its description, its access and its members |
| A wiki's **owner**, or `generic_wiki.delete_wiki` | Delete a wiki they read, restore it from the trash or delete it for good |
| `generic_wiki.add_wiki` | Create a wiki, copy one, import one from an archive - and own it |

Superusers hold all of them. Two ways to give people a wiki to write:
name them on the wiki - its editors - or, for the open wikis, give a
group the three page permissions. `add_wiki` is for whoever may start
wikis: on a wiki host, everyone.

## The page

The menu lists the pages as a tree, with a filter; a page stays in
sight while one of its subpages matches. The page shows its text, when
it was last changed and by whom, and - for editors - *Edit*, *Subpage*,
*History* and *Delete*.

*Edit* turns the page into the editor: its title, its parent page, its
position among its siblings, its address, whether it is pinned to the
dashboard, and the text, in [Quill](https://quilljs.com): headings,
bold and italics, text colour, lists, quotes, code, tables, links,
images - uploaded or by address - files, and alignment. *Save* sends everything to the API as JSON and reloads the
page as the server draws it; *Cancel* and leaving the page ask first
when something changed.

Under its text, the page lists its **attachments** - the images and
files it shows, in its order, a file with its size - each a link.

**History** lists the versions, newest first, with their author and
size, the page's current one marked. *Changes* shows what a version
changed from the one before it, and *Compare* what separates it from
the page as it stands ([Comparing versions](#comparing-versions)).
*View* opens a version read-only,
in the page's layout - `wiki/<wiki>/<page>/versions/<id>/` - with the
way back to the page and, for a writer, *Restore*, which brings it
back. Restoring saves the current text as a version first, unless it
is one already, so it can be undone like any other change; the
restored version is not written again: it is marked current where it
stands in the history. A text is in the history once
(`WikiRevision.keep` returns its entry; `page.current_revision()` is
the one the page holds). The last 50 versions of a page are kept.

**Deleting** a page moves it to the trash with its history; its
subpages move up a level - under the page it was under - rather than
disappearing with it ([The trash](#the-trash)).

### Comparing versions

A page is HTML; what a reader compares is its words. Each block - a
paragraph, a heading, a list item, a table row - is a line; lines put
in are green, lines taken out red and struck through, and a line that
was rewritten shows which words went and which came. Long runs of
unchanged lines are folded (`generic/wiki/diff.py`).

| Request | Answers |
| --- | --- |
| `GET pages/<id>/diff/?from=<version>` | from that version to the page as it stands |
| `GET pages/<id>/diff/?to=<version>` | what that version changed: from the one before it - from nothing, for the first |
| `GET pages/<id>/diff/?from=<a>&to=<b>` | between two versions |
| `GET pages/<id>/diff/` | what the last save changed |
| `POST pages/<id>/diff/` `{"title", "content"}` | from the page as it stands to the text sent, cleaned like a page - nothing is written |

`{"lines": [{"op": "equal" | "insert" | "delete", "text"}, {"op":
"change", "parts": [{"op", "text"}]}, {"op": "skip", "count"}],
"added", "removed", "before", "after", "version"}` - text only, which
the page writes as text. For any reader of the page.

### Drafts and conflicts

**Drafts.** While a page is written, its title and text are kept in
the browser (`localStorage`, by page) a moment after each change: a tab
closed by mistake, a session that ran out or a browser that crashed do
not take the text with them. Opening the editor again offers to *take
it up*. The draft is dropped once the page is saved or the changes
discarded, never leaves the browser, and remembers the version it was
written from - so a draft taken up after someone else saved is still
checked against their change.

**Conflicts.** The editor sends the version it started from. If someone
saved the page in between, the save is refused (`409`) with their name
- rather than silently overwriting their change - and a dialog shows
what this text would change in the page as it now stands, struck
through what it would take out: *Keep writing*, *Take their version*
(the page is loaded again), or *Save mine* (saved over theirs, which
stays in the history).

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
  `wiki-file` on a paragraph, a text colour), so a page cannot borrow
  the application's styles.

**Text colour** is a palette, not a free choice: red, orange, green,
blue, purple, gray - `TEXT_COLORS` in `generic/wiki/sanitize.py` -
written as a class on the run of text, `<span class="ql-color-red">`,
never as an inline style. A pasted `style="color: ..."` is dropped
with every other style, so a page cannot write white on white, and a
colour stays readable in both schemes: the page draws it with the
`--wiki-text-<name>` token (`tokens.css`), lighter in the dark one.
The PDF prints the colour of the light scheme.

On the page, the content also sits under `x-ignore`: Alpine never reads
anything in it as a directive.

## The API

Under `wiki/api/`, JSON, like every other screen:

| Request | Does |
| --- | --- |
| `GET wikis/` | The wikis: `id`, `name`, `slug`, `description`, `position`, `access`, `owner_name`, `url`, `pdf_url`, `page_count`, `can` (`change`, `members`, `delete`) |
| `POST wikis/` | A new wiki; the address comes from the name when not given |
| `PATCH wikis/<id>/` | Rename it, describe it, move it among the wikis |
| `DELETE wikis/<id>/` | Move it to the trash, with its pages |
| `GET wikis/<id>/members/` | Its `access`, `owner` and `members` (`kind` "user" or "group", `id`, `name`, `role`), for whoever manages it |
| `PUT wikis/<id>/members/` | Replace them: `{"access", "members": [{"user" or "group": id, "role"}], "owner": id}`, each part optional |
| `GET wikis/<id>/candidates/?q=` | People and groups by name, to add as members |
| `GET wikis/trash/` | The wikis in the trash the user may delete |
| `POST wikis/<id>/undelete/`, `purge/` | Out of the trash; deleted for good |
| `GET pages/` | The menu: every page, without its text; `?wiki=<id>` for one wiki's |
| `POST pages/` | A new page in `wiki` (left out: its parent's wiki, or the first); the address comes from the title when not given |
| `GET pages/<id>/` | One page, with its text, its `version` and its `attachments` |
| `PATCH pages/<id>/` | Change it; send `version` to be protected from overwriting |
| `DELETE pages/<id>/` | Move it to the trash; its subpages move up |
| `GET pages/trash/?wiki=<id>` | A wiki's pages in the trash, for whoever may delete pages there |
| `POST pages/<id>/undelete/`, `purge/` | Out of the trash; deleted for good |
| `GET`, `POST pages/<id>/diff/` | What changed ([Comparing versions](#comparing-versions)) |
| `GET pages/<id>/revisions/` | Its versions: `url` to read one, `current` on the one the page was restored to |
| `POST pages/<id>/restore/` | Bring one back: `{"revision": <id>}` |
| `POST pages/<id>/duplicate/` | A copy beside it: `{"title", "subpages"}` ([Duplicating](#duplicating)) |
| `POST wikis/<id>/duplicate/` | A copy of the wiki: `{"name", "description", "pages"}` |

A page carries its `wiki`; naming another one in a `PATCH`, or a
`parent` from another wiki, answers `400`, and so does an address
another page of the wiki has. `attachments` is read from the text,
never written: `[{"kind":
"image" | "file", "id", "name", "size", "url"}]`, in the page's order,
once each, leaving out an upload no longer in the database. A save
against an old version answers `409 Conflict`. The address
`api` is reserved; a page titled "API" gets `api-page`.

## Duplicating

A page's **Duplicate** (beside *Subpage*, for who may add pages in the
wiki) asks for the copy's title - *<title> (copy)* to start with - and,
when the page has subpages, whether they come along. The copy is
written beside the page, under the same parent, and opens in the
editor. On the list of wikis, a wiki's copy icon (for who may add a
wiki) asks for the copy's name and description and whether its pages
come along - every one, under the same parent as before, at the same
address within the new wiki.

What is copied is the text as it stands: the history is not - a copy
starts its own - and a copy is never pinned to the dashboard. Images
and files are shared, not copied: an upload belongs to whichever page
links to it.

Permissions: adding pages in the wiki (its editors, or `add_wikipage`
in an open wiki) for a page; `add_wiki` for a wiki - the copy is its
maker's, pages included, and keeps the source's access and members: a
private wiki's copy is not everyone's. Endpoints `POST
pages/<id>/duplicate/` and `POST wikis/<id>/duplicate/` (201 with the
copy; 400 without a title, 403 without the permission).

**Who reads the copy.** A new wiki is nobody's yet: whatever
`WIKI_ACCESS` says of a wiki with nothing attached decides. A project
that ties wikis to teams listens to
`generic.wiki.duplicates.wiki_duplicated` (`sender=Wiki`, `source`,
`copy`, `user`, sent in the copy's transaction) and gives the copy the
source's readers before anyone can open it:

```python
from generic.wiki.duplicates import wiki_duplicated


def keep_readers(sender, source, copy, **kwargs):
    link = TeamWiki.objects.filter(wiki=source).first()

    if link is not None:
        TeamWiki.objects.create(wiki=copy, team=link.team)


wiki_duplicated.connect(keep_readers)   # in AppConfig.ready()
```

`docmanager/` does this (`documents/wikis.py`): a team's handbook
copied stays the team's. Records of the project's own models are
duplicated by their resources: see [Duplicating records](duplicate.md).

## Images

*Insert an image*, in the editor's toolbar, offers **Upload an image**
- a file chooser - beside the image's address. The file is checked in
the browser, then sent to the framework's endpoint, and what comes back
is put in the page as an ordinary image:

| Request | Does |
| --- | --- |
| `POST api/generic/wiki/images/` | Multipart, part `file`: answers `201 {"id", "url"}`, `url` being `/wiki/images/<id>/` wherever the wiki is mounted (built with `reverse`) |
| `GET wiki/images/<id>/` | The image, for the readers of the wiki it was uploaded into |

- **Who**: an upload is sent with its `wiki` and needs the right to
  add or change pages there. Reading one is for whoever reads **that
  wiki** - or a page, or a version of one, showing it (a copy of a
  wiki shares its uploads) - and for whoever uploaded it; to anyone
  else it is not found (`404`). Signed out, the sign-in page. An
  upload sent without a wiki, by an editor from before, is its
  uploader's alone until a page shows it.
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

An image is a `generic_wiki.WikiImage` (`wiki`, `file`,
`original_name`, `uploaded_by`, `uploaded_at`), not attached to a
page: several pages - or earlier versions of one - may show it, so
nothing deletes it when a page stops doing so
([Cleaning up](#cleaning-up) does, once no text shows it). The files live in `MEDIA_ROOT`, which has to be
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
| `GET wiki/files/<id>/` | The file, downloaded under the name it was sent with, for the readers of the wiki it was uploaded into |

- **Who**: like images - writing pages in the wiki to upload, reading
  the wiki to download.
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
- the text with its headings, emphasis, text colours, lists, quotes,
  code, tables (every cell framed, as wide as the text) and alignment;
  a table cell whose text is partly formatted, which fpdf2 cannot draw,
  printed as its text, and a table it cannot draw at all (a row taller
  than the paper) printed as lines of text, a row a line, its cells
  separated by ` | `; links stay links, made absolute;
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

## Export and import

The archive button on a wiki's card, beside *Duplicate*, or beside its
name in the menu, downloads the whole wiki as one zip, `<wiki>.zip`, that any site
running the wiki - another project on the framework, the same one after
a reinstall, a test server - makes a new wiki from with *Import a wiki*
on the list of wikis. The PDF is to read; the archive is to move a
wiki.

```
handbook.zip
├── wiki.json                 the wiki and its pages
├── images/1.png              each image the pages show, once
└── files/2-Plan_2026.pdf     each file they link to, once
```

`wiki.json` is plain JSON, made to be read by other programs too:

```json
{
  "format": "django-generic.wiki",
  "version": 1,
  "generator": "django-generic 1.4.0",
  "exported_at": "2026-10-18T15:30:00+00:00",
  "wiki": {"name": "Handbook", "slug": "handbook", "description": "..."},
  "pages": [
    {"id": 1, "parent": null, "title": "Welcome", "slug": "welcome",
     "position": 1, "show_on_dashboard": true,
     "created_at": "...", "updated_at": "...",
     "content": "<p><img src=\"images/1.png\"></p>..."}
  ],
  "images": [{"path": "images/1.png", "name": "Team photo.png"}],
  "files": [{"path": "files/2-Plan_2026.pdf", "name": "Plan 2026.pdf",
             "size": 48213}]
}
```

- A page's `id` is its number in the archive, and `parent` the `id` of
  the page above it - nothing of the site it came from.
- In the pages' text an upload's address (`/wiki/images/7/`) is written
  as its place in the archive (`images/1.png`); the import writes back
  the address each upload gets on the new site. A link to an upload no
  longer stored is left as it was.
- A link from one page to another of the same wiki
  (`/wiki/handbook/welcome/#rules`) is written `pages/<id>/#rules`, and
  leads to the new page after the import; a link to another wiki, or
  anywhere else, stays as written.
- The history of the pages stays behind: the archive is the wiki as it
  stands, and the import starts each page's history afresh. So do the
  team settings a project keeps beside a wiki (the document manager's
  `TeamWiki`): the new wiki is everyone's until given to a team.

**Importing** makes a **new** wiki, never merges into one: nothing that
exists changes. It takes the archive's name - or the name sent with it
- and its address, or, when that is taken, one made from the name
(`handbook-2`); the pages keep
their titles, addresses, tree, order and pins, and are written by the
importer. What an archive holds is checked as if typed in the editor:

| Checked | How |
| --- | --- |
| The archive | a zip with a `wiki.json` of this `format` and a `version` this site reads - one written by a later version is refused, not half read; at most `WIKI_ARCHIVE_MAX_SIZE` (100 MB) sent, and as much once unpacked, counted before anything is read |
| The pages | cleaned like any page (`WikiPage.save`); addresses made unique in the wiki; a `parent` the archive does not hold, or a loop of parents, puts the page at the top |
| The images | told by their bytes, PNG, JPEG, GIF or WebP, like an upload from the editor; anything else - an SVG named `.png` - is left out |
| The files | at most `FILE_MAX_SIZE` each, like an upload; a larger one is left out |
| Every member | read only by the path the manifest gives under `images/` or `files/`, never unpacked to disk |

What is left out is named in the answer (`skipped`) and in the message
after the import. Any other fault refuses the whole archive with a
sentence saying why, and leaves nothing behind - neither rows nor
stored files.

**Who owns it.** Whoever imports a wiki owns it; it is open, like a
new one.

**Who.** Exporting is for whoever reads the wiki and may download files
- the archive holds them: under `ACCESS_ON_REQUEST` with `"download"`,
only those granted it ([Rights given on request](access-requests.md)), and
without that the button is gone and `export.zip` answers `403`.
Importing needs `generic_wiki.add_wiki`, and a new wiki the user may
write in (`WIKI_EDIT_ACCESS`): one they could not is undone with `403`.

| Address | Does |
| --- | --- |
| `GET wiki/<wiki>/export.zip` | the archive, an `attachment`, `Cache-Control: private, no-cache` |
| `POST wiki/api/wikis/import/` | multipart `file`, optional `name`; `201` with the new wiki (as `GET wikis/<id>/`) and `pages`, `images`, `files`, `skipped`; `400` `{"detail"}` for an archive refused |

From a script, a backup or another site's shell:

```bash
python manage.py wiki_export handbook --output /backups/handbook.zip
python manage.py wiki_import /backups/handbook.zip --name "Handbook (2026)"
```

From code: `generic.wiki.archive.write_archive(wiki, output)` writes
one to a binary file and returns the manifest;
`import_archive(source, user=None, name="")` returns an `ImportResult`
(`wiki`, `pages`, `images`, `files`, `skipped`) or raises
`ArchiveError`.

## The trash

Nothing is deleted at once. *Delete* on a page moves it to its wiki's
trash, with its history; *Delete* on a wiki moves the wiki there, with
its pages. What is in the trash is gone from every screen - the menu,
the search, the dashboard, the PDF, the archive, the API - and keeps
its address, which nothing else takes meanwhile.

| Where | Shows | For |
| --- | --- | --- |
| *Trash*, under a wiki's menu | its deleted pages, newest first, with who deleted them and when | whoever may delete pages there |
| *Trash*, on the list of wikis | the deleted wikis | their owner, or `delete_wiki` |

*Restore* brings a page back under the page it was under - at the top
of the menu if that one is gone - and a wiki back whole. *Delete for
good* deletes it, after a confirmation, with its history.

`WikiPage.objects` and `Wiki.objects` hold what is live;
`all_objects` the trash too (`deleted_at`, `deleted_by`).

## Cleaning up

```bash
python manage.py wiki_cleanup                  # empty the trash after TRASH_DAYS
python manage.py wiki_cleanup --days 7         # ... after 7 days
python manage.py wiki_cleanup --uploads        # and the uploads no page shows
python manage.py wiki_cleanup --dry-run        # count, delete nothing
```

Run once a day (cron, a scheduled task), it deletes for good the pages
and wikis in the trash for more than `GENERIC["TRASH_DAYS"]` days (30;
`None` keeps them until someone empties it). With `--uploads` it also
deletes the images and files that no text shows any more - no page,
live or in the trash, and no version in a history - uploaded more than
`--upload-days` days ago (7: a writer may still be in the editor), the
stored file with the row.

## Styles, sizes and images beside the text

The style menu sets a line's kind: *Heading 1* to *Heading 4*, or
*Normal*. The size menu beside it makes the selected text *Small*,
*Large* or *Huge* - a class, `ql-size-small`, `-large`, `-huge`
(`TEXT_SIZES` in `generic/wiki/sanitize.py`, with the share of the
text's size the PDF prints it at).

**An image beside the text**: click an image in the editor - it is
selected - then the image menu: *Image on the left, text beside it*,
*on the right*, or *Image in the line*. The image gets a class,
`wiki-float-left` or `wiki-float-right` (`IMAGE_FLOATS`), floats at
most half the text's width, its margin included, and the following
paragraphs run beside it. Images to the same side stand side by side,
the next one below them when the line is full; a heading starts below
them all.

**Images side by side**: two or more images in a line of their own,
none to one side, stay on that line, each at most its share of the
text's width (`calc(100% / n)`, up to six) - in the editor, on the page
and on the dashboard, however wide the window.

The PDF lays all of this out the same way. fpdf2 neither wraps text
round an image nor puts images side by side, so `write_beside` in
`generic/wiki/pdf.py` does it: an image beside the text is drawn on its
side, before the block that holds it, next to the ones already there
or below them when the room is gone; the blocks after it are written
with the margins moved past them, until one starts below them or on
another page; a heading starts below them. A paragraph of images alone
(`PageHTML.rows`) is drawn as a line, each image its share of the room,
their bottoms level. A paragraph is not split: one longer than the
image stays narrow to its end. An image beside the text inside a table
stays in its cell.

**Indentation and tabs**: the indent buttons (or Tab at the start of a
list item) move a line right by levels, `ql-indent-1` to `-8`; the PDF
moves it - and an image in it - by `INDENT_STEP` millimetres a level (`generic/wiki/pdf.py`,
through `WikiHTML`, fpdf2's renderer told the paragraph's level). A tab
typed inside a line is kept: the page shows it as the editor does, and
the PDF as four spaces.

## Tables

The table button in the editor's toolbar - or **Ctrl+Alt+T** - puts a
table of 3 rows and 3 columns where the cursor is, on a line of its
own; inside a table it does nothing, tables do not nest. The menu next
to it works on the table holding the cursor: insert a row above or
below, a column left or right, delete the row, the column or the whole
table. *Tab* moves to the next cell.

The editor is Quill's table module: plain cells (`<td>`), no header
row and no merged cells; a header row pasted in becomes a row of plain
cells. The size of a new table is `NEW_TABLE` in `generic/js/wiki.js`.

**Pasting a table** - from Excel, Word, Google Sheets, a web page - goes
through `pastedTables` in `generic/js/wiki.js` before Quill sees it,
which makes it a grid the editor can hold:

- a merged cell (`colspan`, `rowspan`) keeps its content in its first
  cell, and the cells it covered are empty: every row has the same
  number of cells, every value stays in its column;
- a cell holding paragraphs, line breaks or a list is one line, its
  pieces side by side; bold, italics and links in it are kept;
- header cells are plain cells, a caption a line above the table, a
  table inside a cell the text of that cell;
- a single cell - a value copied from a spreadsheet - pastes as its
  text, not as a table;
- inside a table, a pasted table pastes as its text.

A table starts a line of its own: pasted in the middle of a line, the
rest of the line goes after it.
On the page a table is as wide as the text, an empty cell as high as a
line; the PDF draws it with the rest.

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
  too - the server has the last word. A colour added to the palette
  goes in `TEXT_COLORS` (`sanitize.py`, with the PDF's colour), in
  `TEXT_COLORS` and `COLOR_LABELS` (`wiki.js`), and gets its
  `--wiki-text-<name>` token (`tokens.css`) and rules (`wiki.css`). The file block is the Quill blot
  `wikiFile`, registered there too.
- Without the framework's endpoints mounted (`generic.urls`), the
  editor offers no upload: images by address only, no paperclip.
