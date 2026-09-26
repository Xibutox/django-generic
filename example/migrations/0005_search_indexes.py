"""Trigram indexes: a ticket or a customer search stays fast as the
tables grow. PostgreSQL only; elsewhere this migration does nothing."""

from django.db import migrations

from generic.search.operations import CreateSearchIndex


class Migration(migrations.Migration):
    dependencies = [
        ("example", "0004_equipment"),
        ("generic_search", "0001_initial"),
    ]

    operations = [
        CreateSearchIndex(
            "ticket", ("reference", "title"), name="ticket_search"
        ),
        CreateSearchIndex("customer", ("name",), name="customer_search"),
    ]
