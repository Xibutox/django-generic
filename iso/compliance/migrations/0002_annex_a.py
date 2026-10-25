"""The 93 Annex A controls, loaded once in the project's language."""

from django.db import migrations


def load(apps, schema_editor):
    from iso.compliance import catalogue

    catalogue.load(apps.get_model("compliance", "Control"))


class Migration(migrations.Migration):
    dependencies = [("compliance", "0001_initial")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
