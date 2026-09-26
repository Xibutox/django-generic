"""Declared tasks: announced, run, collected, reported.

The four steps are the contract, so most of what is asserted here is
the order things happen in and what is left behind - not how the work
itself was done.
"""

from __future__ import annotations

import pytest
from django.apps import apps
from django.core import mail
from django.urls import reverse

from generic.accounts.models import UserPreferences
from generic.events.models import Notification
from generic.tasks import managed_task
from generic.tasks.models import TaskRun
from generic.tasks.registry import TaskDefinition, registry
from generic.tasks.reporting import recipients
from generic.tasks.resources import beat_installed, tasks_are_offered
from generic.tasks.runner import can_queue, launch

pytestmark = pytest.mark.django_db

TASKS = "/tasks/"
RUNS = "/generic/taskrun/"

beat_only = pytest.mark.skipif(
    not apps.is_installed("django_celery_beat"),
    reason="django-celery-beat is not installed in this environment",
)


@pytest.fixture
def declared():
    """A task declared for one test, withdrawn afterwards.

    The registry is process-wide, like the resource registry: a test
    that leaves one behind changes the catalogue every later test sees.
    """
    names: list[str] = []

    def declare(function=None, **options):
        def decorate(target):
            task = managed_task(**options)(target)
            names.append(task.definition.name)

            return task

        return decorate(function) if function else decorate

    yield declare

    for name in names:
        registry.unregister(name)


@pytest.fixture
def digest(declared):
    """A task that writes a step, adds a result and returns a headline."""

    @declared(name="tests.digest", label="Digest", audience="staff")
    def run_digest(run, **arguments):
        run.note("Counting")
        run.add("Tickets", 3)

        return "3 tickets"

    return run_digest


class TestDeclaring:
    def test_a_declared_task_is_in_the_catalogue(self, digest):
        assert registry.get("tests.digest").label == "Digest"
        assert "tests.digest" in registry.names()

    def test_an_unknown_channel_is_refused_at_declaration(self, declared):
        from django.core.exceptions import ImproperlyConfigured

        with pytest.raises(ImproperlyConfigured):

            @declared(name="tests.bad", report=("carrier-pigeon",))
            def bad(run):  # pragma: no cover - never declared
                pass

    def test_event_is_not_a_channel_and_says_why(self, declared):
        """A notification reaches the open pages already, as a toast."""
        from django.core.exceptions import ImproperlyConfigured

        with pytest.raises(ImproperlyConfigured, match="already reaches"):

            @declared(name="tests.evented", announce=("event",))
            def evented(run):  # pragma: no cover - never declared
                pass

    def test_two_tasks_cannot_share_a_name(self, declared, digest):
        from django.core.exceptions import ImproperlyConfigured

        with pytest.raises(ImproperlyConfigured):

            @declared(name="tests.digest")
            def other(run):  # pragma: no cover - never declared
                pass

    def test_the_name_defaults_to_the_function(self, declared):
        @declared(label="Somewhere")
        def somewhere(run):  # pragma: no cover - not run here
            pass

        assert somewhere.definition.name.endswith("somewhere")


class TestRunning:
    def test_a_run_records_what_the_task_produced(self, digest, user):
        run = launch("tests.digest", user=user)

        assert run.status == TaskRun.Status.SUCCESS
        assert run.summary == "3 tickets"
        assert run.results == [{"label": "Tickets", "value": 3}]
        assert [step["message"] for step in run.log] == ["Counting"]
        assert run.triggered_by == user
        assert run.duration_seconds is not None

    def test_the_row_exists_before_the_work_starts(self, declared):
        """Step 1 happens first, so a task that hangs still has a page."""
        seen = {}

        @declared(name="tests.looks-around")
        def looks_around(run):
            stored = TaskRun.objects.get(pk=run.pk)
            seen["status"] = stored.status
            seen["started"] = stored.started_at is not None

        launch("tests.looks-around")

        assert seen == {"status": TaskRun.Status.RUNNING, "started": True}

    def test_a_failure_is_a_result_like_any_other(self, declared, user):
        @declared(name="tests.breaks", report=("notification",))
        def breaks(run):
            run.note("About to fail")

            raise ValueError("no connection")

        run = launch("tests.breaks", user=user)

        assert run.status == TaskRun.Status.FAILURE
        assert "no connection" in run.error
        assert run.finished_at is not None
        assert [step["message"] for step in run.log] == [
            "Announced to 1 person.",
            "About to fail",
        ]
        # It still reports: silence is the worst way to fail.
        assert (
            Notification.objects.filter(user=user)
            .latest("created_at")
            .title.endswith("failed")
        )

    def test_arguments_reach_the_function(self, declared):
        seen = {}

        @declared(name="tests.takes-arguments")
        def takes_arguments(run, team=""):
            seen["team"] = team

        launch("tests.takes-arguments", arguments={"team": "Front office"})

        assert seen == {"team": "Front office"}

    @pytest.mark.parametrize(
        "returned,summary,results",
        [
            ("done", "done", []),
            (None, "", []),
            (
                {"summary": "two", "results": [{"label": "a"}]},
                "two",
                [{"label": "a"}],
            ),
            (
                [{"label": "a"}, {"label": "b"}],
                "a",
                [{"label": "a"}, {"label": "b"}],
            ),
        ],
    )
    def test_what_a_task_returns_becomes_one_result(
        self,
        declared,
        returned,
        summary,
        results,
    ):
        @declared(name="tests.returns")
        def returns(run):
            return returned

        run = launch("tests.returns")

        assert run.summary == summary
        assert run.results == results

    def test_a_queued_task_is_handed_over_rather_than_run(self, declared):
        """With a worker to take it, nothing runs in this process."""
        handed = {}

        class Handle:
            id = "abc-123"

        class FakeCeleryTask:
            app = type("App", (), {"conf": {"broker_url": "redis://x"}})()

            def delay(self, run_id):
                handed["run_id"] = run_id

                return Handle()

        @declared(name="tests.queued")
        def queued(run):  # pragma: no cover - a worker would run it
            run.note("should not happen")

        registry.register(
            TaskDefinition(
                name="tests.queued",
                function=queued,
                label="Queued",
                celery_task=FakeCeleryTask(),
            )
        )

        run = launch("tests.queued")

        assert handed == {"run_id": run.pk}
        assert run.status == TaskRun.Status.PENDING
        assert run.celery_id == "abc-123"
        assert run.log == []

    def test_without_a_broker_it_runs_here(self, digest):
        assert can_queue(registry.get("tests.digest")) is False


