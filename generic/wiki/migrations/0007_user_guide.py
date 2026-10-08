"""The user guide, in the first wiki: one page per language of the site
the guide is written in (generic/wiki/guide.py)."""

from django.db import migrations


def add_user_guide(apps, schema_editor):
    from generic.wiki.guide import install_user_guide

    install_user_guide(
        wiki_model=apps.get_model("generic_wiki", "Wiki"),
        page_model=apps.get_model("generic_wiki", "WikiPage"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("generic_wiki", "0006_wiki_required"),
    ]

    operations = [
        # Going back leaves the pages: by then they may have been edited.
        migrations.RunPython(add_user_guide, migrations.RunPython.noop),
    ]
