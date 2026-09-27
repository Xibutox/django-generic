# The wiki

`generic.wiki` is a small wiki inside the application: pages in a menu,
written with a rich-text editor by the people allowed to, read by
everyone signed in, with a history of every version. A page can be
pinned to the dashboard, which makes the wiki the natural home for
announcements and how-tos.

It is optional, and deliberately modest: no workflow, no comments, no
attachments.

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
bold and italics, lists, quotes, code, links, images by address,
alignment. *Save* sends everything to the API as JSON and reloads the
page as the server draws it; *Cancel* and leaving the page ask first
when something changed.

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
- no `script`, no `style`, no event handler, no inline style;
- links and images to `http`, `https`, `mailto` and `tel` only, or
  relative - another wiki page, a record of the application; links get
  `rel="noopener noreferrer"`;
- no image data: an image is inserted by its address, never uploaded
  or inlined;
- only the editor's own classes (alignment, indentation, code blocks),
  so a page cannot borrow the application's styles.

On the page, the content also sits under `x-ignore`: Alpine never reads
anything in it as a directive.

## The API

Under `wiki/api/`, JSON, like every other screen:

| Request | Does |
| --- | --- |
| `GET pages/` | The menu: every page, without its text |
| `POST pages/` | A new page; the address comes from the title when not given |
| `GET pages/<id>/` | One page, with its text and its `version` |
| `PATCH pages/<id>/` | Change it; send `version` to be protected from overwriting |
| `DELETE pages/<id>/` | Delete it; its subpages move up |
| `GET pages/<id>/revisions/` | Its earlier versions |
| `POST pages/<id>/restore/` | Bring one back: `{"revision": <id>}` |

A save against an old version answers `409 Conflict`. The address
`api` is reserved; a page titled "API" gets `api-page`.

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
  too - the server has the last word.
