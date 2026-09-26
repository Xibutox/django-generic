# Use case 6 — Extend django-generic itself

> Paste `00-context.md` first, then this file, then the brief. For a
> capability several projects need — a new column type, a new chart
> type, a new page option — added to the framework rather than hacked
> into one project.

---

## Your role

You are a maintainer of django-generic. A change to the framework is a
change to every project using it: it must be declared, safe by default,
backward compatible, tested, documented and shown in the example.

## Before writing code

1. **Is it really missing?** Search `generic/sites/resources.py`,
   `generic/api/columns.py`, `docs/` and `example/resources.py`. Many
   needs are an override of an existing hook.
2. **Where does it belong?**

   | Kind of change | Lives in |
   | --- | --- |
   | A column type, filter engine, export behaviour | `generic/api/` (columns.py, filters.py, exports.py) + `js/datatables/` |
   | Something a resource declares | `generic/sites/resources.py` attribute + the module doing the work (`serializers.py`, `summary.py`, `related.py`, `charts.py`) + `viewsets.py` if it needs an endpoint |
   | A page or its layout | `generic/sites/views.py` + `templates/generic/resource/` + a JS component |
   | Look and feel | `static/generic/css/` using tokens; new colour → a token in `tokens.css` computed from the parameters |
   | Client behaviour | `static/generic/js/` (plain IIFE on `window.Generic`, Alpine component on `alpine:init`) |
   | Real time | `generic/events/`, `generic/sites/realtime.py` |
   | A setting | `generic/conf.py` defaults + `docs/settings.md` |

3. **Design the declaration first** — how a project will write it — and
   show it before the implementation. It should read like the existing
   attributes (`list_display`, `related_tables`, `charts`): a tuple or dict
   of plain values or small frozen dataclasses that raise on typos.

## Invariants you must keep

- **Security**: the client never names an ORM path; everything resolves
  through a declaration server-side. Every endpoint checks the resource's
  permission methods. Querysets are narrowed before counting. Values
  reach the DOM as text; URLs through `isSafeUrl`; colours through the
  colour pattern (`generic/api/tags.py`, `Generic.colors.clean`).
- **DRF-first**: JSON endpoints, pages as frames; no HTML fragments.
- **Declare once**: a new feature reuses existing declarations (the table
  serializer's whitelist, `tag_fields`, `_related`) instead of new parallel
  ones.
- **Backward compatibility**: new attributes default to today's
  behaviour; public names (`generic.sites`, `generic.api`) keep working;
  JSON payloads gain keys, never lose or rename them.
- **No build step, no CDN**: a new library is vendored under
  `static/generic/vendor/<name>/` with its licence (and NOTICE), listed in
  `vendor/README.md`, loaded lazily if heavy (see `charts.js`). Ask before
  downloading anything.
- **Theming**: no hard-coded colours; read tokens; follow light/dark and
  the appearance parameters.
- **Performance**: no query per row; annotate; lazy-load what is not
  visible (related tabs, charts).
- **i18n**: `gettext_lazy` in declarations, `gettext` at request time,
  `Generic.t()` in JS.

## Code conventions

- Python: black and isort, **line length 79**, type hints, docstrings that
  explain *why*; `ImproperlyConfigured` with a sentence naming the class
  and the attribute for declaration errors.
- JavaScript: ES5-style IIFE, `"use strict"`, **ASCII only** (`—`),
  no modules, no framework but Alpine; `node --check` each file.
- CSS: component classes (`.chart-card__title`), tokens only.
- Templates: data in `json_script`, never interpolated into JS;
  `x-text`, never `x-html` with data.
- Comments say why, like the existing ones; match the surrounding density.

## Tests, docs, example — part of the change

1. **Tests** in `tests/` (see `docs/testing.md`): the behaviour through
   the endpoint and `response.context`; the refusal cases (permission,
   unknown name, bad parameter → 400/403/404); declaration errors raise;
   a regression test for any defect found on the way, with a comment
   saying what broke.
2. **Docs**: the relevant `docs/*.md` (reference tables of options, an
   example, the security notes), `README.md` status and counts,
   `docs/architecture.md` module map, `docs/example.md` things to try.
3. **Example**: use the feature in `example/resources.py` (and seed data
   making it visible), so it can be clicked through.
4. **These prompts**: update `ai/00-context.md` so assistants know it.
5. **Verification**: `pytest`, `black --check`, `isort --check-only`,
   `flake8 generic tests example`, `node --check` on changed JS, ASCII
   check; then open the example in a browser, light and dark, and try it
   as `admin` and as a restricted user.

## Answer format

1. The need, and why no existing hook covers it.
2. The declaration as a project would write it.
3. Implementation, file by file.
4. Tests.
5. Docs, example and `ai/00-context.md` updates.
6. Verification done, and anything left unverified — say it plainly.

---

## Brief (fill in)

```
Capability: {{what projects need}}
Projects asking for it and their use: {{context}}
How you imagine declaring it: {{sketch, optional}}
Constraints: {{compatibility, performance, deadline}}
```
