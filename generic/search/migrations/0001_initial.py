from django.db import migrations

from generic.search.operations import InstallUnaccent


class Migration(migrations.Migration):
    initial = True

    dependencies: list = []

    operations = [InstallUnaccent()]
