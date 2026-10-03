"""What the document manager does on its own, once a day: on the
*Tasks* page with a *Run now* button, and for a schedule (Celery beat)
or ``manage.py run_periodic_reviews`` from cron to point at."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from generic.tasks import managed_task


@managed_task(
    name="documents.periodic_reviews",
    label=_("Periodic reviews"),
    description=_(
        "Reminds the authors and team leaders of the documents due for "
        "a review soon, and starts the periodic review workflow of "
        "those due today. Run it once a day."
    ),
    icon="event_repeat",
    announce=("page",),
    report=("page",),
)
def periodic_reviews(run: Any) -> str:
    from documents import periodic

    return periodic.run(task_run=run).describe()
