# The document manager

django-generic as a document management system (a GED): teams, each
with its own folders and documents, and every file a document has had
kept as a version - who sent it, when, why, its size and checksum.
Documents numbered by each team's codification - with a file or not
yet - and taken through review circuits anyone may draw, each step
telling the people it asks, by notification and e-mail, and telling
whoever sent it and the team's leaders how it goes. Plus a wiki per
team, written by the teams that may, exported to PDF, and Word files
merged. A project of its own, like the [minimal
example](../minimal/README.md): one settings file, plain WSGI, SQLite.

```
docmanager/
├── manage.py
├── Dockerfile          gunicorn, and nginx in front (optional)
├── compose.yaml        docker compose -f docmanager/compose.yaml up
├── nginx/              HTTPS with a self-signed certificate, the static files
├── docsite/
│   ├── settings.py     generic.teams and generic.wiki installed, MEDIA_ROOT
│   ├── urls.py         jsi18n/, api/generic/, wiki/, the site last
│   └── wsgi.py
└── documents/
    ├── models.py       Folder (a team's), Tag, DocumentType, Codification,
    │                   Document, DocumentVersion, Comment, TeamWiki,
    │                   Workflow, WorkflowStep, Review, ReviewStep, ReviewTask
    ├── resources.py    the screens, each scoped to its team (team_field)
    ├── versions.py     how a version is recorded, labelled (0.1, 1.0, 1.1...),
    │                   published and restored
    ├── text.py         the text of a file, for the search (docx, pptx,
    │                   xlsx, odt... with the standard library; PDF with pypdf)
    ├── stamping.py     an approved PDF stamped on every page (fpdf2 + pypdf)
    ├── preview.py      the Preview page: PDF, images, Word (mammoth), text
    ├── periodic.py     reminders before a document's review date, and the
    │                   review started on the day (tasks.py, a daily task)
    ├── codification.py a document's number, from its team's pattern
    ├── workflows.py    the review circuits: steps, tasks, who is told what
    ├── merge.py        Word files merged with a template (python-docx)
    ├── merging.py      the Merge Word files page: what may be merged, and how
    ├── wikis.py        who reads and who writes which wiki
    │                   (GENERIC["WIKI_ACCESS"], ["WIKI_EDIT_ACCESS"])
    ├── templates/documents/merge.html, static/documents/   that page
    ├── samples.py      small Word, PDF and text files for the demo
    └── management/commands/   seed_documents, run_periodic_reviews,
                               extract_text
```

## Run it

From a checkout of the repository:

```bash
pip install -e ".[export,wiki]"
cd docmanager
pip install -r requirements.txt     # Word merge, PDF text and stamps, preview
python manage.py migrate
python manage.py seed_documents
python manage.py runserver
```

Already ran it? `git pull`, `pip install -e "..[export,wiki]"` from
this folder, then `migrate` and `seed_documents` again: what is there
stays, what is new is added (types, numbers, workflows, reviews,
subfolders, periodic reviews). `python manage.py extract_text` reads
the text of files sent before the search inside files existed.

Each of `requirements.txt`'s libraries is optional: without `pypdf`,
PDFs are neither searched nor stamped; without `mammoth`, a Word
preview shows its paragraphs only.

The e-mails of the reviews are printed in the terminal running
`runserver` (Django's console backend): set `EMAIL_BACKEND` - or
`MAILERS` from Django 6.1 - to a real server to send them.
`DOCUMENT_REVIEW_CHANNELS` in `docsite/settings.py` says where they go:
`["notification", "mail"]`.

Sign in at <http://localhost:8000/> - every password is `demo`:

| Account | Teams | Group | Sees |
| --- | --- | --- | --- |
| `admin` | - | superuser | everything |
| `manager` | - | Managers (`see_every_team`) | every team's documents; makes teams, types, numbering |
| `alice` | Legal (leader), Engineering | Editors | both teams' documents |
| `bob` | Engineering (leader) | Editors | Engineering's |
| `carol` | Human resources (leader) | Editors | Human resources' |
| `viewer` | Legal | Readers | Legal's, read only |
| `quentin` | - | Quality (a role) | only what a review asks of him |

Waiting for them when they sign in: `quentin` has two tasks (the NDA's
review, the release procedure's approval), `carol` one (the welcome
guide), and `manager` will sign the NDA off once Quentin has read it.

### In Docker, behind nginx over HTTPS

From the repository's root, with Docker (Docker Desktop on Windows or
macOS):

