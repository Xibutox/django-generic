# The wiki

`generic.wiki` is a small wiki inside the application: pages in a menu,
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

The `wiki` extra - nh3, which cleans the pages' HTML - in the brackets
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

## Who may do what

| Who | May |
| --- | --- |
| Anyone signed in | Read every page, its menu and its history |
| `generic_wiki.add_wikipage` | Create pages and subpages |
| `generic_wiki.change_wikipage` | Edit a page, move it in the menu, pin it, restore a version |
| `add_wikipage` or `change_wikipage` | Upload an image or a file into a page |
| `generic_wiki.delete_wikipage` | Delete a page |

Superusers hold all of them. For editors who are not superusers, give a
group the three permissions.

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
| `GET pages/` | The menu: every page, without its text |
| `POST pages/` | A new page; the address comes from the title when not given |
| `GET pages/<id>/` | One page, with its text, its `version` and its `attachments` |
| `PATCH pages/<id>/` | Change it; send `version` to be protected from overwriting |
| `DELETE pages/<id>/` | Delete it; its subpages move up |
| `GET pages/<id>/revisions/` | Its earlier versions |
| `POST pages/<id>/restore/` | Bring one back: `{"revision": <id>}` |

`attachments` is read from the text, never written: `[{"kind":
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

- The page is `generic/wiki/page.html`; a project overrides it like any
  template.
- The pinned pages are drawn by `generic/wiki/includes/pinned.html`, in
  the `dashboard_pinned` block of `generic/site/index.html`.
- The editor's toolbar is `TOOLBAR` in `generic/js/wiki.js`. Adding a
  format there means allowing its HTML in `generic/wiki/sanitize.py`
  too - the server has the last word. The file block is the Quill blot
  `wikiFile`, registered there too.
- Without the framework's endpoints mounted (`generic.urls`), the
  editor offers no upload: images by address only, no paperclip.
