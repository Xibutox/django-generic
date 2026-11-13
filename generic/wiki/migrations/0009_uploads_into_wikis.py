"""Each image and file already uploaded goes to the wiki of the first
page showing it: from now on, whoever reads that wiki opens it. An
upload no page shows stays without one - its uploader's alone."""

import re

from django.db import migrations
from django.urls import NoReverseMatch, reverse


def pattern(kind):
    """The address of a ``kind`` upload wherever the wiki is mounted,
    its id as a group - or ``None`` where the wiki has no address."""
    try:
        sample = reverse(f"generic_wiki:{kind}", kwargs={"pk": 4242})
    except NoReverseMatch:
        return None

    return re.compile(
        r"""(?:src|href)=["']"""
        + re.escape(sample).replace("4242", r"(\d+)")
        + r"""["']"""
    )


def assign(apps, schema_editor):
    WikiPage = apps.get_model("generic_wiki", "WikiPage")
    kinds = {
        "image": apps.get_model("generic_wiki", "WikiImage"),
        "file": apps.get_model("generic_wiki", "WikiFile"),
    }
    patterns = {kind: pattern(kind) for kind in kinds}
    found: dict = {kind: {} for kind in kinds}

    for wiki_id, content in (
        WikiPage.objects.exclude(content="")
        .order_by("pk")
        .values_list("wiki_id", "content")
        .iterator()
    ):
        for kind, expression in patterns.items():
            if expression is None:
                continue

            for match in expression.finditer(content):
                found[kind].setdefault(int(match.group(1)), wiki_id)

    for kind, model in kinds.items():
        by_wiki: dict = {}

        for pk, wiki_id in found[kind].items():
            by_wiki.setdefault(wiki_id, []).append(pk)

        for wiki_id, keys in by_wiki.items():
            model.objects.filter(pk__in=keys, wiki__isnull=True).update(
                wiki_id=wiki_id
            )


class Migration(migrations.Migration):
    dependencies = [("generic_wiki", "0008_members_trash")]

    operations = [migrations.RunPython(assign, migrations.RunPython.noop)]