```bash
docker compose -f docmanager/compose.yaml up --build
```

Then <https://localhost/>, the same accounts. Two containers:

- `web`: the document manager run by gunicorn, `DEBUG` off. Each start
  runs `migrate` and `seed_documents`, which leaves alone what is
  already there. The database and the documents' files are in the
  `data` volume.
- `nginx`: HTTPS, with port 80 redirected to it, the static files
  (collected into the image), and the rest handed to gunicorn. The
  documents' files are not among what it serves: Django sends each one
  through its record's endpoint, to who may see it.

The certificate is signed by nginx itself on its first start
(`nginx/10-self-signed.sh`) and kept in the `certs` volume: the
browser warns once - *Advanced* > *Continue to localhost* - and not
again. Nobody vouches for it, which is all a site on this machine or a
local network needs.

| Variable | Default | |
| --- | --- | --- |
| `HTTP_PORT`, `HTTPS_PORT` | `80`, `443` | the ports on this machine, if those are taken |
| `SERVER_NAME` | `localhost` | the machine's name on the network, put in the certificate |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | the names the site answers to |
| `DJANGO_SECRET_KEY` | a fixed one | |

Set them in a `.env` file beside `compose.yaml` - `docmanager/.env`,
which git ignores - on Windows as anywhere else:

```ini
# https://localhost:8443/, ports 80 and 443 being taken
HTTP_PORT=8080
HTTPS_PORT=8443
# Reached from the network as https://srv-docs/
SERVER_NAME=srv-docs
DJANGO_ALLOWED_HOSTS=srv-docs,localhost,127.0.0.1
```

`docker compose -f docmanager/compose.yaml down -v` starts over: the
database, the files and the certificate. After a change to
`SERVER_NAME`, this or removing the `certs` volume alone
(`docker volume rm docmanager_certs`) signs a new certificate.

A certificate of your own instead: copy `server.crt` and `server.key`
into the `certs` volume, and nginx serves them. The e-mails of the
reviews are in `docker compose -f docmanager/compose.yaml logs web`.
Like the demo it starts, this is for a machine or a local network,
not the internet: its secret key and passwords are public.

## Things to try

- **Teams.** Sign in as `bob`, then as `alice`: the same lists, not the
  same rows. Bob's *New document* offers only Engineering's folders,
  and the API refuses another team's folder sent by hand. *People ›
  Teams* is where `manager` says who is in which team.
- **A document and its versions.** *Documents › Add*: a title, a
  folder, a file and a change note make version 1. Open it, *Edit*,
  *Replace* the file and write why: version 2. Its *Versions* tab lists
  them all, each downloadable under the name it was sent with; *Add*
  there sends a new one too. Select an old version and *Restore*: it
  becomes the current file again, as a new version - nothing is ever
  overwritten.
- **History.** A document's *History* tab says who changed what and
  when; its versions say which file.
- **Review.** *To review* in the list's views, *Approve* as a bulk
  action, the *Documents in review* card on the dashboard, the charts
  above the list.
- **Formats.** The list's *Format* column filters on `DOCX`, `PDF`,
  `MD`...; the search finds them too (type `pdf`), and *Word files* in
  the list's views keeps Word documents and templates only - in the
  *Versions* list as well.
- **Merging Word files.** Select documents in the list - or versions
  in *Versions* - and choose *Merge into Word*: the *Merge Word files*
  page opens with them, also in the navigation. Put them in order, add
  others, choose a template (*Letter template* holds a `{{ documents }}`
  line: the files go there, between its own text) and *Merge and
  download*. Or choose a folder under *Keep it as a new document in*:
  the merged file becomes a document of its own, at version 1. Only
  Word files (`.docx`, `.dotx`) of the reader's teams are offered or
  accepted.
