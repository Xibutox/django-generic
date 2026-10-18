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
- Boards: records as cards, a column per value of a field - a choice,
  a yes or no, or a foreign key - with *Not set* for records without
  one. `boards = (Board("name", field=..., ...),)` on a resource gives
  a page `<model>/<name>/` with the list's search and filters above
  it, each column's count and first 100 cards, cards coloured by a tag
  field and showing the values named in `fields`. With
  `editable=True`, a card dragged to another column - or sent there
  from its *Move to* menu, by keyboard - takes that value, written
  through `save_editable` (the field must be in `editable_fields`; a
  state field stays read only). `GET api/<app>/<model>/boards/<name>/`
  and `PATCH api/<app>/<model>/<pk>/boards/<name>/` `{"column"}`. In the
  example: *Support › Priorities*, tickets by priority. See
  docs/boards.md.
- A chart each reader draws above a list: `chart_builder` on a
  resource puts a *Chart* button in its table's toolbar, opening a
  card above the list - closed until opened - where the reader picks
  the form (bars, lines, areas, pie, donut, heatmap), the field the rows
  are grouped by, a second one splitting them, and the count of rows or
  the total or average of a number; a date by day, week, month, quarter
  or year. It follows the table's filters, a click on a bar filters the
  table, and the choices are remembered per table and saved with the
  table's views. `auto()` resources have it, the fields worked out
  (`chart_builder = False` takes it away); a `ModelResource` says
  `chart_builder = True`, a tuple of fields, or `ChartBuilder(...)`.
  `GET api/<app>/<model>/chart-builder/` accepts only the offered
  fields, by key. In the example: equipment and tickets. See
  docs/charts.md.
- `scripts/new_project.py`: a new project on the framework in one
  command, ready to deploy - the code, the framework's wheel in
  `vendor/`, a development and a production Docker stack, and
  `docker/prod.env` / `docker/dev.env` with every secret random and
  readable by its owner alone. The production stack drops every
  container's capabilities, runs them read-only with limits and
  rotated logs, keeps Postgres and Redis on a network with no way out,
  and backs the database and the uploaded files up every day,
  encrypted (GnuPG, AES-256), checked, pruned, with a weekly restore
  test recorded in `backups/restore-tests.log`. `python ops.py backup |
  verify | restore-test | restore` from the project, on any system;
  its `SECURITY-CONTROLS.md` maps each choice to ISO/IEC 27001 Annex A.
  See docs/new-project.md.

### Security
- Exports no longer carry formulas: a text starting with `=`, `+`, `-`,
  `@`, a tab or a carriage return - `=HYPERLINK(...)` typed into a
  record - is written to Excel as a text cell, and to the CSV behind an
  apostrophe, so it never runs in the spreadsheet of whoever exports
  the table or receives it by mailing (CWE-1236).
- Security events (`generic.audit`): every sign-in, failed sign-in,
  lockout, sign-out, password change, API token made or deleted, right
  granted or refused and export (Excel, CSV, mailings: the table and
  the number of rows) is written to the `generic.security` logger -
  refusals at `WARNING`, with the account and the address - and to the
  read-only *History › Security events* screen
  (`generic.view_securityevent`). Nothing to declare; `SECURITY_LOG`
  turns it off, `SECURITY_LOG_RETENTION_DAYS` keeps it to a size.
  Migration `generic 0022`. The lockout's own log line, which named
  neither the account nor the address, is replaced by its event.
  See docs/security-log.md.
- `SECURITY.md`: how to report a vulnerability privately, what
  follows, the versions supported, and the one dependency
  vulnerability accepted and why. The CI checks every dependency with
  `pip-audit`, runs `bandit` over the example applications too, and
  Dependabot proposes updates of the packages, Actions and images.
  The document manager reads Office XML through `defusedxml`.
- The history records every write. `QuerySet.update()`,
  `bulk_update()` and `bulk_create()` - which fire no signal and left
  no trace, nor did the framework's own uses of them (a right granted,
  a folder moved to another team) - now record a version of each row,
  as the database holds it, with the person behind it
  (`generic.history.bulk`; `with unrecorded():` for a data migration).
  On PostgreSQL a trigger on every recorded table records what is
  written outside the application - `psql`, another application, raw
  SQL - by the database role, "Database (outside the application)";
  the ORM's own statements are tagged and left to the application, so
  nothing is recorded twice (`generic.history.triggers`, installed
  after `migrate`, `manage.py history_triggers`, `HISTORY_TRIGGERS`).
  An API token's history is kept at last (`HistoryEntry.object_id`
  holds 128 characters, migration `generic 0023`), without its hash.
- Retention that runs: `manage.py apply_retention` and the managed
  task `generic.apply_retention` (to schedule daily) delete the history,
  access log and notifications older than `HISTORY_RETENTION_DAYS`,
  `ACCESS_LOG_RETENTION_DAYS` and `EVENTS_RETENTION_DAYS`
  (`generic.retention`). `EVENTS_RETENTION_DAYS` (90) was documented
  but applied by nothing: notifications were kept forever. The example
  keeps its access log a year, as the CNIL recommends.
- Document manager: an approval given for somebody else is stamped
  under the name of who gave it - "Alice (for Bob)" - on the approved
  PDF. It named the person asked, who had approved nothing.

