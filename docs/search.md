# Search without accents

`societe` finds *Société*, `elodie` finds *Élodie*, and *ÉTÉ* finds
*été*. One optional app, `generic.search`, makes every text match the
framework makes set accents aside as well as case:

| Where | What is folded |
| --- | --- |
| A table's search box | every word, and every `-word` it excludes |
| Column filters | *contains*, *is*, *starts with*, *ends with* and their negations, from the chips, the funnels and the search row |
| The filter editor | its search among a column's values - choice labels included |
| The command palette | every resource's results, and the wiki's |
| Autocompletes | the resource endpoint behind every relation field, and `AutocompleteView` |
| Classic list views | `GenericListView`'s `?q=` |
| Data resources | the same rules, applied in Python to rows that are in no table |

Without the app, every match is what it was: nothing changes for a
project that does not ask.

## Turning it on

```python
INSTALLED_APPS = [
    ...,
    "generic",
    "generic.search",
    ...,
]
```

```bash
python manage.py migrate
```

That is all. The migration does what the database needs:

- **PostgreSQL**: it creates the `unaccent` and `pg_trgm` extensions
  and a function, `generic_unaccent(text)`, wrapping `unaccent` in the
  `IMMUTABLE` promise an index requires. Both extensions are *trusted*
  since PostgreSQL 13, so the database's owner creates them without
  being a superuser. On an older server, or where the application's
  role does not own the database, a DBA runs
  `CREATE EXTENSION unaccent; CREATE EXTENSION pg_trgm;` once, and the
  migration finds them there.
- **SQLite**: nothing to create. The app registers a Python function of
  the same name on every connection, so development and the tests fold
  exactly as production does.
- **Other databases**: nothing. Their collations usually set accents
  aside already, and the searches are sent as before.

## Keeping it fast: a trigram index

`icontains` becomes `UPPER(generic_unaccent(col)) LIKE '%...%'`, which
no ordinary index helps. A GIN trigram index does, and
`CreateSearchIndex` builds one on exactly that expression:

```python
# myapp/migrations/0007_search_indexes.py
from django.db import migrations

from generic.search.operations import CreateSearchIndex


class Migration(migrations.Migration):
    dependencies = [
        ("myapp", "0006_previous"),
        ("generic_search", "0001_initial"),
    ]

    operations = [
        CreateSearchIndex("ticket", ("reference", "title"), name="ticket_search"),
        CreateSearchIndex("customer", ("name",), name="customer_search"),
    ]
```

One index per field (`ticket_search_0`, `ticket_search_1`), used by the
table search, the column filters and the autocompletes alike. Like
Django's own `CreateExtension`, the operation does nothing on another
database, so the migration runs everywhere. It lives in a migration
rather than in `Meta.indexes` for that reason: a model's indexes are
built on every database, and this one only exists on PostgreSQL.

Index what is searched on tables that grow: a few thousand rows scan in
a blink anyway.

## Best match first

```python
@register(Customer)
class CustomerResource(ModelResource):
    search_fields = ("name", "code", "city")
    search_rank = True
```

The command palette and the autocompletes then list the closest match
first: `word_similarity` from `pg_trgm` scores how well the typed words
match a word of each search field, accents set aside, and the best
score of a row sorts it; the usual order breaks ties. Tables are not
reordered - their reader chose an order. Fields crossing a many-valued
relation are left out of the score, which would otherwise list a row
once per related value. On SQLite the order is the usual one.

`generic.W007` names a resource setting `search_rank` in a project that
did not install the app.

## From code

```python
from generic.search import fold, normalize, text_lookup

Customer.objects.filter(**{text_lookup("name"): "societe"})
# name__unaccented__icontains with the app, name__icontains without

text_lookup("reference", "istartswith")
fold("Société Générale")       # "Societe Generale"
normalize("ÉTÉ")               # "ete": what Python-side matches compare
```

`text_lookup` is how the framework itself decides, so a project's own
search agrees with every other. The `unaccented` transform is
registered on every field and is *bilateral*: the searched text is
folded as well as the column.

## What folding means

Letters lose their accents (`é è ê ë` → `e`, `ç` → `c`, `ñ` → `n`), and
the letters Unicode does not decompose are spelled out as PostgreSQL's
`unaccent` rules spell them: `œ` → `oe`, `æ` → `ae`, `ß` → `ss`,
`ø` → `o`, `ł` → `l`, `đ` → `d`. The tests assert the same list
against Python, SQLite and PostgreSQL.

Not included: full-text search - stemming, `SearchVector`. It changes
what a search means, from "contains these letters" to "contains these
words", and a reference or a code would stop matching part of itself.
