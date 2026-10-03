# Numbering

`generic.numbering` makes numbers from a pattern - `LEG-CTR-2026-0042`,
`INV/26/00017`, `SD-1001` - each one given once, never twice, whatever
the number of requests asking at the same time. Nothing to install: it
is part of the framework (`python manage.py migrate` creates its one
table).

```python
from generic.numbering import Pattern, allocate, peek

allocate("{team}-{type}-{year}-{seq:04}", team="LEG", type="CTR")
# "LEG-CTR-2026-0001", then "LEG-CTR-2026-0002"...
```

## A pattern

Text with fields between braces:

| Field | Gives |
| --- | --- |
| `{seq}` | the running number - **required**; `{seq:04}` pads it to four digits (`0042`), twelve at most |
| `{year}`, `{yy}` | `2026`, `26` - today, in the project's `TIME_ZONE` |
| `{month}`, `{day}` | `10`, `03` |
| anything else | a value the caller passes: `allocate(pattern, team="LEG")` |

Only `{seq}` takes a width. A pattern without it could only ever give
one number, and is refused.

## Series

Each **series** counts on its own: the counter is named by the pattern
filled in but for its number - `LEG-CTR-2026-#`. So:

- a pattern holding `{year}` starts again at 1 every year;
- two teams, two types - any value that changes the text - never
  share a count;
- changing a team's pattern starts a new series, and the numbers
  already given stay what they were.

`namespace="invoices"` keeps apart two kinds of record numbered with
the same pattern.

The counter is a row of `generic.Sequence` (`key`, `value`), taken
with `select_for_update`: whoever asks at the same time waits for the
first transaction to end and gets the next number. Call `allocate`
inside the transaction that stores the number - a number taken and
then rolled back is given back with it.

## Unique, even by hand

`exists` skips numbers something already holds - one typed by hand, or
given by an older pattern that happened to match:

```python
code = allocate(
    pattern,
    namespace="documents",
    exists=lambda code: Document.objects.filter(code=code).exists(),
    team="LEG",
    type="CTR",
)
```

Keep a unique constraint on the field too: `exists` makes a collision
unlikely, the constraint makes it impossible.

## In a form

`Pattern(text, fields=(...)).validate()` raises Django's
`ValidationError` - a field the owner does not offer, no `{seq}`, a
width on something else, braces that do not close - so a pattern
people type is checked like any other value:

```python
from generic.numbering import Pattern

def validate_pattern(value):
    Pattern(value, fields=("team", "type")).validate()

pattern = models.CharField(max_length=120, validators=[validate_pattern])
```

`peek(pattern, **values)` shows the number the next record would get,
and takes nothing: what a settings page displays beside the pattern.

## An example

The document manager (`docmanager/`) numbers documents by team: each
team's `Codification` holds its code (`{team}`) and its pattern, a
`DocumentType` gives `{type}`, and `documents/codification.py` calls
`allocate` once per document - at its creation when the team asks for
it, or from the *Codify* action, with or without a file.
