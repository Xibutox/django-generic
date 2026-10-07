"""The catalogue: what this application knows how to run.

A page rather than a table, because what it lists is declarations in
code, not rows: every task, what it does, who it tells, and how its
last few runs went. The button starts one, which is a form post and a
redirect - the work itself goes to a worker, or happens here when there
is none.
"""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from generic.conf import generic_settings
from generic.sites.views import SiteViewMixin
from generic.tasks.models import TaskRun
from generic.tasks.registry import registry
from generic.tasks.resources import (
    beat_installed,
    results_installed,
    results_url,
    send_to_celery,
    tasks_are_offered,
    undeclared_tasks,
)
from generic.tasks.runner import launch
from generic.views.toolbar import Breadcrumb, ToolbarItem


class TasksPage(SiteViewMixin, TemplateView):
    """Every declared task, with a button and its recent runs."""

    template_name = "generic/tasks/catalogue.html"
    page_title = _("Task catalogue")
    page_subtitle = _(
        "The tasks declared to the framework: run one now, see its "
        "schedules and its last runs."
    )

    def has_permission(self) -> bool:
        if not tasks_are_offered():
            return False

        return bool(self.request.user.has_perm("generic.run_task"))

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [Breadcrumb(label=gettext("Task catalogue"))]

    def get_toolbar_items(self) -> list[ToolbarItem]:
        items = [
            ToolbarItem(
                url=reverse("site:generic_taskrun_list"),
                label=gettext("Runs"),
                icon="history",
                variant="ghost",
            )
        ]

        if results_installed():
            items.append(
                ToolbarItem(
                    url=reverse("site:django_celery_results_taskresult_list"),
                    label=gettext("Celery results"),
                    icon="fact_check",
                    variant="ghost",
                )
            )

        if beat_installed():
            items.append(
                ToolbarItem(
                    url=reverse("site:django_celery_beat_periodictask_list"),
                    label=gettext("Schedules"),
                    icon="schedule",
                    variant="ghost",
                )
            )

        return items

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["tasks"] = self.get_tasks()
        context["other_tasks"] = self.get_other_tasks()
        context["results_installed"] = results_installed()
        context["beat_installed"] = beat_installed()

        return context

    def get_tasks(self) -> list[dict[str, Any]]:
        """Each declared task, with how its last runs went."""
        limit = int(generic_settings.TASK_RECENT_RUNS or 0)
        entries = []

        for definition in registry.catalogue():
            runs = list(TaskRun.objects.of(definition.name)[:limit])
            entries.append(
                {
                    "definition": definition,
                    "name": definition.name,
                    "label": definition.title,
                    "description": definition.description,
                    "icon": definition.icon,
                    "announce": definition.announce,
                    "report": definition.report,
                    "queued": definition.celery_task is not None,
                    "runs": runs,
                    "last": runs[0] if runs else None,
                    "schedules": self.schedules_for(definition.name),
                }
            )

        return entries

    def get_other_tasks(self) -> list[dict[str, Any]]:
        """The Celery tasks no ``@managed_task`` declares.

        Found in the Celery app, not declared: they can be sent from
        here, and what came of them is in Celery's results.
        """
        return [
            {
                "name": name,
                "schedules": self.schedules_for(name),
                "results_url": results_url(task=name),
            }
            for name in undeclared_tasks()
        ]

    def schedules_for(self, name: str) -> list[Any]:
        """The scheduler's rows pointing at this task, if it is installed."""
        if not beat_installed():
            return []

        from django.apps import apps

        model = apps.get_model("django_celery_beat", "PeriodicTask")

        return list(model.objects.filter(task=name))

    def post(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        """Run one task, then come back and say what happened."""
        name = (request.POST.get("task") or "").strip()
        definition = registry.get(name)

        if definition is None and name in undeclared_tasks():
            return self.send(request, name)

        # An operation is started by the page offering it, with the
        # arguments only that page knows: never from here, by name.
        if definition is None or not definition.catalogue:
            raise Http404(f"No task is called {name!r}.")

        if definition.permission and not request.user.has_perm(
            definition.permission
        ):
            messages.error(
                request,
                gettext("You may not run %(task)s.")
                % {"task": definition.title},
            )

            return HttpResponseRedirect(request.path)

        run = launch(
            name,
            user=request.user,
            trigger=TaskRun.Trigger.MANUAL,
        )

        if run.status == TaskRun.Status.FAILURE:
            messages.error(
                request,
                gettext("%(task)s failed: %(error)s")
                % {"task": run.label, "error": run.summary or run.error},
            )
        elif run.is_finished:
            messages.success(
                request,
                gettext("%(task)s finished. %(summary)s")
                % {"task": run.label, "summary": run.summary},
            )
        else:
            messages.info(
                request,
                gettext("%(task)s is running.") % {"task": run.label},
            )

        return HttpResponseRedirect(run.get_absolute_url() or request.path)

    def send(self, request: Any, name: str) -> Any:
        """Send a Celery task nobody declared, without arguments."""
        try:
            task_id = send_to_celery(name)
        except Exception as error:  # the broker, or the task itself
            messages.error(
                request,
                gettext("%(task)s could not be sent: %(error)s")
                % {"task": name, "error": error},
            )

            return HttpResponseRedirect(request.path)

        messages.success(
            request,
            gettext("%(task)s sent to Celery (%(id)s).")
            % {"task": name, "id": task_id},
        )

        return HttpResponseRedirect(results_url(task=name) or request.path)