class TestWhoHears:
    def test_the_audience_is_what_the_task_declared(
        self,
        declared,
        user,
        staff_user,
    ):
        @declared(name="tests.for-staff", audience="staff")
        def for_staff(run):
            pass

        run = launch("tests.for-staff", user=user)

        assert recipients(registry.get("tests.for-staff"), run) == [staff_user]

    def test_by_default_only_whoever_started_it_hears(self, declared, user):
        @declared(name="tests.for-me")
        def for_me(run):
            pass

        run = launch("tests.for-me", user=user)

        assert recipients(registry.get("tests.for-me"), run) == [user]
        assert Notification.objects.filter(user=user).count() == 2

    def test_a_scheduled_run_tells_nobody_in_particular(self, declared):
        @declared(name="tests.nightly")
        def nightly(run):
            pass

        run = launch("tests.nightly", trigger=TaskRun.Trigger.SCHEDULE)

        assert recipients(registry.get("tests.nightly"), run) == []
        assert Notification.objects.count() == 0

    def test_a_callable_audience_chooses_for_itself(self, declared, user):
        @declared(name="tests.picky", audience=lambda run: [user])
        def picky(run):
            pass

        launch("tests.picky")

        assert Notification.objects.filter(user=user).count() == 2


class TestHowTheyHear:
    def test_starting_and_finishing_are_two_messages(self, declared, user):
        @declared(
            name="tests.talks",
            label="Talks",
            announce=("notification",),
        )
        def talks(run):
            return "all good"

        launch("tests.talks", user=user)

        titles = list(
            Notification.objects.filter(user=user).values_list(
                "title", flat=True
            )
        )

        # Newest first: step 4, then step 1.
        assert titles == ["Talks has finished", "Talks has started"]

    def test_a_task_can_keep_it_to_its_own_page(self, declared, user):
        @declared(
            name="tests.quiet",
            announce=("page",),
            report=("page",),
        )
        def quiet(run):
            return "nothing to see"

        run = launch("tests.quiet", user=user)

        assert Notification.objects.count() == 0
        assert run.summary == "nothing to see"

    def test_mail_carries_a_link_to_the_run(self, declared, user):
        user.email = "desk@example.test"
        user.save(update_fields=["email"])

        @declared(name="tests.writes", announce=("page",), report=("mail",))
        def writes(run):
            return "12 rows"

        run = launch("tests.writes", user=user)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["desk@example.test"]
        assert run.get_absolute_url() in mail.outbox[0].body

    def test_everyone_reads_it_in_their_own_language(self, declared, user):
        """The reader's language, not the announcer's."""
        UserPreferences.objects.create(user=user, language="fr")

        @declared(name="tests.parle", label="Parle", announce=("page",))
        def parle(run):
            return "fini"

        launch("tests.parle", user=user)

        assert (
            Notification.objects.get(user=user).title == "Parle est terminée"
        )


class TestTheCatalogue:
    def test_it_lists_every_declared_task(self, auth_client, user, digest):
        user.user_permissions.add(permission("run_task"))

        response = auth_client.get(TASKS)
        entries = {entry["name"]: entry for entry in response.context["tasks"]}

        assert response.status_code == 200
        assert entries["tests.digest"]["label"] == "Digest"
        assert b"tests.digest" in response.content

    def test_running_one_lands_on_its_run(self, auth_client, user, digest):
        user.user_permissions.add(permission("run_task"))

        response = auth_client.post(TASKS, {"task": "tests.digest"})

        run = TaskRun.objects.get()

        assert response.status_code == 302
        assert response["Location"] == run.get_absolute_url()
        assert run.trigger == TaskRun.Trigger.MANUAL
        assert run.triggered_by == user

    def test_an_unknown_task_is_not_found(self, auth_client, user, digest):
        user.user_permissions.add(permission("run_task"))

        assert auth_client.post(TASKS, {"task": "nope"}).status_code == 404

    def test_without_the_permission_there_is_no_page(self, auth_client):
        response = auth_client.get(TASKS)

        assert response.status_code in (302, 403)

    def test_it_is_in_the_navigation_of_whoever_may_run_tasks(
        self,
        auth_client,
        user,
        digest,
    ):
        before = auth_client.get("/account/").content.decode()
        user.user_permissions.add(permission("run_task"))
        after = auth_client.get("/account/").content.decode()

        assert TASKS not in before
        assert TASKS in after


