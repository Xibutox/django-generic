# The example project

A runnable support desk that exercises every feature, so you can click
through them rather than read about them. For the opposite - the
least a project needs, one model and the wiki - see
[`minimal/`](../minimal/README.md); for a document manager - teams,
folders, versioned files - [`docmanager/`](../docmanager/README.md).

```bash
python manage.py migrate
python manage.py seed_example
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and sign in. The dashboard shows the wiki
page pinned to it, then a *What to try* panel saying what each part
demonstrates.

`seed_example` builds a desk big enough for the summary pages to mean
something: 8 customers, 240 tickets, about 500 comments and 850 time
entries, a few wiki pages. Two large customers carry most of the
tickets. Running it again tops up what is missing and leaves the rest.

## Users

All three share the password `demo`. Throwaway local accounts.

| User | Holds | Use it to see |
| --- | --- | --- |
| `admin` | superuser | everything, including the Django admin at `/admin/` and the wiki editor |
| `viewer` | works tickets, comments and time entries; only views customers, teams, agents and tags | the same screens without the pencil and plus beside *Team*, read-only customers, a wiki to read but not edit |
| `guest` | nothing | an empty sidebar but for the dashboard and the wiki, and 403 on every resource page |

Signed out, any page redirects to the sign-in form.

Seeding sets the three passwords, which signs out any session open with
them.

## Layout

```
example_project/       the project: settings, urls, asgi, wsgi, celery
example/               the app
├── models.py          Customer, Team, Agent, Tag, Ticket,
│                      TicketComment, TimeEntry - declared by hand -
│                      and Supplier, Equipment, Maintenance - by auto()
├── resources.py       every resource: list, form, summary page and
│                      related tables, inlines, actions, presets,
│                      extra navigation links and the dashboard; the
│                      two auto() lines of the equipment; and the
│                      external services, a DataResource
├── external.py        a status API's answer: the rows of the external
│                      services, a list of dicts, cached a minute
├── pages.py           pages the resources declare beside the generated
│                      ones: the customer map, a ticket's timeline
├── serializers.py     hand-written declarations, for the classic pages
├── api.py             their viewsets and autocomplete
├── api_urls.py        their REST endpoints, under /api/
├── views.py           the classic generic views
├── urls.py            the classic pages, under /demo/
├── events.py          the topics clients may subscribe to
├── templates/example/ the dashboard and the classic pages
└── management/commands/seed_example.py
```

`resources.py` is the file to read first: it is everything the
generated screens are made from.

The models were chosen for coverage, not realism: between them they
need text, choices, booleans, decimals, floats, dates, timestamps, URLs,
nullable foreign keys, a many-to-many and child collections — and
records with many related records, which is what summary pages are for.

The delete rules are deliberate too. `Ticket.team` is `PROTECT`, so a
team with tickets cannot be deleted — that is the case the delete page
has to explain. `TicketComment.ticket` is `CASCADE`, so deleting a
ticket takes its comments — that is the case it has to preview.
`TimeEntry.agent` is `PROTECT`: an agent who logged time stays on the
record.

## What each page shows

| Page | Demonstrates |
| --- | --- |
| `/` | the dashboard: a pinned wiki page, four charts drawn with `{% generic_chart %}`, every resource the user may reach, what to try |
| `/example/ticket/` | the generated list: two charts following its filters, coloured tags for status, priority and tags, filters, search, views, exports, bulk actions, live updates, links to each ticket's customer and team |
| `/example/timeentry/` | hours by month, split billable or not, and by agent (the eight largest, the rest as *Other*) |
| `/example/tag/` | tags drawn with their own colours, a computed column returning tags, a colour picker in the form |
| `/example/customer/1/` | a summary page: figures, two charts of its related rows, values, and tabs for its ~80 tickets and ~300 time entries, each tab with its own charts |
| `/example/ticket/1/` | a smaller one: its time entries and comments, the ticket's bulk actions as buttons, and ten buttons in its header — more than fit, on purpose |
| `/example/team/1/`, `/example/agent/1/`, `/example/tag/1/` | a reverse foreign key, three related tables, a many-to-many seen from the other side |
| `/example/ticket/add/` | the generated form: fieldsets, a collapsed section, a *History* tab, Select2 relations |
| `/example/ticket/1/change/` | the same, with the comments as a tabular inline and a computed read-only value |
| `/example/team/1/change/` | a stacked inline: the team's agents as cards |
| `/example/ticket/1/delete/` | the cascade preview |
| `/example/team/1/delete/` | the protected case: refused, with the reason |
| `/wiki/` | the wikis - the desk's handbook and the infrastructure runbooks - each with its menu, pages, editor, history and PDF |
| `/account/` | profile, appearance sliders, preferences, what you watch, password |
| `/generic/historyentry/` | every recorded change, as an ordinary table |
| `/auth/user/`, `/auth/group/` | accounts and groups, as `admin` only |
| `/notifications/` | the notification history |
| `/example/equipment/`, `/example/supplier/` | pages nobody wrote: two `auto()` lines, the rest worked out from the models |
| `/example/equipment/1/change/` | a form laid out two fields a row, and the maintenance visits as a tab of rows — also worked out |
| `/data/services/`, `/data/services/paylane/` | rows that are in no table: an external API's answer, listed, filtered and exported, and a page per service, read only, with a tab of its incidents |
| `/data/incidents/inc-2050/` | a row of another data resource, reached from its service's tab and leading back to it |
| `/example/customer/map/` | a page of the resource's own, in the navigation: the customers on a drawing of France, then their table; `/example/customer/geojson/` the same as JSON |
| `/example/ticket/1/timeline/` | a page of each ticket, written as a view of its own and in each row's menu: everything that happened to it, in one column |
| `/data/services/paylane/runbook/` | a page of each row of a data resource: a long text the API answers on its own, fetched for that page only |
| `/demo/tickets/1/work/` | a grid over one ticket's hours: every writable cell a control, rows added on top |
| `/demo/triage/` | a declared grid over every open ticket, corrected many at once; `/demo/teams/<pk>/triage/` for one team |
| `/demo/` | the classic, server-rendered views, with their own feature guide |

## Things worth trying

**A file on a ticket.** Open ticket `SD-1000`: its *Description*
section links `customer-log.txt`, downloaded through the ticket's own
endpoint (`/api/example/ticket/<pk>/files/attachment/`), which checks
you may read the ticket. *Edit* it: *Replace* chooses another file -
a PDF, an image, a spreadsheet - shown with its size before you save;
*Remove* takes it away; a file too large, or of a kind the field does
not take, is refused before anything is sent. As `guest`, the same
download answers 403.

**A bill of materials.** *Manufacturing › Articles › Bill of
materials* is the tree of every product: unfold *BK-100 City bicycle*,
then its wheel, its hub, its axle - five levels, each fetched when it
is opened. Unfold *CB-900 Control cabinet* and its terminal rail: 1,200
terminal blocks, fifty at a time, with a search box at the top of the
level (`TB-07`). Open *WH-300 Wheel assembly*: its *Bill of materials*
tab, and *Where used* - both bicycles. Try to add a line putting the
bicycle inside one of its own spokes: the form refuses it.
*Article families* is the other shape, a model pointing at its parent.
`ArticleResource.trees` is the whole of it ([Trees](trees.md)).

**On a customer.** Open the largest one from the dashboard. The figures
sit on top, the values below — the account manager is a link to the
agent's own page. Switch to *Time spent*: that table starts only now,
and each row links to its ticket and its agent. Filter it, export it:
the file holds that customer's time only. In *Tickets*, press *Add*:
the form comes filled with the customer, and saving brings you back to
this tab.

**Charts.** On the ticket list, switch *Tickets opened* from weeks to
months. Click the *Closed* slice of the donut: the table filters on it,
and both charts redraw for what is left. Click a bar of *Tickets
opened*: the table narrows to that week *and* that priority. Show the
figures as a table, or download the image. Open your account page and
drag the accent colour: the charts follow, like the rest of the page.
On a customer, open the *Time spent* tab: its chart starts only then,
and a click on an agent's bar filters that tab's table.

**A header with too many buttons.** A ticket offers *Work on the
hours*, its customer, team and assignee, the knowledge base, two
external sites, *View on site*, *Delete* and *Edit* — ten with *Watch*.
They stay on one line: what does not fit is behind the **⋯** button,
folded from the end of the list, so *Delete* goes first and the
project's own links last; *Edit* never folds. Widen and narrow the
window and buttons come out of the menu and go back into it. On a phone
the header stacks: title, then *Watch*, **⋯** and *Edit*. The links are
`TicketResource.get_record_links`; each is offered only to whoever may
open what it leads to.

**The navigation, pinned or not.** Press the pin in the top bar, beside
the navigation's button: the page takes the whole width and the
navigation becomes a panel. Move the pointer to the left edge of the
window and it slides back out; move away and it goes. The button in the
bar opens it and keeps it open; the pin puts it back for good. The
choice is remembered in this browser and on your account — it is also
on the preferences page, under *Navigation*.

**Watching a ticket.** Open a ticket and press *Watch*, beside the
star. Change it in another tab — or let somebody else — and the bell
shows what happened. Press *Watch every record* on the ticket list
instead and you hear about every ticket created, changed or deleted.
*Watching*, in the account menu, lists both and is where you tick which
changes are worth a message and whether they arrive as a notification,
an e-mail, or only on the page you have open. Leave the channels empty
and each watch follows *Account settings › Notifications*. See
[Watching](watch.md).

**Tasks.** *Tasks* in the navigation (you are `admin`). The desk
declares one task, *Overdue ticket digest*: press **Run now** and watch
it announce itself in the bell, count what is late, and land on its own
run page with the steps it wrote and a line per team. *Runs* lists every
run; *Schedules* holds the nightly crontab the seed created for it,
where **Run now** starts it off schedule. Nothing is queued here —
there is no broker on a laptop, so the work happens in the process that
asked for it. See [Tasks](tasks.md).

**Operations.** *Support › Tickets*: tick a few tickets and run
**Check** from the selection bar (or from a ticket's page). It is done
in the request and answered with a card holding a section per ticket -
folded when nothing is wrong, open with the warning or the error
otherwise, each title leading to its ticket. *Support › Customers*:
tick some and run **Review**. That one runs in the background - a
thread here, since a laptop has no Celery worker - so the card first
says it is running, then turns into the report when it is done; the
bell has the notification, which leads to the run's page and the same
tree. See [Operations and reports](operations.md).

**Help and what changed.** *Help* in the account menu: the version, the
licence read from the project's own `LICENSE`, the keyboard shortcuts,
and the newest release. *What changed* lists every release of every
`CHANGELOG.md` found — this repository's, and any the application keeps
of its own. Add a line to `CHANGELOG.md` and reload the page to see it
appear; see [UI layer](ui.md#help-licence-and-changelog).

**A planned restart.** *Plan a restart* in the account menu (you are
`admin`, so you have the permission). Set an hour two minutes away,
leave *Manual operation* ticked, and announce it: a banner counts down
above every page, a toast marks the announcement, another arrives a
minute before, a red one ten seconds before. Untick the box and the
server restarts itself at the hour. See
[Planned restarts](maintenance.md).

**In French.** Open the account menu, top right: under *Language*, pick
*French*. The frame, the tables, the filter editor, the forms and their
errors are translated, and so is this application — its menu groups,
column titles, ticket states, charts and feature guide. The choice is
saved on your account, so it follows you to another browser. What stays
English is the seeded content itself: ticket titles, customer names,
tags. Note *Ouvert* for the ticket state against *Ouvrir* in a row menu:
the state carries a gettext context, see [Translation](i18n.md).

**Tags.** In the ticket list, status, priority and tags are coloured
tags. A tag with one colour is tinted and follows the theme; *billing*
and *security* have a background of their own. Edit a tag under
*Organisation › Tags* with the colour picker, save, and the ticket list
shows the new colours. The *Tags* filter still offers the tags through the
autocomplete.

**Filters, on the ticket list.** The header has one row of titles: hover
*Status* and press its funnel — the values come with their counts and
their colours; tick *Open* and *Pending*. The chip lands in the bar
above the table. Under the titles sits a row of fields: type `invoice`
under *Title*, `>=5` under *Estimated hours*, `30d` under *Due on*; pick
*Yes* under *Billable*. Each one is a chip too — remove one and its
field empties. The button beside *Filter* hides the row and brings it
back; on *Tags*, a dozen labels, it starts hidden. Press **F**, pick *Opened at*, choose *is in the last*
30 days. Type `team:fro` in the search box and take *Front office* from
the list, then `hours:>=2 ` — a space turns it into a filter too. With
several filters, switch *All of* to *Any of*; in the column picker, *Add
a group* holds conditions of their own. Right-click a customer name:
*only this value*, or *anything but*. Copy the address into another tab:
the same filters come back. The *Needs attention* view is a group
inside a filter.

**On the ticket list.** Search for `invoice !blank`. Hide a column with
*Columns*, save the layout under *Views*, mark it as your default and
reload. Try the *Open work* preset. Export to Excel: the file holds **every matching
row**, not the page on screen. Tick two rows and *Close* them.
Right-click a row for its menu; double-click opens its summary.

**Live.** Open the ticket list in two windows and edit a ticket in
one: the other refreshes by itself, and so does the ticket's summary
page if it is open.

**Messages.** As `admin`, open *People › Messages* and write one to the
*Read only* group, or to everyone: sign in as `viewer` in another browser
and it is in the bell, with a toast if the page was open. Back on the
message, *Read* counts who has opened it; deleting it takes it out of
every bell again.

*Real time › Live updates* shows what the connection behind every page
carries, each frame with what it made happen: send yourself a
notification and watch the bell hear of it; edit a ticket in another
window and watch the frame every open table refreshed on. None of it is
addressed to anyone - people are told things by notification.

The card under them is what a channel of the project's own is for: a
team's queue, counted live. `example/events.py` declares one channel
per team, open to its agents only, and publishes the team's count
whenever one of its tickets changes; the card subscribes and redraws.
Close a ticket of that team in another window and the number moves.
Signed in as `viewer`, who is on no team, the channel refuses the page
and says so.

**On the ticket form.** Press the pencil beside *Team*: the team opens
in a popup, and its new name comes back into the field when you save
it. The plus beside *Tags* creates one. Add a comment row, remove
another, and save once: both land in the same transaction. Ctrl+S
saves; leaving with unsaved changes asks first.

**On your account.** Under *Appearance*, drag the *Accent colour*
slider and watch the whole page follow; raise *Contrast* and *Table
stripes* until table rows stand apart; try *High contrast* or *Forest*.
Save, and the next page opens that way — on any browser you sign in
from.

**In the wiki.** As `admin`, edit a page: headings, lists, links,
quotes, code. *Insert an image*, then *Upload an image*: a PNG from
your disk lands in the page, and stays there when you save - a `.png`
that is really something else is refused. Drag a PDF from your desktop onto
the text: it lands there as a file block, and *How we triage* already
holds one. Put the cursor on a line and press Alt+Up or Alt+Down - or
the toolbar's arrows - to move it, a file or an image with it; once
saved, the page lists its attachments under its text. Save, then open *History*
and restore the earlier version — the text you replaced is kept too.
Pin a page to the dashboard. As `viewer`, the same pages are there to read, without the
buttons.

**Several wikis.** `/wiki/` lists two: the *Desk handbook* and the
*Infrastructure runbooks*. As `admin`, *New wiki* adds a third, the
pencil renames one; open one and its menu holds only its pages, with
the other wikis folded under its name. *PDF* downloads a wiki as one
document: a cover, a table of contents, every page in the menu's
order, the images drawn, the files named. The old address
`/wiki/triage/` still leads to the page, now `/wiki/main/triage/`.

**As `viewer`.** The pencil and plus beside *Team* are gone, and the
team list has no *Add*: the schema only offers what the permissions
allow, and the endpoint refuses the rest anyway. On a ticket's summary,
the customer is named but not linked if the customer page is out of
reach.

**Importing.** On the ticket list, press **Import**, then *Download a
template* - or export the list and drop the export back in: every row
comes back *unchanged*. Change a title and a status (in English or
French) in the file, add a row with a new reference, and drop it again:
the preview says one to create, one to update, and names any cell it
cannot read. As `viewer`, the button is not there.

**A ticket's life.** Open an open ticket: the buttons at the top are
what it can become - *Wait for the customer*, *Resolve* (which asks
for the resolution), *Close*. Resolve it: the buttons change, and its
History tab says *Transition: Resolve*. *Reopen* only appears to
whoever holds `example.reopen_ticket`. On the list, select tickets and
run *Close*: the ones already closed are counted as skipped.

**Mailing a list.** Filter the ticket list, open **Views** and choose
*Send by e-mail on a schedule…*: the form holds the list as you see
it. *Scheduled mailings* (Tasks group) already has *Open urgent
tickets* for `admin`; *Send now* on it, and the development stack's
worker log shows the e-mail and its attachment.

**From a script.** `seed_example` printed a read-only token for
`admin`: `curl -H 'Authorization: Token ...'
http://127.0.0.1:8000/api/example/ticket/?length=5`. Make others on the
account page (*API tokens*), and read what each endpoint takes at
`/api/docs/`. Signed in as `viewer`, the description lists only what
`viewer` may open.

