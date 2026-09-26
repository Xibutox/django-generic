"""Scheduled mailings: a table, as someone sees it, sent on a schedule.

From any list page, the saved-views menu offers *Send by e-mail on a
schedule*: the table as it is now - its filters, search, columns and
order - becomes a :class:`~generic.mailings.models.ScheduledMailing`,
and a dispatcher task sends it as an Excel or CSV attachment every day,
every weekday, every week or every month.

Each recipient receives the rows **they** may see, computed as them,
in their language: the file is the resource's own export, asked for by
a request signed in as the recipient, so its column whitelist, its
``get_queryset`` and its permissions apply unchanged. Nothing new
decides who sees what.
"""
