# Changelog

What changed in the Support desk, the example application of this
repository, newest first.

This file is the application's: the *Help › What changed* page shows
it first, then the framework's own, which ships inside the package -
[generic/CHANGELOG.md](generic/CHANGELOG.md). A project built on
django-generic keeps its changelog here, at its root, the same way.

The format is [Keep a Changelog](https://keepachangelog.com).

## [Unreleased]

### Added
- A user guide for every application built on the framework: the
  everyday actions - finding one's way, the search, filtering, views,
  exports, bulk actions, a record's page, the forms, deleting, the
  history, the wiki, the account - written once, in English and French.
  Every wiki starts with it: a migration puts *User guide* / *Guide
  utilisateur* in the first wiki, one page per language of the site,
  and `manage.py wiki_user_guide` puts it back or brings it up to date
  (`--update`, the replaced text kept in the page's history). The same
  text as a Word document, illustrated, is
  `docs/user-guide/guide-utilisateur.docx`
  (`scripts/build_user_guide.py`).
- Text colour in the wiki's editor: the *A* in its toolbar colours the
  selected text red, orange, green, blue, purple or gray, or gives it
  back its own colour. The colours read in the light and the dark
  scheme (`--wiki-text-*` tokens) and are printed in the wiki's PDF;
  the server keeps only these (`TEXT_COLORS` in
  `generic.wiki.sanitize`, as `ql-color-<name>` classes), never an
  inline style.
- Tables in the wiki's editor: the table button in its toolbar, or
  Ctrl+Alt+T, puts a 3 x 3 table on a line of its own; the menu next to
  it adds a row above or below, a column left or right, or deletes the
  row, the column or the table. A table already in a page is now kept
  as a table when the page is edited (Quill's table module), and an
  empty cell keeps a line's height on the page.
- More styles in the wiki's editor: *Heading 1* joins the style menu
  (Heading 1 to 4, Normal), and a size menu beside it makes text
  small, large or huge (`ql-size-*` classes, printed in the PDF). The
  menus' names are translated.
- Text beside an image in the wiki: click an image, then the image
  menu puts it on the left or the right with the text running beside
  it, or back in the line (`wiki-float-left` / `-right` on the image,
  at most half the text's width). The PDF does the same: the image on
  its side, the following paragraphs in the room beside it until one
  starts below it.
- A wiki's PDF in landscape: its *PDF* button offers *Portrait* or
  *Landscape* (`export.pdf?orientation=landscape`;
  `generic.wiki.pdf.render(wiki, orientation="landscape")`).

### Fixed
- A table pasted into the wiki's editor from Excel, Word, Google
  Sheets or a web page no longer breaks the page. Merged cells no
  longer push the cells after them into the wrong column: the content
  stays in the first cell and the covered cells are left empty. A cell
  holding several paragraphs or a list stays one cell, the text on one
  line, instead of being torn into several cells or tables. Headers
  become plain cells and a caption becomes a line above the table. A
  single copied cell pastes as plain text, and a table pasted inside a
  table pastes as its text.
- A wiki's PDF no longer fails on a table cell whose text is partly
  formatted - a bold word, a coloured figure, as Excel and Word paste
  them - which fpdf2 refuses: such a cell is printed as its text, and a
  cell formatted throughout keeps its format. A table fpdf2 still
  cannot draw - a row taller than the paper, as a wide spreadsheet
  makes ("The row with index ... is too high") - is printed as lines of
  text, a row a line, its cells separated by " | ", rather than
  stopping the whole wiki's PDF.
- A wiki's PDF keeps the editor's indentation - a paragraph, heading,
  quote or list item moved right with the indent buttons or Tab is
  moved right in the PDF too, an image in it included - and a tab
  typed in a line is printed as
  space, not dropped. On the page, tabs and runs of spaces show as in
  the editor.
- A table in a wiki's PDF has its borders: every cell framed, as the
  page shows it, and the table as wide as the text. fpdf2 drew only a
  line over it.
- A large image no longer runs off a wiki's PDF: every image is drawn
  at most the text's width and a page's height, its shape kept, and a
  smaller one at the size the page shows it.
- The document manager in Docker: gunicorn takes request lines up to
  8190 bytes (`--limit-request-line`), not 4094, so a table with many
  columns or filters no longer answers 400 "request line is too
  large". Tables also ask for less: of what DataTables builds, they
  send only what the endpoint reads (each column's name, the order, the
  search box), not six parameters a column.

## [1.3.0] - 2026-10-05

### Added
- The document manager runs in Docker: `docmanager/compose.yaml` puts
  gunicorn behind nginx, which redirects HTTP to HTTPS, serves the
  static files and signs its own certificate on its first start. The
  data lives in PostgreSQL, the cache (and so the sign-in lock, shared
  by every worker) in Redis, and the documents' files in
  `docmanager/data/documents` on the host (`DOCUMENTS_DIR`). Ports and
  names come from `docmanager/.env`. Without those services the
  settings fall back on SQLite and the local-memory cache, as before.
  `DEMO_DATA=0` starts it empty, with its roles (Editors, Readers,
  Quality, Managers - `seed_documents --roles-only`) and, from
  `DJANGO_SUPERUSER_USERNAME`, `_PASSWORD` and `_EMAIL`, a first
  administrator. See docmanager/README.md.
- The document manager grows: search inside files (Office formats and
  PDF), versions labelled 0.1, 1.0, 1.1, 2.0 with readers seeing only
  the published one, approved PDFs stamped, a preview page for
  documents and versions, folders in folders, periodic reviews that
  remind and start on their own, and deleted documents kept in a
  trash. Every documents table carries preview and download icons,
  and the documents list starts with fewer columns.
- Customers keep an access log: who opened which customer, under
  *History › Access log* and from each customer's page. A ticket's
  page offers *Mark as billable* only when the ticket is not billable
  yet, and every action button says what it does.
- A minimal example beside the full one, `minimal/`: one settings
  file, the URLs and one app with one model whose screens come from
  `auto(Book)`, on the core package alone, with the wiki and a Docker
  image of its own. With `MICROSOFT_CLIENT_ID`,
  `MICROSOFT_CLIENT_SECRET` and `MICROSOFT_TENANT_ID` set, it signs in
  with Microsoft through django-allauth. See minimal/README.md.
- The document manager becomes a GED: documents numbered by each
  team's codification (`LEG-CTR-2026-0001`, a pattern per team on the
  framework's new `generic.numbering`), with or without a file -
  a number may be reserved before the document is written; document
  types; review circuits anyone may draw (steps of review, approval
  or reading, asking people, roles, the team's leaders or members, one
  of them or each of them), a document sent through one with its steps
  still editable, a task per person answered with a comment or handed
  to someone else, each person asked told by notification and e-mail,
  the starter and the team's leaders told of every step; nothing
  blocks - a step nobody can answer is skipped, the starter and the
  leaders may skip, add, remind, answer for someone or cancel.
  Also comments, related documents, a next-review date, an advisory
  check-out, *Make obsolete*. Wikis get editing teams: only they write
  in a wiki that has some (`GENERIC["WIKI_EDIT_ACCESS"]`). Teams get
  leaders (`Team.leaders`).
- The document manager gives each team its wiki: `TeamWiki` links a
  wiki to a team, and `documents/wikis.py`, plugged in as
  `GENERIC["WIKI_ACCESS"]`, lets only its members - and whoever sees
  every team - read it, its pages and its PDF. `seed_documents` makes
  *Company* (everyone's) and three teams' handbooks.
- A document manager beside the examples, `docmanager/`: teams each
  with their folders and documents, every file a document has had kept
  as a version - who sent it, when, why, its size and SHA-256 - and
  downloaded under the name it was sent with; *Restore* makes an old
  version current again as a new one. Lists search and filter by
  format (`DOCX`, `PDF`...), with a *Word files* preset. *Merge Word
  files*, in the navigation, puts documents and versions together into
  one `.docx` made from a `.docx`/`.dotx` template - downloaded, or
  kept as a new document - and the lists' *Merge into Word* action
  opens it with the selection. The merge is the example's own
  (`docmanager/requirements.txt`: python-docx, docxcompose).
  `seed_documents` makes three teams and six accounts. See
  docmanager/README.md.
- A bulk action may open a page of the site: `{"redirect": "/path/"}`
  sends the browser there (`Generic.operations.handle`); another
  site's address is refused. See docs/sites.md.
- Teams in the framework, `generic.teams` (migration `0001`): a `Team`
  of members, and `team_field` on a resource - `"team"`,
  `"folder__team"`, `"teams"` - narrows its lists, pages, searches,
  files, watches and the forms pointing at it to the reader's teams;
  another team's key sent by hand is refused. Superusers and holders of
  `generic_teams.see_every_team` see everything; `scope_to_teams()`
  for views of a project's own. `scope_relations = True` gives forms
  the same narrowing for any resource restricting its rows. See
  docs/teams.md.
- `form_extra_fields`: questions a form asks that the model does not
  keep - a change note - write only and handed to `save_model` as
  `serializer.extra_values`; `get_download_name()` downloads a file
  under another name than the stored one. See docs/forms.md.
- Files in the wiki: the editor's paperclip - or a drop, or a paste -
  uploads files into a page, where each becomes a block linking to its
  download; images dropped or pasted land in the text the same way.
  The arrows of the toolbar (Alt+Up / Alt+Down) move a line, an image
  or a file up and down the page, and a page lists its attachments
  under its text. *How we triage* holds a checklist file. The
  framework's side: `generic_wiki.WikiFile` (migration `0003`),
  `POST api/generic/wiki/files/`, `GET wiki/files/<id>/` (always a
  download), the `wiki-file` block kept by the cleaning, and
  `attachments` in the page's API. See docs/wiki.md.
- Operations: the work behind a button, answered with a report. On the
  ticket list (or a ticket's page) **Check** looks at each selected
  ticket in the request and answers with a card holding a section per
  ticket - folded when nothing is wrong, open on the warning or the
  error otherwise. On the customer list **Review** goes through the
  selected customers in the background (a thread on a laptop, a worker
  in Docker): the card says it is running, then turns into the report
  when it ends, and the bell leads to the run's page with the same
  tree. The framework's side: `generic.reports.Report` (levelled lines,
  sections that fold, isolated sections that roll back one item and go
  on), `@operation` and `operation_response` in `generic.tasks`, a
  report on every task run (`TaskRun.tree`, migration `0016`), the
  `OPERATION_FALLBACK` setting and `Generic.operations` in the browser.
  See docs/operations.md.

## [1.2.0] - 2026-09-27

### Added
- Tickets carry an attachment, chosen in their form and downloaded from
  their page - behind the ticket's own permission - and the wiki's
  pages show images uploaded from its editor. The seed attaches a log
  to SD-1000. The production stacks keep uploads in an `app-media`
  volume, to back up with the database (docs/deployment.md). The
  framework's side is in generic/CHANGELOG.md, 1.2.0.
- Browser tests: `tests/browser/` drives the Support desk through a
  real Chromium - signing in, the ticket list (search, ordering,
  paging, a reload, a `status:open` chip, a bulk transition, the Excel
  download), the add and change forms, a summary page's tabs (the
  regression test for 1.1.0's `GenericDataTables.start` race), a
  transition's dialog, the Triage grid, an import, the command
  palette, the dark theme, French and the navigation on a phone, a
  ticket's attachment (chosen, downloaded, replaced, removed, refused
  before sending, refused to a stranger) and a wiki image uploaded
  from the editor - and fails on any error a page logs. Python Playwright through
  pytest-playwright against `live_server`, no Node; opt-in with the
  new `browser` extra (`pytest tests/browser -m browser --no-cov`, a
  plain `pytest` leaves them out), and a CI job of their own that keeps
  the screenshots of what failed. See docs/testing.md.
- The production stack behind nginx: `docker/docker-compose.prod-nginx.yml`
  is the Caddy stack with nginx in front (the `nginx` image target),
  serving the server's own certificate, or plain HTTP to try it. For a
  server whose nginx already serves other applications,
  `docker/docker-compose.host-nginx.yml` runs the stack without a
  proxy - Daphne on 127.0.0.1, the static files copied to a folder -
  and `docker/nginx/host-site.conf.example` is the server block to add.
  `docker/nginx/django-generic.conf` holds what any nginx needs for the
  application: the WebSocket upgraded and kept open, the scheme and the
  client's address set by nginx, uploads the size imports send. CI runs
  `nginx -t` on every configuration. See docs/deployment.md.
- Unexpected errors are mailed to `DJANGO_ADMINS`, and everything is
  logged to standard output and, with `DJANGO_LOG_FILE`, to a file: the
  production stack writes `/app/logs/app.log` in an `app-logs` volume
  from every service. The worker logs through the project's settings
  rather than Celery's own handlers (`generic.logs`, docs/logging.md).

### Fixed
- The installation guide says how the framework really arrives: it is
  not on PyPI, where `django-generic` is an unrelated package, so a
  project builds its wheel from the repository, keeps it in `vendor/`
  and names it by its path in `requirements.txt`. Two walkthroughs, a
  new project from nothing and an existing one, both run as written;
  Docker, updating and working on the framework beside a project
  follow. The README and the feature pages no longer say `pip install
  django-generic[...]`.

## [1.1.0] - 2026-09-26

### Added
- Searches ignore accents: `region` finds *Région Occitanie*. The
  project installs `generic.search`, and tickets and customers have
  trigram indexes on PostgreSQL. Some seeded names carry their accents
  to show it.
- Tickets and customers can be imported from a spreadsheet: *Import*
  on their lists. A ticket's reference and a customer's code find the
  record to update.
- The admin account is sent the open urgent tickets every weekday at
  eight (*Scheduled mailings*, in the Tasks group), and the scheduler
  runs the mailings every five minutes.
- A ticket moves through its life by buttons: *Wait for the customer*,
  *Customer answered*, *Resolve* (with a resolution), *Close*, and
  *Reopen* for supervisors (`example.reopen_ticket`). The status is no
  longer edited in forms, the Triage grid or imports, and the list's
  *Close* action is the generated one.
- Scripts call the API with a token made on the account page; the
  seed prints a read-only one for admin. `api/docs/` describes every
  endpoint.

### Fixed
- *Run now* hands the task to the Celery worker. The web server never
  loaded the project's Celery application, found no broker, and ran
  every task in the request; `example_project/__init__.py` now imports
  it, as Celery's guide for Django does.
- A page left quiet keeps its live connection. With redis-py 8, a reply
  from Redis is given up on after 5 seconds - the time channels-redis
  waits for the next event - and every quiet WebSocket was closed and
  reopened, deaf in between. The channel layer now waits 15.
- The development Docker stack migrates first, in a `migrate` service
  web, worker and beat wait for: beat no longer exits on a new
  database, its tables not there yet.
- `pytest` in the development image passes whoever owns the mounted
  checkout: the coverage data go to `/tmp`.
- Mail is configured the Django 6.1 way, with `MAILERS`, and still
  with `EMAIL_BACKEND` and the `EMAIL_*` settings on Django 5.2
  (`mail_settings` in `example_project/settings/base.py`). The same
  `EMAIL_*` variables drive production; without `EMAIL_HOST`, mail
  still goes to the log and `check --deploy` still has nothing to say.

## [1.0.0] - 2026-09-25

The example released with django-generic 1.0.0: a small support desk
chosen to show every feature at work.

### Screens
- Tickets, customers, time entries, teams, agents and tags, declared by
  hand in `example/resources.py`: coloured tags, summary pages with
  figures, charts and related tables, inlines, bulk actions, presets.
- Suppliers, equipment and maintenance visits declared with two
  `auto()` lines.
- External services and their incidents, a status API's answer served
  by data resources, with a runbook page per service.
- Pages of their own: a map of the customers and the same as GeoJSON, a
  ticket's timeline.
- Triage and a ticket's hours as grids; the classic server-rendered
  views kept under `/demo/` for comparison.
- *Live updates*: what the connection behind every page carries, each
  frame with what it made happen, and channels of the project's own.

### Running it
- `seed_example` fills the desk with customers, a few hundred tickets,
  time entries, comments, a wiki, a welcome message to everyone and
  three users - `admin`, `viewer` and `guest`, password `demo`.
- Development and production settings, and a Docker stack for each.
- `debug.py`, the server under a debugger in one process, and the VS
  Code configurations for it - server, a command, the tests, a Celery
  worker, and attaching to the development stack in Docker.
