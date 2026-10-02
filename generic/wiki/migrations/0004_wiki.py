"""Several wikis: a wiki for every page, filled in by 0005."""

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("generic_wiki", "0003_wikifile"),
    ]

    operations = [
        migrations.CreateModel(
            name="Wiki",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name",
                    models.CharField(max_length=200, verbose_name="name"),
                ),
                (
                    "slug",
                    models.SlugField(
                        allow_unicode=True,
                        help_text="The part of the URL naming the wiki.",
                        max_length=120,
                        unique=True,
                        verbose_name="address",
                    ),
                ),
                (
                    "description",
                    models.TextField(
                        blank=True, default="", verbose_name="description"
                    ),
                ),
                (
                    "position",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Order among the wikis.",
                        verbose_name="position",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now,
                        verbose_name="created at",
                    ),
                ),
            ],
            options={
                "verbose_name": "wiki",
                "verbose_name_plural": "wikis",
                "ordering": ("position", "name"),
            },
        ),
        migrations.AddField(
            model_name="wikipage",
            name="wiki",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="pages",
                to="generic_wiki.wiki",
                verbose_name="wiki",
            ),
        ),
    ]