### Added
- Bulk edit: `bulk_edit_fields = ("team", "assignee", "tags", ...)` on
  a resource puts *Edit the selected …* first in its tables' selection
  bar. A dialog asks which fields to change and to what - in the form's
  own controls; a many-to-many may be added to or removed from, an
  optional field cleared - then reviews the change (the whole edit run
  and rolled back: how many records would change, which would be left
  as they are and why) before writing it. Each record goes through its
  form serializer and `save_bulk_edit` (`save_model` by default),
  asked `has_change_permission(request, obj)` and `can_edit_column`;
  one history version each (*Bulk edit: <fields>*), one live event.
  `BULK_EDIT_MAX_ROWS` (1000). `auto()` works the fields out. In the
  example: tickets, where a closed ticket keeps its team. See
  docs/bulk-edit.md.
- Rights given on request: with `GENERIC["ACCESS_ON_REQUEST"] =
  ("export", "download")`, exporting tables (Excel, CSV, copy, print,
  scheduled mailings) and downloading files are permissions
  (`generic.export_rows`, `generic.download_files`) that people ask
  for. The export menu offers *Ask for permission…*, a record's file
  *Ask to download*, and the account page lists each right with a
  button to ask or remind. Every superuser and holder of
  `generic.validate_accessrequest` is notified, and grants or refuses
  on *People › Access requests*, which keeps every request. Asking
  again reminds them, no more than once an hour per person and right
  (`ACCESS_REQUEST_INTERVAL`). Off by default; on in the example,
  where the viewer has a download request waiting. Migration
  `generic 0021`. See docs/access-requests.md.
- A reminder before exporting or downloading: `EXPORT_DISCLAIMER` and
  `DOWNLOAD_DISCLAIMER` (a text, or `{"text", "title", "checkbox"}`)
  show a privacy notice with a box to tick before every table export,
  scheduled mailing and file download. Off by default; the example
  shows one for each.
- Reporting a bug: a bug icon in the top bar of every page - and
  *Report a bug* in the account menu and on the help page - opens the
  team's ticket service in a new tab. The project sets it with
  `GENERIC["BUG_REPORT_URL"]` (the example points at this repository's
  issues); an administrator holding `generic.change_helpsettings`
  replaces it for everyone from the form on the help page, without a
  deployment. `https://`, `http://` or `mailto:` only; nothing is drawn
  while no link is set. Migration `generic 0020`. See docs/ui.md.
- Server status: *Monitoring › Server status* shows this server's
  processors, memory, swap and disks as gauges, a trend line since the
  page opened, and whether each database, the migrations, each cache,
  the channel layer, Celery, the media folder and the tasks are
  working - and, beside it, every other server running django-generic
  added under *Monitoring › Monitored servers* with its address and
  token (`STATUS_TOKEN` on the other side). One maintenance server
  watches them all; a server that does not answer says why. Projects
  add checks of their own with `@generic.status.register_check` (the
  example's: *External services*). Every server answers the same JSON
  at `api/generic/status/`, and `api/generic/status/health/` is the
  one-word answer for a load balancer. psutil, the new `status` extra,
  measures; without it the page reads the standard library and
  `/proc`. Migration `generic 0019`, permission
  `generic.view_status`. See docs/status.md.
- Wiki history: every version can be read without restoring it -
  *View* opens it in the page's layout, read-only, with the way back
  to the page and, for a writer, *Restore*
  (`wiki/<wiki>/<page>/versions/<id>/`). The history marks the page's
  current version, and restoring a version no longer writes it to the
  history a second time: the page points back at its entry.
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
- Several images side by side look the same in the wiki's editor, on
  its page, on the dashboard and in the PDF: images in a line of their
  own stay on it, each at most its share of the width; images to one
  side stand next to each other, the next below when the line is full;
  a heading starts below the images beside the text.
- A wiki's PDF in landscape: its *PDF* button offers *Portrait* or
  *Landscape* (`export.pdf?orientation=landscape`;
  `generic.wiki.pdf.render(wiki, orientation="landscape")`).

### Fixed
- A message at the top of a page, and a toast in the corner, reads on
  one line: its icon and its dismiss button centre on its first line
  of text, where the icon stood a few pixels above it and the text a
  pixel below. A long message wraps beneath them, and a one-line
  message is no taller than its text and padding.
- Small misalignments across the interface, the style unchanged. The
  navigation's filter box shares the edges of the links below it, and
  the version in the sidebar's foot their icons' column. A table's
  tools are one height: the filter-row toggle, the reload button and
  the page buttons now match the small buttons beside them, and the
  server-rendered list's *Apply* its action picker. A chart's period
  picker is a small control again, so a chart card holding one has
  the header height of the card beside it. Cards laid out by a grid or
  a stack take only its gap: the wiki's page starts level with its
  menu, every task card on the task catalogue level with the first,
  the customer map's legend level with the map, and the cards of the
  account page, the help and the import pages no longer stand twice as
  far apart as anywhere else. The account page's *Watching* rows start
  where the card's title does. The dashboard's shortcuts keep their
  titles on one line across a row, a two-line description no longer
  pushing one down. *Yes* and *No* in a table sit on the line of the
  row's text, not a pixel above. In the document manager, *Start each
  file on a new page* lines up with the file name beside it.
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