**Everywhere.** Ctrl+K searches every page, record and wiki page.
Accents do not matter (`generic.search`): `region` finds *Région
Occitanie*, and `lefevre` finds the agent *Norah Lefèvre*.
*Watch* on a record tells you when it changes, and the arrow beside it
offers every ticket at once; both end up on the *Watching* page.

**On a ticket.** Open `/example/ticket/1/` and press **History**. The
seed works three tickets along as two different people, so the tab has
a story to tell: *Camille Rousseau* picked one up and raised its
priority, *admin* answered it and closed it. Each entry says what
changed, from what to what; *Show this version in full* has the whole
record as it stood. Then edit the ticket yourself and watch your own
name arrive at the top of the tab.

**On the sign-in page.** Sign out and look at `/login/`: the example
declares one provider, so a button leads and the password form is
folded underneath it. The button goes to a page of the example that
explains what a real provider would do — it signs nobody in. Open the
fold and `admin` / `demo` still works.

**On one ticket's hours.** Open `/demo/tickets/1/work/` — a page about
one ticket, showing its time entries, built for correcting them. Every
writable cell is already its control: the hours, the date, the note,
the agent and the ticket's *status* are edited where they are. That
last column is not the timesheet's at all — it closes the ticket from
here, and asks for the ticket's change permission rather than the
timesheet's. Type a silly number of hours to see a refusal land on the
cell.

