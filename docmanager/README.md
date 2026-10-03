# The document manager

django-generic as a document management system (a GED): teams, each
with its own folders and documents, and every file a document has had
kept as a version - who sent it, when, why, its size and checksum.
Plus the wiki. A project of its own, like the [minimal
example](../minimal/README.md): one settings file, plain WSGI, SQLite.

```
docmanager/
├── manage.py
├── docsite/
│   ├── settings.py     generic.teams and generic.wiki installed, MEDIA_ROOT
│   ├── urls.py         jsi18n/, api/generic/, wiki/, the site last
│   └── wsgi.py
└── documents/
    ├── models.py       Folder (a team's), Tag, Document, DocumentVersion
    ├── resources.py    the screens, each scoped to its team (team_field)
    ├── versions.py     how a version is recorded, numbered and restored
    ├── merge.py        Word files merged with a template (python-docx)
    ├── merging.py      the Merge Word files page: what may be merged, and how
    ├── templates/documents/merge.html, static/documents/   that page
    ├── samples.py      small Word, PDF and text files for the demo
    └── management/commands/seed_documents.py
```

## Run it

From a checkout of the repository:

```bash
pip install -e ".[export,wiki]"
cd docmanager
pip install -r requirements.txt     # the Word merge
python manage.py migrate
python manage.py seed_documents
python manage.py runserver
```

Sign in at <http://localhost:8000/> - every password is `demo`:

| Account | Teams | Group | Sees |
| --- | --- | --- | --- |
| `admin` | - | superuser | everything |
| `manager` | - | Managers (`see_every_team`) | every team's documents; makes teams |
| `alice` | Legal, Engineering | Editors | both teams' documents |
| `bob` | Engineering | Editors | Engineering's |
| `carol` | Human resources | Editors | Human resources' |
| `viewer` | Legal | Readers | Legal's, read only |

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
- **Wiki.** *Wiki* in the navigation, as in every example.

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
- `@page` - the merge page, a page of the documents' resource with its
  entry in the navigation ([Pages](../docs/pages.md)).
- Everything else - lists, forms, files, related tables, charts,
  history, actions - is declared in `documents/resources.py` like any
  django-generic screen.

The Word merge is this project's, not the framework's:
`documents/merge.py` can be copied into any project that needs it.

## Its own repository

This folder is self-contained. To grow it into a project of its own,
copy it into a new repository and install the framework from its wheel
or as a git submodule ([Installation](../docs/installation.md)); for
production settings and Docker, follow the full example
(`example_project/`, `docker/`, [Deployment](../docs/deployment.md)).
