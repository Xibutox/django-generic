"""The state of the server, and of the other servers it watches.

One page, *Server status*, shows this server - processors, memory,
disks, the process, every check: databases, migrations, caches, the
channel layer, Celery, the media folder, the tasks - and beside it each
*monitored server*: another installation of django-generic, plugged in
by its address and, when it asks for one, its token. Every server
answers the same JSON document (``api/generic/status/``), so one
maintenance server can watch all the others::

    # settings.py of a server being watched
    GENERIC = {"STATUS_TOKEN": env("STATUS_TOKEN")}

    # a check of the project's own
    from generic.status import register_check

    @register_check(label=_("Payment provider"))
    def payments():
        return "ok", _("Answered")
"""

from generic.status.checks import (
    LEVELS,
    Check,
    register_check,
    unregister_check,
)

__all__ = [
    "LEVELS",
    "Check",
    "register_check",
    "unregister_check",
]