Press **Add a row**: a draft opens on top, dated today, billable, with
no ticket column to fill in — it belongs to this ticket. Save it empty
and each required cell says so; pick an agent, type the hours, press
`Enter`, and the entry is logged. Widen the columns, narrow the window:
the grid scrolls inside its card, never the page.

The same entries are **read-only** on `/example/timeentry/` and in the
ticket's own *Time entries* tab: declaring what may be edited turns
nothing on, and those tables do not ask. The customer's *Time spent*
tab does ask (`RelatedTable(editable=True)`) — but adds no rows: its
entries reach the customer through their tickets, and a new one would
have no ticket.

**Pages nobody wrote.** *Equipment* in the navigation — suppliers and
the equipment bought from them — is two lines of `resources.py`:

```python
auto(Supplier, related=("equipment",), group=EQUIPMENT)
auto(Equipment, related=("maintenances",), group=EQUIPMENT)
```

Everything else comes from `example/models.py`. The list opens on the
name, then the serial number, the kind and the state as coloured tags,
the supplier and the agent as links; *Notes*, long text, is no column.
Search `Nordic`: the supplier's name is searched too. Open a laptop: its
fields, then its maintenance visits as a table. *Edit* it: two fields a
row, the notes the whole width, and a *Maintenance visits* tab where a
visit is added with the laptop, in the same save. Maintenance is
declared nowhere: its pages exist all the same, out of the navigation,
reached from the equipment. Try to delete a supplier: the equipment it
sold is `PROTECT`, and the delete page says so. See
[Pages from the model](auto.md).