class TestTheRunPages:
    def test_the_list_is_a_table_like_any_other(
        self,
        auth_client,
        user,
        digest,
    ):
        user.user_permissions.add(permission("view_taskrun"))
        launch("tests.digest", user=user)

        assert auth_client.get(RUNS).status_code == 200

    def test_a_run_page_shows_its_steps_and_its_result(
        self,
        auth_client,
        user,
        digest,
    ):
        user.user_permissions.add(permission("view_taskrun"))
        run = launch("tests.digest", user=user)

        rendered = auth_client.get(run.get_absolute_url()).content.decode()

        assert "Counting" in rendered
        assert "Tickets" in rendered

    def test_a_run_is_never_written_by_hand(self, user, digest):
        from generic.sites import site

        resource = site.get_resource(TaskRun)

        assert resource.has_add_permission(None) is False
        assert resource.has_change_permission(None) is False

    def test_run_again_starts_another(self, auth_client, user, digest):
        user.user_permissions.add(permission("view_taskrun"))
        user.user_permissions.add(permission("run_task"))
        first = launch("tests.digest", user=user)

        response = auth_client.post(
            reverse("site:api_generic_taskrun-actions"),
            {"action": "run_again", "ids": [first.pk]},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        assert TaskRun.objects.of("tests.digest").count() == 2


@beat_only
class TestTheSchedules:
    def test_the_scheduler_s_models_are_registered(self):
        from generic.sites import site

        model = apps.get_model("django_celery_beat", "PeriodicTask")

        assert site.is_registered(model)
        assert beat_installed() is True
        assert tasks_are_offered() is True

    def test_a_schedule_can_be_run_now(self, auth_client, user, digest):
        crontab = apps.get_model("django_celery_beat", "CrontabSchedule")
        periodic = apps.get_model("django_celery_beat", "PeriodicTask")
        schedule = periodic.objects.create(
            name="Nightly digest",
            task="tests.digest",
            crontab=crontab.objects.create(minute="0", hour="7"),
            # Running one by hand does what the schedule does.
            kwargs='{"team": "Front office"}',
        )

        for codename in ("view_periodictask", "change_periodictask"):
            user.user_permissions.add(
                permission(codename, app_label="django_celery_beat")
            )

        user.user_permissions.add(permission("run_task"))

        response = auth_client.post(
            reverse("site:api_django_celery_beat_periodictask-actions"),
            {"action": "run_now", "ids": [schedule.pk]},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content

        run = TaskRun.objects.get(task="tests.digest")

        assert run.arguments == {"team": "Front office"}

    def test_running_an_undeclared_task_says_so(self, auth_client, user):
        crontab = apps.get_model("django_celery_beat", "CrontabSchedule")
        periodic = apps.get_model("django_celery_beat", "PeriodicTask")
        schedule = periodic.objects.create(
            name="Someone else's",
            task="elsewhere.cleanup",
            crontab=crontab.objects.create(minute="0", hour="4"),
        )

        for codename in ("view_periodictask", "change_periodictask"):
            user.user_permissions.add(
                permission(codename, app_label="django_celery_beat")
            )

        user.user_permissions.add(permission("run_task"))

        response = auth_client.post(
            reverse("site:api_django_celery_beat_periodictask-actions"),
            {"action": "run_now", "ids": [schedule.pk]},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        assert "elsewhere.cleanup" in response.json()["message"]
        assert TaskRun.objects.count() == 0


class TestTheExample:
    def test_the_desk_declares_its_digest(self):
        assert registry.get("example.overdue_digest") is not None

    def test_it_counts_the_overdue_tickets_by_team(
        self,
        support_desk,
        staff_user,
    ):
        import datetime

        from django.utils import timezone

        from example.models import Ticket

        late = support_desk["login"]
        late.due_on = timezone.localdate() - datetime.timedelta(days=3)
        late.status = Ticket.Status.OPEN
        late.save(update_fields=["due_on", "status"])

        run = launch("example.overdue_digest")

        assert run.status == TaskRun.Status.SUCCESS
        assert "1" in run.summary
        assert run.results[0]["value"] == 1
        # Step 1 reached the desk: the admin hears it start.
        assert Notification.objects.filter(user=staff_user).count() == 2


def permission(codename: str, app_label: str = "generic"):
    from django.contrib.auth.models import Permission

    return Permission.objects.get(
        codename=codename,
        content_type__app_label=app_label,
    )
