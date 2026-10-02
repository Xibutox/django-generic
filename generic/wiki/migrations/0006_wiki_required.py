"""Every page in a wiki, its address unique within it."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("generic_wiki", "0005_pages_into_first_wiki"),
    ]

    operations = [
        migrations.AlterField(
            model_name="wikipage",
            name="wiki",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="pages",
                to="generic_wiki.wiki",
                verbose_name="wiki",
            ),
        ),
        migrations.AlterField(
            model_name="wikipage",
            name="slug",
            field=models.SlugField(
                allow_unicode=True,
                help_text="The end of the page's URL.",
                max_length=120,
                verbose_name="address",
            ),
        ),
        migrations.AddConstraint(
            model_name="wikipage",
            constraint=models.UniqueConstraint(
                fields=("wiki", "slug"), name="generic_wiki_page_slug"
            ),
        ),
    ]