**Rows from an API.** *Support › External services* lists the services
the desk relies on — e-mail, payments, telephony — as a status API
reports them. Nothing of it is in the database: `example/external.py`
stands for the API client and returns a list of dicts, dates as text, a
list of regions per service, `null` where there is nothing to say. A
`DataResource` in `resources.py` declares the columns and says where the
rows come from, and the rest is the table every model has: tick
*Major outage* in the status filter, look for services in *South Asia*,
sort by response time, those with no answer first when descending;
search `telephony`; export what is left. Open *Paylane*: its status and
figures on top, its description the whole width, its status page a
link. There is no *Edit* and no *Delete* — those rows are read, not
written.

Below them, the *Incidents* tab: the same API's other list, declared as
a second data resource and tied to the first with one line,
`RelatedRows("incidents", resource="incidents", field="service")`. It
is the incidents' own table, narrowed to Paylane — filter it by status,
export it — and each incident opens on its own page, whose *Service*
leads back to Paylane (`RowLink`). The incidents are not in the
navigation: like a maintenance visit, they are reached from what they
belong to.

The *Runbook* button of the same page opens what the desk does when
Paylane fails: a long text on a page of its own, read as prose, under
what is going wrong right now. The API answers it on its own
(`external.runbook_of`), so it is fetched when that page opens and never
with the list. See [Rows from elsewhere](data.md).

