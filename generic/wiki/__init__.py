"""A small wiki inside the application.

Pages in a menu, edited in place with a rich-text editor by the people
holding the wiki permissions (admins do), read by everyone signed in,
with a history of every version. A page can also be pinned to the
dashboard, which makes it the natural place for announcements and
how-tos.

Optional: add ``"generic.wiki"`` to ``INSTALLED_APPS`` and mount
``generic.wiki.urls`` under ``wiki/``. The sidebar, the dashboard and
the command palette pick it up by themselves.
"""