- **A wiki per team.** *Wiki* in the navigation lists the wikis the
  reader may read: *Company*, everyone's, and their teams' handbooks -
  `bob` sees *Engineering handbook*, never *Legal handbook* (its pages
  and its PDF answer 404). *PDF* on a wiki downloads it whole. *People
  › Team wikis* is where `manager` says which wiki is which team's and
  which teams write in it: *Company* is read by everyone and written
  by Human resources only - `bob` reads it without *Edit*, `carol`
  edits it. A wiki with no editing team is written by whoever reads it
  (with the page permissions); an editing team reads the wiki it
  writes in. Administrators and `manager` write everywhere.
- **Numbers.** Every document has its team's number: `LEG-CTR-2026-0001`
  for a Legal contract, `ENG/PRC/00001` for an Engineering procedure,
  `HR-2610-001` for Human resources (*Settings › Codifications*, where
  `manager` changes a team's pattern and sees its next number;
  *Settings › Document types* give the `{type}`). Legal numbers every
  new document; elsewhere tick *Give it its number now* in the form,
  or select documents and *Codify*. A document needs no file for it:
  *Supplier contract 2027* is a number reserved for a contract not
  written yet - *Without a file* in the list's views. A number never
  changes; each series counts on its own, from 1 again each year when
  the pattern holds `{year}`.