**Pages nobody generates.** Three resources have pages of their own,
declared on them and written in `example/pages.py` — whatever they
show, the framework gives them their address, their permission, the
record, the frame and a button:

- *Support › Customer map* draws the customers on a map of France —
  an SVG, no library — bubbles sized by their open tickets, coloured by
  segment; a bubble opens its customer. Below, the customers' own
  table, filters and exports included; beside, a link to the same data
  as GeoJSON, a page answering JSON rather than HTML. Both are `@page`
  methods of `CustomerResource`.
- A ticket's *Timeline* button — or the entry of the same name in each
  row's menu — shows everything that happened to it: opened, commented,
  hours logged, fields changed (read from its history), due. It is a
  view of its own, `TicketTimelineView`, declared with
  `ResourcePage("timeline", view=..., detail=True)`.
- A service's *Runbook*, above, is a `@page` method of a data resource.

Sign in as `guest`, who may see neither customers nor tickets: no
button, no navigation entry, and a refusal at the address. See
[Pages of a resource's own](pages.md).

**Triage: many tickets at once.** *Support › Triage* (`/demo/triage/`)
is a grid the ticket resource declares over a set it chooses — every
ticket still open — rather than one record's rows. Assign a batch,
change priorities and due dates down the column; the status and the
priority, drawn as coloured tags elsewhere, are selects here. The team
buttons narrow it to one team (`/demo/teams/<pk>/triage/`, the grid's
argument), and a row added there starts in that team, with the next
reference filled in. Close a ticket: it stays on screen until the grid
reloads, because the grid says which rows are shown, not which may be
written. `TicketResource.grids` and `example/views.py` are the whole
of it.

**On a customer.** Open `/example/customer/1/` and look at the tab bar:
six related tables and the history, more than it can draw. The ones
that do not fit wait behind the `+N` button at its end, and the button
says so when the tab you are on is one of them. Narrow the window and
watch the bar give tabs up one at a time. Three of those tabs — teams,
agents, subjects — are reached *through* the tickets, and each row
arrives once however many tickets it owns.

**On the dashboard.** The row of cards at the top is the hub: *Open
tickets* carries the count and opens the list already filtered to what
the desk has not answered, *Log a ticket* goes to the add form, and
under *Elsewhere* two cards leave the application — one to Django's
documentation, one to a `mailto:`. Sign in as `guest` and most of them
are gone: each card names the permission it needs.

**On the People screens**, as `admin`. The seed makes two groups:
*Desk agents*, which is what `viewer` belongs to, and *Read only*. Open
*Groups* and both say how many members and how many permissions they
carry; open one and its members are a tab. On an account, *New
password* is write-only — save the form and read the record back
through the API, and there is no password in it. Then sign in as
`viewer`: the People group is not in their navigation at all, and
`/auth/user/` answers 403.

**On the API.** These are worth pasting into the address bar:

```
/api/example/ticket/?draw=1&length=5&search[value]=invoice
/api/example/ticket/?draw=1&filters={"match":"any","conditions":[{"column":"priority","operator":"any_of","value":["urgent"]},{"column":"tags","operator":"empty"}]}
/api/example/ticket/facets/?column=team&q=fro
/api/example/customer/1/summary/
/api/example/timeentry/?draw=1&length=5&_related=example.customer.time_spent:1
/api/example/ticket/charts/opened/?period=month
/api/example/timeentry/charts/hours_by_agent/?_related=example.customer.time_spent:1
/api/example/ticket/form-schema/
/api/example/team/autocomplete/?q=fro
/wiki/api/pages/
```

## Vendored files

`generic/static/generic/vendor/` holds jQuery, DataTables, Select2,
Alpine.js, Quill, Apache ECharts and the Material Symbols font, each with
its licence.
The framework ships them, so nothing is fetched from a CDN and the
example runs offline. Quill's two files had their last line removed —
a `sourceMappingURL` comment naming a map that was never shipped —
since production collects the static files with hashed names, and that
refuses a reference to a missing file.

## Running it against Postgres and Redis

```bash
docker compose -f docker/docker-compose.dev.yml up --build
```

The same project and the same development settings, with
`DATABASE_URL` and `REDIS_URL` set, the source mounted so runserver
reloads, and the migrations applied on every start. After pulling new
code that changes the dependencies, add `--build`.

The production stack — Daphne behind Caddy, hashed static files,
secrets from the environment — is `docker/docker-compose.prod.yml`. Both
are in [Development and production](deployment.md).

`daphne` is listed first in `INSTALLED_APPS`, before `staticfiles`.
That is what makes `manage.py runserver` serve the WebSocket **and**
the static files. Without it, runserver is WSGI-only and every socket
is silently dropped — which is exactly what a "the events do not work"
bug report usually turns out to be.

## The Debug Toolbar

With the `dev` extra installed, the example turns on
[Django Debug Toolbar](https://django-debug-toolbar.readthedocs.io/)
by itself: a tab on the right edge of every page, closed until you
click it. It is in `example_project/settings/dev.py` and `urls.py`,
guarded by `DEBUG_TOOLBAR`, which is true only when

- the development settings are the ones running — production never
  installs it,
- the package is installed,
- no test runner is running,
- and the environment does not say `DEBUG_TOOLBAR=0`.

```bash
pip install -e ".[dev]"
```

What to look at here:

- **SQL** — the queries a page ran, with the duplicates flagged. A
  record's summary page is where a missing `select_related` shows.
- **History** — the requests since the page opened, the API calls
  among them. The tables, the charts, the forms and the summary refresh
  all go through `/api/`, so that is where most of the queries are:
  pick one in History and the other panels switch to it.
- **Templates** — which override of `generic/...` actually drew the
  page.

The toolbar shows for requests from this machine (`INTERNAL_IPS`). In
the Docker stack the browser reaches the container through the network's
gateway, which the toolbar's own Docker callback recognises; it is used
only when `/.dockerenv` exists, since outside a container it would let
in anything coming through the router.

It works under Daphne, the ASGI server the example runs on. A panel
the toolbar cannot run asynchronously shows unticked and greyed out.

## If the page loads with no styling

The symptom is a readable but completely unstyled page, and 404s on
everything under `/static/`. Two causes, both easy to tell apart:

**You ran an ASGI server directly.** `daphne example_project.asgi:application`
serves the pages but not the static files — an ASGI server has no
reason to. `example_project/asgi.py` wraps the HTTP half in
`ASGIStaticFilesHandler` when `DEBUG`, so this works with
`DJANGO_SETTINGS_MODULE=example_project.settings.dev`; if you copied an
earlier version of that file, that is what is missing. Without the
variable, `asgi.py` loads the production settings, which serve no
static files at all — Caddy does, in front — and refuse to start
without their secrets.

**The server predates a settings change.** `runserver` reloads Python,
but a change to `INSTALLED_APPS` needs a full restart. Stop it and
start again.

To check which, ask the server directly:

```bash
curl -I http://127.0.0.1:8000/static/generic/css/base.css
```

`200` with `Content-Type: text/css` means static serving is fine and
the problem is elsewhere. `404` means it is not being served at all.

A page that looks half-updated after pulling new code is usually the
browser's cache holding an older script: a hard reload (Ctrl+F5)
fetches everything again.

## Keeping it honest

`tests/test_example.py` renders the classic pages; `tests/sites/`
drives the generated pages, the summary pages and their endpoints
through the example's own resources; `tests/wiki/` covers the wiki. The
example is a deliverable: a reader copies from it, so a broken example
is a broken promise.
