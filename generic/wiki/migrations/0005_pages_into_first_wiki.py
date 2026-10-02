"""The pages written so far move into a first wiki.

A migration of its own, between adding the column and requiring it:
PostgreSQL refuses to alter a table whose rows changed in the same
transaction.
"""

from django.db import migrations


def into_first_wiki(apps, schema_editor):
    """Every page gets the first wiki - "Wiki", at ``main`` - so the
    pages of a site that had one wiki stay where readers find them."""
    Wiki = apps.get_model("generic_wiki", "Wiki")
    WikiPage = apps.get_model("generic_wiki", "WikiPage")
    wiki, _created = Wiki.objects.get_or_create(
        slug="main", defaults={"name": "Wiki"}
    )
    WikiPage.objects.filter(wiki__isnull=True).update(wiki=wiki)


class Migration(migrations.Migration):

    dependencies = [
        ("generic_wiki", "0004_wiki"),
    ]

    operations = [
        migrations.RunPython(into_first_wiki, migrations.RunPython.noop),
    ]
