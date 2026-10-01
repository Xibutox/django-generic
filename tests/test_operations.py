"""Operations: the work behind a button, and the report it answers with.

Two halves. A report (generic.reports) is a tree of levelled lines that
fold, written by any code. An operation (generic.tasks.operations) is a
task a page starts, done in the request or elsewhere, whose run keeps
that report and tells its starter - and only them - when it is done.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.test import override_settings
from django.urls import reverse

from example.models import Customer, Tag, Ticket
from generic.events.models import Notification, NotificationLevel
from generic.reports import (
    MAX_NODES,
    Report,
    count_levels,
    describe_counts,
    node_level,
)
from generic.tasks import operation, operation_payload, operation_response
from generic.tasks.models import TaskRun
from generic.tasks.registry import registry
from generic.tasks.resources import runs_are_kept, tasks_are_offered
from generic.tasks.runner import launch
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

TICKETS = "/api/example/ticket/actions/"
CUSTOMERS = "/api/example/customer/actions/"


@pytest.fixture
def declared():
    """Operations declared for one test, withdrawn afterwards."""
    names: list[str] = []

    def declare(**options):
        def decorate(target):
            declared_operation = operation(**options)(target)
            names.append(declared_operation.definition.name)

            return declared_operation

        return decorate

    yield declare

    for name in names:
        registry.unregister(name)


@pytest.fixture
def tidy(declared):
    """An operation writing a section per value, one of which fails."""

    @declared(name="tests.tidy", label="Tidy")
    def tidy_up(run, names):
        for name in names:
            with run.report.section(name, isolated=True) as section:
                Tag.objects.create(name=name)

                if name == "broken":
                    raise ValueError("cannot tidy broken")

                section.success("tidied")

        return f"{len(names)} looked at"

    return tidy_up


class FakeThread:
    """threading.Thread, run at start(): what the thread would do."""

    started: list["FakeThread"] = []

    def __init__(self, target, args=(), name="", daemon=None):
        self.target, self.args, self.name = target, args, name

    def start(self):
        FakeThread.started.append(self)
        self.target(*self.args)


@pytest.fixture
def threads(monkeypatch):
    """Threads that run when started, and leave the connections open.

    The test database is one connection inside one transaction: a real
    thread would not see the run, and closing every connection at its
    end would close the test's own.
    """
    from generic.tasks import runner

    FakeThread.started = []
    monkeypatch.setattr(
        runner, "threading", SimpleNamespace(Thread=FakeThread)
    )
    monkeypatch.setattr(
        runner, "connections", SimpleNamespace(close_all=lambda: None)
    )

    return FakeThread.started


@pytest.fixture
def published(monkeypatch):
    """The events sent to users, as (user ids, type, payload)."""
    from generic.events import bus

    sent = []

    def capture(users, event_type, payload=None, **kwargs):
        sent.append((list(users), event_type, payload))

    monkeypatch.setattr(bus, "publish_to_users", capture)

    return sent


# -- the report -----------------------------------------------------------


class TestReport:
    def test_lines_keep_their_level_title_and_detail(self):
        report = Report()
        report.warning("No address", "Nothing was sent.")

        assert report.as_list() == [
            {
                "level": "warning",
                "title": "No address",
                "detail": "Nothing was sent.",
                "children": [],
            }
        ]

    def test_a_section_shows_the_worst_level_inside_it(self):
        report = Report()

        with report.section("Customer A") as section:
            section.success("Recomputed")

            with section.section("Invoices") as invoices:
                invoices.error("Invoice 12 failed")

        assert node_level(report.nodes[0]) == "error"
        assert report.level == "error"

    def test_a_report_with_nothing_wrong_is_a_success(self):
        report = Report()
        report.info("Read 12 rows")

        assert report.level == "success"
        assert Report().level == "success"

    def test_counts_are_of_lines_not_sections(self):
        report = Report()

        with report.section("A") as section:
            section.warning("one")
            section.warning("two")
            section.error("three")

        assert count_levels(report.nodes) == {
            "info": 0,
            "success": 0,
            "warning": 2,
            "error": 1,
        }
        assert describe_counts(report.counts()) == "1 error, 2 warnings"
        assert describe_counts(Report().counts()) == "Everything went well."

    def test_an_unknown_level_is_refused(self):
        with pytest.raises(ValueError, match="Unknown report level"):
            Report().add("fatal", "Boom")

    def test_a_line_links_only_to_a_page_or_a_web_address(self):
        report = Report()
        report.info("Open", url="/example/ticket/1/")
        report.info("Script", url="javascript:alert(1)")
        report.info("Elsewhere", url="//evil.test/")

        urls = [node.get("url") for node in report.nodes]

        assert urls == ["/example/ticket/1/", None, None]

    def test_an_isolated_section_rolls_back_and_goes_on(self):
        report = Report()

        for name in ("kept", "dropped"):
            with report.section(name, isolated=True) as section:
                Tag.objects.create(name=name)

                if name == "dropped":
                    raise IntegrityError("duplicate")

                section.success("saved")

        assert list(Tag.objects.values_list("name", flat=True)) == ["kept"]
        assert report.failures == 1
        assert report.nodes[1]["children"][-1]["level"] == "error"
        assert "IntegrityError: duplicate" in (
            report.nodes[1]["children"][-1]["title"]
        )

    def test_outside_an_isolated_section_an_error_propagates(self):
        report = Report()

        with pytest.raises(ValueError):
            with report.section("plain"):
                raise ValueError("stop")

    def test_a_huge_report_says_how_much_it_left_out(self):
        report = Report()

        for number in range(MAX_NODES + 5):
            report.info(f"line {number}")

        assert len(report.nodes) == MAX_NODES
        assert report.as_list()[-1]["title"] == "... 5 more"

    def test_for_page_opens_the_sections_that_need_reading(self):
        report = Report()

        with report.section("fine") as section:
            section.success("ok")

        with report.section("not fine") as section:
            section.warning("careful")

        fine, not_fine = report.for_page()

        assert (fine["shown"], fine["open"], fine["counts"]) == (
            "success",
            False,
            "",
        )
        assert (not_fine["shown"], not_fine["open"]) == ("warning", True)
        assert not_fine["counts"] == "1 warning"

    def test_a_report_is_answered_with_its_tree(self):
        report = Report()
        report.warning("careful")

        payload = operation_payload(report)

        assert payload["level"] == "warning"
        assert payload["message"] == "1 warning"
        assert payload["operation"]["finished"] is True
        assert payload["operation"]["id"] is None
        assert payload["operation"]["report"][0]["title"] == "careful"


# -- declaring --------------------------------------------------------------


class TestDeclaring:
    def test_an_operation_is_a_task_off_the_catalogue(self, tidy):
        definition = registry.get("tests.tidy")

        assert definition.catalogue is False
        assert definition not in registry.catalogue()
        assert definition.announce == ("page",)
        assert definition.audience == "trigger"

    def test_operations_alone_keep_the_runs_without_the_tasks_page(self):
        # The example declares operations, and a catalogue task too.
        assert runs_are_kept()

        with override_settings(GENERIC={"SHOW_TASKS": False}):
            assert not runs_are_kept()
            assert not tasks_are_offered()

    def test_the_tasks_page_will_not_start_an_operation(
        self, admin_client, tidy
    ):
        response = admin_client.post(
            reverse("site:tasks"), {"task": "tests.tidy"}
        )

        assert response.status_code == 404
        assert not TaskRun.objects.exists()


# -- starting ---------------------------------------------------------------


class TestStarting:
    def test_in_the_request_the_run_is_finished_with_its_report(
        self, tidy, user, published
    ):
        run = tidy.start(user, names=["dust", "broken"])

        assert run.status == TaskRun.Status.SUCCESS
        assert run.summary == "2 looked at"
        assert run.level == "error"
        assert [node["title"] for node in run.tree] == ["dust", "broken"]
        assert TaskRun.objects.get().tree == run.tree
        # The isolated section rolled its own tag back.
        assert list(Tag.objects.values_list("name", flat=True)) == ["dust"]

    def test_in_the_request_it_is_answered_not_notified(
        self, tidy, user, published
    ):
        tidy.start(user, names=["dust"])

        assert not Notification.objects.exists()
        assert published == []

    def test_a_request_stands_for_its_user(self, tidy, rf, user):
        request = rf.post("/")
        request.user = user

        run = tidy.start(request, names=["dust"])

        assert run.triggered_by == user

    def test_arguments_must_be_json(self, tidy, user):
        with pytest.raises(TypeError, match="primary keys, not records"):
            tidy.start(user, names=[user])

    def test_a_declared_permission_is_checked_on_every_start(
        self, declared, user
    ):
        @declared(name="tests.guarded", permission="example.change_ticket")
        def guarded(run):  # pragma: no cover - refused before it runs
            pass

        with pytest.raises(PermissionDenied):
            guarded.start(user)

        assert not TaskRun.objects.exists()

    def test_the_run_remembers_the_language_it_was_started_in(
        self, declared, user
    ):
        from django.utils import translation
        from django.utils.translation import gettext

        @declared(name="tests.speaks")
        def speaks(run):
            run.report.info(gettext("Nothing was selected."))

        from generic.tasks.runner import create_run, execute

        with translation.override("fr"):
            run = create_run("tests.speaks", user=user)

        # Wherever it runs later - a worker, a thread - it writes French.
        run = execute(run.pk, deliver=False)

        assert run.language == "fr"
        assert (
            run.tree[0]["title"]
            == "Rien n'a \u00e9t\u00e9 s\u00e9lectionn\u00e9."
        )


class TestBackground:
    def test_without_a_worker_it_goes_to_a_thread_after_the_commit(
        self,
        tidy,
        user,
        threads,
        published,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            run = tidy.start(user, background=True, names=["dust"])

        # Answered before the work: the thread starts on the commit.
        assert run.status == TaskRun.Status.PENDING
        assert threads == []

        for callback in callbacks:
            callback()

        run.refresh_from_db()

        assert [thread.name for thread in threads] == [f"generic-run-{run.pk}"]
        assert run.status == TaskRun.Status.SUCCESS
        assert run.summary == "1 looked at"

    def test_its_end_is_told_to_its_starter_and_to_their_page(
        self,
        tidy,
        user,
        threads,
        published,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            run = tidy.start(user, background=True, names=["dust", "broken"])

        run.refresh_from_db()
        notification = Notification.objects.get()

        assert notification.user == user
        assert notification.level == NotificationLevel.CRITICAL
        assert notification.url == run.get_absolute_url()
        assert "1 error" in notification.body

        [(users, event_type, payload)] = published

        assert users == [user.pk]
        assert event_type == "operation.finished"
        assert payload["id"] == run.pk
        assert payload["finished"] is True
        assert payload["level"] == "error"

    def test_the_inline_fallback_keeps_the_work_in_the_request(
        self, tidy, user, threads
    ):
        with override_settings(GENERIC={"OPERATION_FALLBACK": "inline"}):
            run = tidy.start(user, background=True, names=["dust"])

        assert run.status == TaskRun.Status.SUCCESS
        assert threads == []

    def test_an_unknown_fallback_is_refused(self, tidy, user):
        with override_settings(GENERIC={"OPERATION_FALLBACK": "carrier"}):
            with pytest.raises(ValueError, match="OPERATION_FALLBACK"):
                tidy.start(user, background=True, names=[])

    def test_a_failure_in_the_background_is_reported_too(
        self,
        declared,
        user,
        threads,
        published,
        django_capture_on_commit_callbacks,
    ):
        @declared(name="tests.fails", label="Fails")
        def fails(run):
            run.report.info("got this far")
            raise RuntimeError("the disk is full")

        with django_capture_on_commit_callbacks(execute=True):
            run = fails.start(user, background=True)

        run.refresh_from_db()

        assert run.status == TaskRun.Status.FAILURE
        assert run.level == "error"
        assert run.tree[0]["title"] == "got this far"
        assert Notification.objects.get().title == "Fails failed"


# -- answering a page -------------------------------------------------------


class TestAnswering:
    def test_a_finished_run_is_answered_with_200(self, tidy, user):
        response = operation_response(tidy.start(user, names=["dust"]))

        assert response.status_code == 200
        assert response.data["message"] == "1 looked at"
        assert response.data["level"] == "success"
        assert response.data["operation"]["report"][0]["title"] == "dust"

    def test_a_run_still_going_is_answered_with_202(self, tidy, user, threads):
        run = tidy.start(user, background=True, names=["dust"])
        response = operation_response(run)

        assert response.status_code == 202
        assert response.data["level"] == "info"
        assert response.data["operation"]["finished"] is False
        assert "running in the background" in response.data["message"]

    def test_only_runs_and_reports_are_answered(self):
        with pytest.raises(TypeError):
            operation_payload("done")

    def test_an_action_returning_a_report_answers_with_it(
        self, monkeypatch, worker_client, support_desk
    ):
        from generic.sites import action, site

        resource = site.get_resource(Ticket)

        @action(description="Check", permissions=("view",))
        def audit(self, request, queryset):
            report = Report()

            for ticket in queryset:
                report.warning(ticket.reference)

            return {"message": "Audited", "report": report}

        # In place of the example's own "check": any action may return
        # a report, with or without an operation behind it.
        monkeypatch.setattr(type(resource), "check", audit)

        response = worker_client.post(
            TICKETS,
            {"action": "check", "ids": [support_desk["login"].pk]},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Audited"
        assert response.json()["level"] == "warning"
        assert response.json()["count"] == 1
        assert response.json()["operation"]["report"][0]["title"] == "SD-1"


# -- the run's page -----------------------------------------------------------


class TestRunPage:
    def test_whoever_started_it_may_read_its_page(self, tidy, client, user):
        run = tidy.start(user, names=["dust", "broken"])
        client.force_login(user)

        response = client.get(run.get_absolute_url())

        assert response.status_code == 200
        assert "report__section" in response.content.decode()
        assert "cannot tidy broken" in response.content.decode()

    def test_nobody_else_may_without_the_permission(self, tidy, client, user):
        run = tidy.start(user, names=["dust"])
        client.force_login(UserFactory(username="other"))

        response = client.get(run.get_absolute_url())

        assert response.status_code in (403, 404)

    def test_run_again_leaves_operations_to_their_page(
        self, tidy, admin_client, admin_user
    ):
        tidy.start(admin_user, names=["dust"])

        response = admin_client.post(
            "/api/generic/taskrun/actions/",
            {"action": "run_again", "all": True},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert "started from its own page" in response.json()["message"]
        assert TaskRun.objects.count() == 1

    def test_a_task_run_by_hand_reports_its_warnings_on_the_bell(
        self, declared, staff_user
    ):
        @declared(name="tests.warns", label="Warns")
        def warns(run):
            run.report.warning("one customer has no address")

        definition = registry.get("tests.warns")
        # A task, rather than an operation: it reports when it ends.
        registry.register(
            type(definition)(
                **{**definition.__dict__, "report": ("notification",)}
            )
        )

        launch("tests.warns", user=staff_user)

        notification = Notification.objects.get()

        assert notification.level == NotificationLevel.WARNING
        assert "1 warning" in notification.body


# -- the example ------------------------------------------------------------


class TestExample:
    def test_checking_tickets_answers_with_a_section_each(
        self, worker_client, support_desk
    ):
        login = support_desk["login"]
        login.due_on = datetime.date(2020, 1, 1)
        login.save()

        response = worker_client.post(
            TICKETS,
            {
                "action": "check",
                "ids": [login.pk, support_desk["export"].pk],
            },
            content_type="application/json",
        )
        answer = response.json()

        assert response.status_code == 200
        assert answer["level"] == "error"
        assert answer["count"] == 2
        assert answer["operation"]["finished"] is True

        sections = {
            node["title"]: node for node in answer["operation"]["report"]
        }
        login_section = sections["SD-1 - Login fails after password reset"]

        assert login_section["url"] == f"/example/ticket/{login.pk}/"
        assert login_section["children"][0]["level"] == "error"
        assert sections["SD-3 - Invoice export is slow"]["children"][0][
            "title"
        ] == ("Closed: nothing to check.")

    def test_reviewing_customers_answers_at_once(
        self, admin_client, support_desk, threads
    ):
        customer = Customer.objects.create(name="Acme", code="ACME")
        Ticket.objects.filter(pk=support_desk["login"].pk).update(
            customer=customer, due_on=datetime.date(2020, 1, 1)
        )

        response = admin_client.post(
            CUSTOMERS,
            {"action": "review", "ids": [customer.pk]},
            content_type="application/json",
        )
        answer = response.json()

        assert response.status_code == 200
        assert answer["operation"]["finished"] is False
        # The thread starts on the commit, which a test never reaches.
        assert threads == []

        run = TaskRun.objects.get()
        run = launch(run.task, user=run.triggered_by, arguments=run.arguments)

        [section] = run.tree

        assert section["title"] == "Acme"
        assert [child["level"] for child in section["children"]] == [
            "info",
            "error",
            "warning",
        ]
