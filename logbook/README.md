# The logbook

django-generic as a planner merged with a note-taking app and a time
tracker - simpler than a project planner, with the notes where the work
is decided and the hours where it is done. A project of its own, like
the [minimal example](../minimal/README.md): one settings file, plain
WSGI, SQLite.

- **Notes**, written line by line as in a notebook: text, headings,
  bullets, check boxes - and **task lines**. Type `/fnc `, `/dm ` or
  `/aut ` at the start of a line (or pick the kind in the line's menu)
  and the line becomes a task: an **FNC** (a ticket, a fault to fix,
  with its **criticality**: minor, major or critical), a **DM** (an
  evolution) or an **AUT** (anything else: a meeting, support given to
  someone), each numbered on its own - FNC-0001, DM-0001, AUT-0001. The
  line is the task's title; its status, a ticket's criticality and a
  timer sit beside it. The note saves itself as you type.
- A task is about **several projects, or none**: one written in a note
  starts with the note's project.
- **Tasks** on a **board**, a column per status (*Backlog*, *To do*,
  *In progress*, *In review*, *Done*), dragged from one to the next; a
  second board by person; a calendar of the due dates.
- **Time**: start a task's timer from its line, its page or the list -
  one runs at a time, starting another stops it - or log it on the
  **timesheet**, drawn on the hours of the week or the day: drag an
  entry to another time, stretch it from its foot, drag across empty
  hours for a new one, or drop a task from the *Tasks under way* panel
  on a time to log an hour of it.
- **Verification**: a lead goes through the week (*To verify*), checks
  the entries and verifies them - *Verify* is theirs alone.
- On the dashboard: the open tickets and evolutions, the tasks in
  progress, the hours of the week, what is left to verify and the
  timers running.

```bash
pip install -e ".[export]"        # from the repository's root
cd logbook
python manage.py migrate
python manage.py seed_planner
python manage.py runserver
```

Sign in as `admin`, `alice` (a lead: verifies), `bob` (a planner) or
`viewer` (reads), password `demo`.

```
logbook/
├── manage.py
├── logsite/
│   ├── settings.py     one file: the framework, the planner app, two languages
│   ├── urls.py         jsi18n/, api/generic/, the site last
│   └── wsgi.py
└── planner/
    ├── models.py       Label, Project, Note, NoteLine, Task, TimeEntry
    ├── resources.py    the screens: boards, calendars, key figures, actions
    ├── documents.py    a note as the editor reads and writes it
    ├── timers.py       one timer a person; starting one stops the other
    ├── static/planner/ note.js, note.css: the line editor
    ├── templates/      the note's page: the editor above its tables
    ├── locale/fr/      the French
    └── management/commands/seed_planner.py
```

## What is the framework's

Almost everything: the lists, forms and record pages; the board
(`Board`), the calendars (`Calendar`) - the timesheet's hours, moving,
stretching and the panel of tasks to drop (`hours=`, `Allocate`) were
added to the framework for it, see [Calendars](../docs/calendars.md) -
the dashboard's key figures and cards, the charts, the numbering
(`generic.numbering`), the actions and the permissions.

The app's own are the note editor - a page (`@page document`) the
editor reads and posts the note to, and its script - and the timer.

## Kept working

`tests/test_logbook.py` runs it in a process of its own: seeded twice,
every page opened, a note written with new tasks, the timer, a task
dropped on the timesheet, moved and stretched, and the verification.
