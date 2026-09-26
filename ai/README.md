# Building with an AI assistant

These files teach an AI assistant (Claude, ChatGPT, Copilot, Cursor…) how
django-generic works, so it can develop a complete application by
**declaring** screens with the framework instead of re-coding lists,
forms, detail pages, charts and APIs.

| File | Use it to |
| --- | --- |
| [`00-context.md`](00-context.md) | **Always first.** The reference: rules, stack, file map, every declaration, endpoints, front end, events, settings, pitfalls |
| [`01-new-application.md`](01-new-application.md) | **The main use case.** From a business brief — any domain, any models — to models, resources, dashboard, permissions, demo data and tests |
| [`02-add-a-model.md`](02-add-a-model.md) | Add a model or a feature to an existing app, wired everywhere it belongs |
| [`03-record-overview.md`](03-record-overview.md) | Design a record's summary page: figures, sections, many related tables, tags, charts |
| [`04-custom-page-and-api.md`](04-custom-page-and-api.md) | A screen that is not one model's records: aggregated tables, custom charts (e.g. workload with a capacity line), Alpine blocks, workflow endpoints, real time |
| [`05-project-setup.md`](05-project-setup.md) | Start a new Django project on the framework: settings, URLs, ASGI, Celery, Docker, CI |
| [`06-extend-the-framework.md`](06-extend-the-framework.md) | Add a capability to django-generic itself, safely |
| [`07-review-and-debug.md`](07-review-and-debug.md) | Review generated code against the contract; a troubleshooting table |

## How to use them

**In a chat assistant**: start a conversation with the content of
`00-context.md`, then the use-case file, then fill in its *Brief* section.
Keep the same conversation for follow-ups; paste `00-context.md` again in
a new one.

**In a coding agent with access to the repository** (Claude Code, Cursor,
Copilot agent…): `AGENTS.md` and `CLAUDE.md` at the repository root point
the agent to this folder automatically. Ask, for instance:

> Read ai/00-context.md and ai/01-new-application.md, then build the
> application described below. Brief: …

An agent that can run commands should run the migrations, the tests and
the linters itself, as the prompts ask.

**In a project that installs django-generic** (rather than working in
this repository): copy the `ai/` folder into that project, keep
`00-context.md` as is, and add a short `ai/project.md` describing the
project's own apps, conventions and vocabulary; paste it after
`00-context.md`.

## Tips for good results

- Give the brief in the users' words, with real examples of records.
  Volumes matter: they decide inline versus related table.
- Say who may do what; the assistant turns it into groups and
  permissions.
- List the questions the data must answer; they become figures and
  charts.
- Ask for phase 1 and 2 (domain and design tables) first on a large
  application, review them, then let it write the code.
- Review the result with `07-review-and-debug.md` before merging.

## Keeping them true

The prompts describe this version of the framework. When the framework
changes — a new attribute, a new endpoint — update `00-context.md` in the
same change (use case 6 says so). When an assistant reports that the code
and the context disagree, the code is right: fix the context.
