"""The interface size preference goes: the browser's own zoom does the
same, and better - its slider restyled the page under the pointer while
it was dragged."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("generic", "0012_historyentry_delete_favorite"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="userpreferences",
            name="interface_scale",
        ),
    ]
