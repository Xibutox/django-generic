# Changelog

What changed in django-generic, newest first. The *Help › What changed*
page of every application built on it reads this file - shipped inside
the package - after the application's own.

The format is [Keep a Changelog](https://keepachangelog.com), and the
versions follow [semantic versioning](https://semver.org): from 1.0.0
on, a declaration that works keeps working until the next major
version.

## [1.4.0] - 2026-10-18

### Added
- Field permissions: `field_permissions` on a resource names who may
  see a field and who may change it (`{"unit_cost":
  "example.change_article"}`, or `(view, change)`). A field a reader
  may not see is gone for them from the list's columns, filters,
  ordering, search and facets, the exports and mailings, the form, the
  record's JSON, imports, the summary's sections and figures, the
  history tab, charts and the chart builder, trees, calendars, boards,
  comparisons and labels. A field they may see but not change is read
  only in the form and refused in table cells, grids, bulk edits,
  imports, calendar and board moves. See docs/field-permissions.md.
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
  and `PATCH api/<app>/<model>/<pk>/boards/<name>/` `{"column"}`. See
  docs/boards.md.
- Records side by side: `compare_fields` on a resource (`True` for
  the summary page's sections, or a tuple of fields) puts *Compare the
  selected ...* in the list's selection bar, for two to six rows
  ticked. The page `<model>/compare/?ids=3,8,12` shows a column per
  record and a row per field, each value drawn as the summary page
  draws it, the rows that differ marked, a switch showing only them,
  and records taken out one by one. Records come through the list's
  queryset and each one's view permission.
  `GET api/<app>/<model>/compare/?ids=`. See docs/compare.md.
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
  fields, by key. See docs/charts.md.
- Pivot tables: the chart builder's new *Table* form crosses the
  chosen fields in a table of figures - a row per value of the first,
  a column per value of the second - with a total column, a total row
  and the grand total, each its own aggregate (the total of an average
  is the average of every row). Figures are tinted by size, a click on
  one filters the table, and the table downloads as CSV. Every row is
  kept, with no *Other*, up to 200 rows and 50 columns. A declared
  `Chart(type="pivot", ...)` draws the same table. See docs/charts.md.
- Bulk edit: `bulk_edit_fields = ("team", "assignee", "tags", ...)` on
  a resource puts *Edit the selected ...* first in its tables'
  selection bar. A dialog asks which fields to change and to what - in
  the form's own controls; a many-to-many may be added to or removed
  from, an optional field cleared - then reviews the change (the whole
  edit run and rolled back: how many records would change, which would
  be left as they are and why) before writing it. Each record goes
  through its form serializer and `save_bulk_edit` (`save_model` by
  default), asked `has_change_permission(request, obj)` and
  `can_edit_column`; one history version each (*Bulk edit:
  <fields>*), one live event. `BULK_EDIT_MAX_ROWS` (1000). `auto()`
  works the fields out. See docs/bulk-edit.md.
- Labels with QR codes: `labels = True` or `Labels(fields=...,
  size=..., content=...)` on a resource adds the bulk action *Print
  labels* (the rows ticked or every matching row, up to 500) and a
  *Label* button on each record's page. The sheet lays out stickers of
  the record's name, a few values and a QR code holding the address of
  its page (or a field's value), printed without the frame at small,
  medium or large sizes. Codes come from segno, the new `labels` extra;
  without it the address is written out. See docs/labels.md.
- Rights given on request: with `GENERIC["ACCESS_ON_REQUEST"] =
  ("export", "download")`, exporting tables (Excel, CSV, copy, print,
  scheduled mailings) and downloading files are permissions
  (`generic.export_rows`, `generic.download_files`) that people ask
  for. The export menu offers *Ask for permission...*, a record's file
  *Ask to download*, and the account page lists each right with a
  button to ask or remind. Every superuser and holder of
  `generic.validate_accessrequest` is notified, and grants or refuses
  on *People › Access requests*, which keeps every request. Asking
  again reminds them, no more than once an hour per person and right
  (`ACCESS_REQUEST_INTERVAL`). Off by default. Migration
  `generic 0021`. See docs/access-requests.md.
- A reminder before exporting or downloading: `EXPORT_DISCLAIMER` and
  `DOWNLOAD_DISCLAIMER` (a text, or `{"text", "title", "checkbox"}`)
  show a privacy notice with a box to tick before every table export,
  scheduled mailing and file download. Off by default.
- Reporting a bug: a bug icon in the top bar of every page - and
  *Report a bug* in the account menu and on the help page - opens the
  team's ticket service in a new tab. The project sets it with
  `GENERIC["BUG_REPORT_URL"]`; an administrator holding
  `generic.change_helpsettings` replaces it for everyone from the form
  on the help page, without a deployment. `https://`, `http://` or
  `mailto:` only; nothing is drawn while no link is set. Migration
  `generic 0020`. See docs/ui.md.
- Server status: *Monitoring › Server status* shows this server's
  processors, memory, swap and disks as gauges, a trend line since the
  page opened, and whether each database, the migrations, each cache,
  the channel layer, Celery, the media folder and the tasks are
  working - and, beside it, every other server running django-generic
  added under *Monitoring › Monitored servers* with its address and
  token (`STATUS_TOKEN` on the other side). One maintenance server
  watches them all; a server that does not answer says why. Projects
  add checks of their own with `@generic.status.register_check`.
  Every server answers the same JSON at `api/generic/status/`, and
  `api/generic/status/health/` is the one-word answer for a load
  balancer. psutil, the new `status` extra, measures; without it the
  page reads the standard library and `/proc`. Migration
  `generic 0019`, permission `generic.view_status`. See
  docs/status.md.
- A user guide for every application built on the framework: the
  everyday actions - finding one's way, the search, filtering, views,
  exports, bulk actions, a record's page, the forms, deleting, the
  history, the wiki, the account - written once, in English and French.
  Every wiki starts with it: a migration puts *User guide* / *Guide
  utilisateur* in the first wiki, one page per language of the site,
  and `manage.py wiki_user_guide` puts it back or brings it up to date
  (`--update`, the replaced text kept in the page's history). The same
  text as a Word document, illustrated, is
  `docs/user-guide/guide-utilisateur.docx`.
- Wiki history: every version can be read without restoring it -
  *View* opens it in the page's layout, read-only, with the way back
  to the page and, for a writer, *Restore*
  (`wiki/<wiki>/<page>/versions/<id>/`). The history marks the page's
  current version, and restoring a version no longer writes it to the
  history a second time: the page points back at its entry.
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
- `PageSweep` counts queries: `test_rows_cost_the_same_however_many`
  reads each resource's rows once with one row and once with up to
  `query_rows` (25), and fails, listing the SQL, when the second costs
  more - a column reading a relation row by row (an N+1) is caught on a
  test database of a few records instead of in production. A resource
  with one record gets a copy of it to compare. Every project's sweep
  gains the test; `generic.testing.capture_queries` counts the queries
  of any block.

### Changed
- Python 3.14 and Django 6.1 join the supported versions, and the
  framework is tested on PostgreSQL 17 beside 16.

### Fixed
- Tags keep a readable text whatever colour a record gives them: its
  lightness is held where it reads on the tag's background in either
  scheme (4.5:1); an orange tag read at 4.4:1, a white one at 2:1.
- The warning colour (badges, the appearance preview) reads at 4.5:1 on
  its background.
- A Select2 choosing several values is named after its label for screen
  readers.
- The table's *Search or filter* box is a combobox: the suggestions it
  offers are announced.
- The calendar's days sit in rows, one per week, as a grid's cells
  must.
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
  and the cards of the account page, the help and the import pages no
  longer stand twice as far apart as anywhere else. The account page's
  *Watching* rows start where the card's title does. The dashboard's
  shortcuts keep their titles on one line across a row, a two-line
  description no longer pushing one down. *Yes* and *No* in a table
  sit on the line of the row's text, not a pixel above.
- Tables ask for less: of what DataTables builds, they send only what
  the endpoint reads (each column's name, the order, the search box),
  not six parameters a column, so a table with many columns or filters
  no longer goes over a server's request-line limit (gunicorn's 4094
  bytes, answered 400 "request line is too large").
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
  typed in a line is printed as space, not dropped. On the page, tabs
  and runs of spaces show as in the editor.
- A table in a wiki's PDF has its borders: every cell framed, as the
  page shows it, and the table as wide as the text. fpdf2 drew only a
  line over it.
- A large image no longer runs off a wiki's PDF: every image is drawn
  at most the text's width and a page's height, its shape kept, and a
  smaller one at the size the page shows it.

### Security
- Signed out after a silence: `generic.middleware.SessionIdleMiddleware`
  and `GENERIC["SESSION_IDLE_MINUTES"]` sign out a session nobody used
  for that long. What a page fetches by itself carries `X-Generic-Idle`
  (seconds since the reader last clicked, typed or scrolled), so a live
  table refreshing all night keeps nobody signed in; the refused page
  reloads onto the sign-in page, which says why. Off by default.
- A Content-Security-Policy: `generic.middleware.CSPMiddleware` and
  `GENERIC["CONTENT_SECURITY_POLICY"]` (`"recommended"`, or directives
  of your own; `CONTENT_SECURITY_POLICY_REPORT_ONLY` to try it).
  Nothing from elsewhere runs in a page; the framework's three inline
  scripts carry the request's nonce (`{% csp_nonce %}`), and the API
  docs page loads its script from its own address. Off by default.
- Argon2: the `argon2` extra (`argon2-cffi`); a project listing
  `Argon2PasswordHasher` first in `PASSWORD_HASHERS` rehashes older
  passwords at the next sign-in. See docs/security.md.
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
  but applied by nothing: notifications were kept forever.

## [1.3.0] - 2026-10-05

### Added
- Operations: the work behind a button, answered with a report.
  `generic.reports.Report` holds levelled lines and sections that fold,
  and isolated sections that roll back one item and go on.
  `@operation` and `operation_response` in `generic.tasks` run the
  work in the request or, with `.start(request, background=True)`, in
  the background: through Celery, or a thread when no worker answers
  (`OPERATION_FALLBACK`). Every task run keeps its report
  (`TaskRun.tree`, migration `generic 0016`), and `Generic.operations`
  draws it in the browser as a card that follows the run until it
  ends. See docs/operations.md.
- Teams, `generic.teams` (an optional app, migrations `0001` and
  `0002`). A `Team` has members and leaders. `team_field` on a
  resource (`"team"`, `"folder__team"`, `"teams"`) narrows its lists,
  pages, searches, files, watches and the forms pointing at it to the
  reader's teams, and refuses another team's key sent by hand. A user
  may belong to several teams; leaders see their team's records;
  superusers and holders of `generic_teams.see_every_team` see
  everything. `scope_to_teams()`, `teams_of()`, `leaders_of()` and
  `in_teams_of()` serve a project's own views. `scope_relations =
  True` gives forms the same narrowing for any resource that restricts
  its rows. See docs/teams.md.
- Numbering, `generic.numbering`: numbers such as `LEG-CTR-2026-0001`
  from a `Pattern`, each given once however many requests ask at the
  same time (`allocate()`, `peek()`, `generic.Sequence`,
  migration `generic 0017`). See docs/numbering.md.
- A trash: `trash = True` on a resource moves deleted records to a
  trash (the `Trashable` mixin) instead of deleting them. A *Trash*
  page restores them or deletes them for good; the `empty_trash`
  command and the `generic.empty_trash` task delete what is older than
  `TRASH_DAYS` (30). See docs/trash.md.
- An access log: `access_log = True` on a resource records who opened
  which record and who downloaded which file (`generic.access`,
  migration `generic 0018`), shown under *History › Access log* and
  linked from the record's page. `ACCESS_LOG_RETENTION_DAYS` and
  `generic.access.prune()` keep it bounded.
- Sign-in lock: after `LOGIN_MAX_ATTEMPTS` (5) failed passwords for
  one account or from one address, the sign-in page refuses it for
  `LOGIN_LOCKOUT_MINUTES` (15). Counted in Django's cache, so a
  production with several processes needs a shared cache (Redis).
  `None` turns it off.
- Several wikis. A `Wiki` model groups pages under their own menu:
  `wiki/` lists the wikis, `wiki/<wiki>/<page>/` is a page, and
  `wiki/api/wikis/` manages them under the `add/change/delete_wiki`
  permissions (migrations `0004` to `0006`). `GENERIC["WIKI_ACCESS"]`
  narrows which wikis a user reads, everywhere at once (pages, search,
  dashboard, PDF); `GENERIC["WIKI_EDIT_ACCESS"]` narrows which they
  write in; `Wiki.objects.readable_by()` and `writable_by()` apply
  them.
- A wiki downloads as a PDF, `wiki/<wiki>/export.pdf`: a cover, a
  table of contents, every page in menu order, uploaded images
  embedded and files listed. Written with fpdf2 (pure Python, in the
  `wiki` extra); `WIKI_PDF_FONTS` chooses the fonts.
- Files in the wiki: the editor's paperclip, a drop or a paste uploads
  files into a page, each a block linking to its download
  (`generic_wiki.WikiFile`, migration `0003`, `POST
  api/generic/wiki/files/`, `GET wiki/files/<id>/` always as an
  attachment). Images dropped or pasted are uploaded too. The
  toolbar's arrows (Alt+Up / Alt+Down) move a line, an image or a file
  up and down the page, and a page lists its attachments under its
  text and in its API.
- Resources: `form_extra_fields`, questions a form asks that the model
  does not keep (a change note), handed to `save_model` as
  `serializer.extra_values`; `get_download_name()`, a file downloaded
  under another name than the stored one; `may_download(request, obj,
  field)`, to refuse one file field; `list_display_hidden`, columns a
  table starts without, still offered by the column selector;
  `has_record_action(request, obj, name)`, so a record's page offers
  only the actions that apply to it.
- `@action(help=...)`: a sentence saying what the action does, the
  tip of its button. `@display(icons=True)`: a column of icons one
  clicks, shortcuts of the row (preview, download...).
- A bulk action may open a page of the site by returning
  `{"redirect": "/path/"}`; another site's address is refused. See
  docs/sites.md.

### Changed
- Pages take the window's full width. A project may still cap them
  with `--content-max-width` (it was 1600px).
- A wiki page's address holds its wiki: the route `generic_wiki:page`
  takes `wiki` and `slug`, and a page's slug is unique within its
  wiki. Existing pages move into a first wiki, `main`, and their old
  addresses redirect; code linking to a page should use
  `page.get_absolute_url()`.
- On a summary page, cards side by side start at the same height, and
  switching tabs no longer scrolls the page back up.

## [1.2.0] - 2026-09-27

### Added
- Files in the generated forms. A model's `FileField` (or
  `ImageField`) is a chooser in its form: the current file linked with
  its size, *Choose a file* / *Replace*, *Cancel*, and *Remove* when it
  may be empty. The choice is checked in the browser against the
  field's extensions (`accept`, from its `FileExtensionValidator`) and
  `GENERIC["FILE_MAX_SIZE"]` (10 MB) before anything is sent, and
  checked again by the server. A form with a new file sends its usual
  JSON as a `_payload` part beside one part per file
  (`generic.api.parsers.MultiPartJSONParser`); without one, it sends
  JSON as before, and classic multipart still works for scripts.
- A record's files download through
  `api/<app>/<model>/<pk>/files/<field>/`, never from a public
  `MEDIA_URL`: the record's view permission and row restrictions apply,
  and only the file fields the resource shows that reader are served. A
  raster image (PNG, JPEG, GIF, WebP) is shown; anything else - HTML and
  SVG first - is downloaded, and every answer carries
  `X-Content-Type-Options: nosniff` and `Content-Security-Policy:
  sandbox`. A file reads as `{"name", "url", "size"}` in the record, a
  table cell (`FileColumn`) and the summary page; exports write its
  name. Replaced and removed files are kept: the history points at
  them. File fields are refused in `editable_fields` and imports, and
  read-only in inline rows. `generic.W010`: files are stored and
  `MEDIA_ROOT` is empty.
- Images in the wiki: the editor's *Insert an image* uploads a PNG,
  JPEG, GIF or WebP - checked by its bytes, not its name; never SVG -
  for whoever may add or change pages (`api/generic/wiki/images/`),
  shown to the wiki's readers from `wiki/images/<id>/`. A new model,
  `generic_wiki.WikiImage`, and its migration.
- `generic.logs`: logs a production can read, and errors somebody hears
  of. `logging_config()` logs to standard output and, when asked, to a
  file rotated by size that the web server, a Celery worker's children,
  the scheduler and `manage.py` share without losing a line
  (`SharedRotatingFileHandler`). Every unexpected error goes by mail,
  with its traceback, to `ADMINS` when `DEBUG` is off - the same error
  once per `ERROR_MAIL_INTERVAL` (ten minutes), the next mail counting
  the ones held back, and a mail that cannot leave never raised into
  the failing request (`ErrorMailHandler`). `admins()` writes `ADMINS`
  the way the running Django reads it. `generic.W009` (`check
  --deploy`): `ADMINS` is empty. See docs/logging.md.

### Fixed
- The sign-in pages, and the last page of a popup form, name the site's
  icon like every other page; the browser no longer asks for a
  `/favicon.ico` nobody serves. The icon is one include,
  `generic/includes/favicon.html`, for a project to override once.
- The history no longer shows a decimal that did not change. A value
  set by code without its places - `Decimal(2)` in a field of two - was
  kept as `2`, read back as `2.00`, and listed as "2.00 -> 2.00" at the
  next save of anything else.
- *Mark all as read* works, in the bell and on the notifications page:
  its endpoint was looked up by a route name DRF never gave it.
- A classic multipart create or update - a form posted with its files -
  no longer receives every value as a list, and an `ImageField` is
  described as an image rather than a file.
- The checks' hints and the error messages no longer say `pip install
  django-generic[...]`: that name on PyPI is an unrelated package. They
  name the extra, and docs/installation.md installs the framework from
  a wheel built from its repository.

## [1.1.0] - 2026-09-26

### Added
- `generic.search`, an optional app: every text match the framework
  makes - the table search, column filters, the filter editor, the
  command palette, the autocompletes, classic list views, the wiki and
  data resources - sets accents aside as well as case, so `societe`
  finds *Société*. PostgreSQL through `unaccent` (its migration creates
  the extension and an indexable wrapper), SQLite through a Python
  function of the same name, other databases untouched.
- `generic.search.operations.CreateSearchIndex`: a GIN trigram index on
  exactly the expression a search compiles to, built on PostgreSQL and
  skipped elsewhere.
- Imports: `imports = Import(fields=..., key=...)` on a resource gives
  its list an *Import* button and a page to choose an Excel or CSV
  file, match its columns, preview what would be created, updated or
  refused - by row and column - and import, all or nothing. Headers,
  choices, relations and dates are read as the exports write them, so
  an export imports back unchanged. Endpoints `import/schema/`,
  `import/template/` and `import/`; hooks `clean_import_row` and
  `save_import_row`; settings `IMPORT_MAX_ROWS`,
  `IMPORT_MAX_FILE_SIZE`, `IMPORT_PREVIEW_ROWS`; the `import` extra.
- `generic.testing.PageSweep`: a project's `tests/test_pages.py` in about
  ten lines - every page opened by a superuser (in each of
  `languages`), a user allowed nothing and a stranger, and every
  generated endpoint behind them: rows, form schema, summary, history,
  each column's values, exports, charts, imports, transitions, the
  OpenAPI description. The framework's own screens get their records
  from the base class; a page whose address nothing fills is named.
  The framework's suite runs on it, and `scripts/smoke_install.py
  --sweep` runs it from the wheel.
- State machines: `transitions = ("status",)` on a resource offers
  each django-fsm-2 `@transition` of that field as a button on the
  record's page - only from the states it leaves, only to a reader
  allowed to take it - as a bulk action on the list
  (`transition:<name>`, rows it cannot move skipped and counted), and
  as `<pk>/transitions/<name>/` (403, 404, 409 when the record has
  moved, 400). Label, icon, confirmation, variant and fields to ask
  for come from the transition's own `custom`; the state is read only
  in forms, grids and imports; the history names the transition.
  `Generic.dialogs.fields()` asks a few values at once. The `fsm` extra.
- The API for scripts. `generic.tokens` (on django-rest-knox,
  its hashing, in a table of its own): personal tokens made
  on the account page and shown once, read only or read and write, with
  an expiry and their last use; an *API tokens* screen under People to
  revoke anyone's; `generic.tokens.authentication.TokenAuthentication`.
  `generic.openapi` (on drf-spectacular): `api/schema/` and `api/docs/`
  describe every generated endpoint as it behaves - the DataTables
  envelope and its filter tree, charts, actions, exports, imports -
  listing only what the reader may use, Swagger UI served from the
  sidecar's files. Checks `generic.E006`, `W008`, `E008`;
  settings `API_TOKEN_*`; the `api` extra.
- Scheduled mailings (`generic.mailings`): *Send by e-mail on a
  schedule* in a list's Views menu sends the table as it is - filters,
  search, columns, order - as Excel or CSV, daily, on weekdays, weekly
  or monthly, to people and groups. Each recipient gets the rows they
  may see, computed as them through the resource's own export, in
  their language. A dispatcher task (`generic.send_scheduled_mailings`,
  or `manage.py send_scheduled_mailings` from cron) claims each due
  mailing once; one that no longer works pauses and tells its owner.
  Behind `generic.add_scheduledmailing`; `ModelResource.mailing`,
  `SHOW_MAILINGS`, `MAILING_MAX_ATTACHMENT_SIZE`;
  `generic.delivery.mail_with_attachment`.
- `generic.sites.realtime.batch(resource)`: every change made in a
  block announced as one `bulk` event.
- `ModelResource.search_rank`: the command palette and the
  autocompletes list the closest match first (`pg_trgm`); `generic.W007`
  when the app is missing.

### Fixed
- A record's summary page no longer throws `GenericDataTables.start is
  not a function` and leaves its first related tab empty when Alpine
  shows the tab before the tables' script has loaded: the tab waits
  for the new `generic:datatables-loaded` event.
- Exports and forms speak each request's language. Column titles and
  form sections were turned into text when a resource's serializers
  were built - once per process - so every export and form after the
  first request kept that request's language.
- An account page shown to nobody - the API description, written with
  no request - no longer fails asking an anonymous user for a password.
- A JSON field of an add form takes its value from the address
  (`?state={...}`) as JSON rather than as text.

## [1.0.0] - 2026-09-25

The first official release: an admin-like application framework for
Django, driven by the REST API. Declare a model once and get its
screens; everything below is included.

### Declaring screens
- `ModelResource` and `@register`: from one declaration, a model's list
  page, summary page, add and change forms, delete page, REST endpoint,
  navigation entry and command palette results. Attributes and hooks
  keep the admin's names - `list_display`, `search_fields`,
  `fieldsets`, `inlines`, `actions`, `@display`, `get_queryset`.
- `auto(Model, related=(...))` and `AutoResource`: the resource worked
  out from the model - columns, search, coloured choices, a form two
  fields a row, related tables and form tabs - anything declared
  winning.
- `DataResource` and `@register_data`: rows that are in no table - an
  external API's answer - listed, filtered, searched, sorted, counted
  and exported like a model's, with a page per row, read only;
  `RelatedRows` and `RowLink` tie data resources together.
- Pages of a resource's own, `@page` and `ResourcePage`: a map, a
  timeline, a report, a JSON feed - any content, mounted at the
  resource's address, guarded by its permissions, the record found
  through its queryset, drawn in the frame and offered where it belongs.

### Tables
- DataTables driven by the server: pagination, multi-word search with
  exclusions and phrases, multi-column ordering, a column picker, saved
  views and presets, Excel and CSV exports of every filtered row, copy
  and print.
- Filters as chips: every operator per type, relative dates, groups of
  *all* and *any*, the values of a column offered with their counts,
  typed as `status:open hours:>2` in the search box or in a row of
  fields under the headers, kept in the address. The filter editor
  applies as it changes.
- Columns declared once on the serializer drive the configuration, the
  filtering and ordering whitelists and the export: text, numbers,
  decimals, booleans, dates, choices, relations and coloured tags.
- Bulk actions on a selection or on every filtered row, a row menu, and
  tables that refresh themselves when their rows change.

### Editing in place
- Editable cells, fields of a related model included, written through
  the endpoint with the related model's own permission.
- Grids: a table in which every writable cell is a control, rows added
  on top; declared grids over any set of records, shown by `GridView`.

### Forms
- Forms drawn from a JSON schema of the serializer: fieldsets, tabs,
  collapsed sections, read-only values, Select2 relations fed by
  autocomplete endpoints, popups to create or edit the related record.
- Tabular and stacked inlines, saved with the record in one
  transaction, and a deletion preview that says what goes with a
  record, or why it cannot go.

### Summary pages and charts
- A record's summary: figures, sections of typed values linking to the
  related records, and a tab per related table - the related model's
  full table narrowed to the record.
- Charts declared on the resource, computed by the database under the
  table's filters, drawn with Apache ECharts in the page's colours, on
  the list, the summary, the dashboard or any template.

### Real time
- Events over WebSocket with Django Channels, keeping open pages up to
  date: topics, and permissions per topic.
- Notifications for everything addressed to a person - the bell, the
  notifications page, a toast on every open page - and e-mail, as each
  person chooses; every e-mail addressed to its reader alone.
- Messages: *People › Messages* tells some people, some groups or
  everyone something, as a notification or an e-mail; the list records
  who sent what to how many and how many read it, and deleting a
  message withdraws it.
- Watching a record or a whole model, told by notification or e-mail,
  as each user chooses.
- Planned restarts announced to everyone connected, three warnings,
  then the restart.

### Records over time
- A version of every record of every registered model, read back by a
  History tab: who changed what, when, from what to what.
- Declared background tasks with their runs and results, and the Celery
  Beat schedules as ordinary screens.

### People and access
- Users, groups and permissions as screens, refusing any grant the
  person granting does not hold.
- Model permissions checked by the resource and enforced by the
  endpoint; clients send public column names, never ORM paths.
- Single sign-on providers offered on the sign-in page, the protocol
  left to the project's own library.

### The frame
- One frame for every page: collapsible navigation, top bar, command
  palette, breadcrumbs, a toolbar folding into a menu, toasts, dialogs.
- Colours computed from five parameters in OKLCH, light and dark
  themes, and per-user appearance: accent, contrast, colourfulness,
  tint and table stripes. The interface is sized in rem throughout and
  follows the browser's text size and zoom.
- A wiki with an editor, history and pages pinned to the dashboard; a
  help page reading the project's own licence and changelog.
- Classic server-rendered views - list, detail, forms, delete - for
  pages that want no JavaScript.

### Languages
- English and French, for the framework's pages and its JavaScript; a
  language menu and a per-user preference.

### Installation
- `pip install django-generic`: the core needs only Django and Django
  REST framework; the rest comes as extras. The package carries its
  templates, static files - every library vendored, no CDN, no build
  step - translations and changelog.
- `manage.py check` names what a project's wiring is missing or has out
  of place - the `request` context processor, a middleware, session
  authentication for the API, the site's URLs - with the line to write.
- The site may be mounted under a prefix in a project whose root is
  taken; without the `events` extra, the pages open no WebSocket.

### Deployment
- An example project with development and production settings, Docker
  images and Compose stacks for both, Daphne behind Caddy, Postgres,
  Redis, and Celery workers.
- Requires Python 3.10 or later, Django 5.2 or later and Django REST
  framework 3.16 or later. Extras: `export`, `events`, `tasks`, `beat`,
  `wiki`, `postgres`, `dev`.