- **Review circuits.** *Reviews › Workflows* lists the circuits:
  *Quick approval* (the team's leaders approve), *Contract review*
  (Victor and the *Quality* role review - each of them - then the
  manager signs off), *Procedure validation* (leaders review, quality
  approves, the whole team reads). Anyone may draw their own: steps in
  order, each asking to **review**, **approve** or **read**, its people
  being named people, groups (roles), the team's leaders and/or
  members, answered by one of them or each of them, with days to
  answer.
- **Sending a document.** Select one and *Send for review* (also on its
  page): choose a workflow - or none, and draw the steps right there -
  write a message, *Start now*. Its steps are copied: changing them in
  the review never changes the workflow. Untick *Start now* to prepare
  it and *Start* it later.
- **Tasks.** Each person asked gets a notification and an e-mail
  linking to their task; *My tasks* (dashboard, and the *Tasks* list's
  views) lists them. *Answer* on a task: approve - reviewed, read - or
  reject, with a comment, or hand it to someone else. *Approve* and
  *Reject* also work on several tasks at once. Sign in as `quentin`:
  he is in no team, yet opens and downloads the two documents he is
  asked about - and nothing else.
- **Progress.** At each step, whoever started the review and the
  team's leaders are told what happened and where it stands ("now at
  step 2 of 2, Sign-off - waiting on Maria"). The review's page shows
  its steps and tasks; the document's *Reviews* tab, each circuit it
  went through. The document is *In review* while it runs, *Approved*
  at the end (when a step approved it), *Draft* again when rejected.
- **Nothing blocks.** A step nobody can answer is skipped. The file may
  be replaced during a review. The starter, the team's leaders and
  the managers may answer for someone, *Skip the current step*, add a
  step in its *Steps* tab (whoever it names is asked at once if it is
  running), *Remind* those who have not answered, or *Cancel the
  review*. *Approve* on the documents list still approves without a
  circuit.
- **Check-out.** *Check out* says you are working on a document - the
  *Checked out* view lists them - without stopping anyone: whoever
  sends a version meanwhile is let through and the holder is told;
  *Check in* gives it back, anyone may.
- **Search inside files.** The list's search reads the files' text
  too: search `Signed version` as `alice`. Word, PowerPoint, Excel,
  OpenDocument, text and PDF files are read when they are sent.
- **Published and working versions.** Versions are labelled `0.1`,
  `0.2` while a draft, `1.0` once approved, then `1.1` for the next
  draft and `2.0` at the next approval. Readers who change nothing
  (`viewer`) read the published version only - its file, its preview,
  its row in *Versions* - while the authors work on the next; someone a
  review asks reads the draft too. An approved PDF is stamped on every
  page with its number, version, date and approvers (*Release
  procedure*'s *Published file*).
- **Preview.** *Preview* on a document's page (or its row's menu)
  shows the file in the page: PDF and images as they are, Word as
  text, text files as text.
- **Shortcuts.** The list's *File* column has two icons on each row:
  the eye opens the preview - where the format is one the page shows -
  and the arrow downloads the latest version its reader may read: the
  working file for its authors, the published one for everyone else
  (`@display(icons=True)`). The reviews and the tasks carry the same
  two icons for their document, and each version its own preview and
  download, so nobody opens a page to find a button. A file's name is
  text in the tables: the icons are how it is opened.
- **Trash.** Delete a document: it goes to the *Trash* page of the
  list, its open review is cancelled, and *Restore* brings it back.
  Older than 30 days, `python manage.py empty_trash` deletes it for
  good.
- **Access log.** A document's *Access log* link says who opened it,
  previewed it and downloaded which file.
- **Folders in folders.** A folder's *In folder* puts it inside another
  of its team's (*Contracts / Suppliers*); its documents are found by
  the whole path.
- **Periodic reviews.** A document type reviewed every so many months
  (*Procedure*: 12) sets an approved document's next review date. Run
  `python manage.py run_periodic_reviews` (or the *Periodic reviews*
  task, daily): the authors and team leaders are reminded 30 days
  before (*Release procedure* is due in 10), and on the day the type's
  workflow starts on its own.
- **Also.** *Comments* on a document's page, *Related documents* in
  its form, a *Next review on* date (the *Due for a review* view), a
  *Make obsolete* action, *Not numbered* and *Without a file* views.

The files are under `media/` beside `manage.py` (`DJANGO_MEDIA_ROOT`
moves them), served only through the API, to who may read the
document.

## On generic

What the framework gives this project, and where to read about it:

- `generic.teams` - teams, and `team_field` on a resource
  ([Teams](../docs/teams.md)).
- `form_extra_fields` - the change note, asked by the form and never
  stored on the document ([Forms](../docs/forms.md#questions-that-are-not-fields)).
- `get_download_name` - a file downloaded under the name it was sent
  with ([Forms](../docs/forms.md#the-download)).
- An action returning `{"redirect": ...}` - *Merge into Word* opening
  the merge page with the selection ([Sites](../docs/sites.md#selection-and-bulk-actions)).
- `GENERIC["WIKI_ACCESS"]` and `["WIKI_EDIT_ACCESS"]` - the teams'
  wikis, who reads and who writes them, `documents/wikis.py`
  ([Wiki](../docs/wiki.md#who-sees-which-wiki)).
- `generic.numbering` - the documents' numbers, each series counting
  on its own under a lock ([Numbering](../docs/numbering.md)).
- Team leaders - `Team.leaders`, `leaders_of()`: told how reviews go,
  asked as a step's people ([Teams](../docs/teams.md#team-leaders)).
- `generic.delivery.deliver` - the reviews' notifications and e-mails,
  each in its reader's language ([Events](../docs/events.md)).
- `trash`, `access_log` and `may_download` - deleted documents kept to
  be restored, who opened and downloaded what, drafts kept from
  readers ([Trash and access log](../docs/trash.md)).
- `@page` - the merge page, the preview, a page of the documents' resource with its
  entry in the navigation ([Pages](../docs/pages.md)).
- Everything else - lists, forms, files, related tables, charts,
  history, actions - is declared in `documents/resources.py` like any
  django-generic screen.

The Word merge and the review circuits are this project's, not the
framework's: `documents/merge.py` and `documents/workflows.py` can be
copied into any project that needs them.

## Its own repository

This folder is self-contained. To grow it into a project of its own,
copy it into a new repository and install the framework from its wheel
or as a git submodule ([Installation](../docs/installation.md)); for
production settings and Docker, follow the full example
(`example_project/`, `docker/`, [Deployment](../docs/deployment.md)).
