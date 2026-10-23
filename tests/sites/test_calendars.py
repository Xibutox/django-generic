"""Calendars: a resource's records on the days of a date field.

The example declares one on tickets, by due date, coloured by priority,
editable: a ticket dragged to another day gets that due date.
"""

from __future__ import annotations

import datetime
import json

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from example.models import Ticket, TimeEntry
from generic.sites import Allocate, Calendar, ModelResource, site
from generic.sites.calendars import (
    MAX_DAYS,
    bind_calendar,
    parse_moment,
    wall_clock,
)

pytestmark = pytest.mark.django_db

DUE = "/api/example/ticket/calendars/due/"
PAGE = "/example/ticket/due/"


def move_url(ticket) -> str:
    return f"/api/example/ticket/{ticket.pk}/calendars/due/"


@pytest.fixture
def october(support_desk):
    """SD-1 due on the 6th, SD-2 on the 20th, SD-3 not due."""
    Ticket.objects.filter(pk=support_desk["login"].pk).update(
        due_on=datetime.date(2026, 10, 6)
    )
    Ticket.objects.filter(pk=support_desk["invoice"].pk).update(
        due_on=datetime.date(2026, 10, 20)
    )

    return support_desk


def days(client, start="2026-10-01", end="2026-11-01", **params) -> dict:
    response = client.get(DUE, {"start": start, "end": end, **params})

    assert response.status_code == 200, response.content

    return response.json()


@pytest.fixture
def reader_client(client, django_user_model):
    user = django_user_model.objects.create_user(username="reader")
    user.user_permissions.set(
        Permission.objects.filter(codename="view_ticket")
    )
    client.force_login(user)

    return client


class TestTheRecordsOfARange:
    def test_the_records_falling_in_it(self, admin_client, october):
        answer = days(admin_client)

        assert [event["start"] for event in answer["events"]] == [
            "2026-10-06",
            "2026-10-20",
        ]
        assert answer["truncated"] is False
        assert answer["editable"] is True

    def test_the_end_is_left_out(self, admin_client, october):
        answer = days(admin_client, start="2026-10-07", end="2026-10-20")

        assert answer["events"] == []

    def test_an_event_carries_its_page_colour_and_values(
        self, admin_client, october
    ):
        login = october["login"]
        event = days(admin_client)["events"][0]

        assert event["id"] == str(login.pk)
        assert event["label"] == "SD-1 - Login fails after password reset"
        assert event["url"] == f"/example/ticket/{login.pk}/"
        assert event["end"] == event["start"]
        assert event["time"] == ""
        # High priority, as the example's tag style colours it.
        assert event["color"] or event["background"]
        assert [cell["label"] for cell in event["cells"]] == [
            "Customer",
            "Status",
            "Assignee",
        ]

    def test_the_table_s_filters_and_search_apply(self, admin_client, october):
        tree = {
            "match": "all",
            "conditions": [
                {
                    "column": "status",
                    "operator": "any_of",
                    "value": ["pending"],
                }
            ],
        }
        filtered = days(admin_client, filters=json.dumps(tree))
        searched = days(admin_client, search="login")

        assert [event["label"][:4] for event in filtered["events"]] == ["SD-2"]
        assert [event["label"][:4] for event in searched["events"]] == ["SD-1"]

    @pytest.mark.parametrize(
        "start, end",
        [
            ("", "2026-11-01"),
            ("2026-10-01", "soon"),
            ("2026-10-10", "2026-10-01"),
            ("2026-01-01", "2026-12-31"),
        ],
    )
    def test_a_range_it_cannot_read_is_refused(
        self, admin_client, october, start, end
    ):
        response = admin_client.get(DUE, {"start": start, "end": end})

        assert response.status_code == 400

    def test_refused_without_the_view_permission(
        self, client, django_user_model, october
    ):
        client.force_login(django_user_model.objects.create_user("nobody"))

        response = client.get(
            DUE, {"start": "2026-10-01", "end": "2026-11-01"}
        )

        assert response.status_code == 403

    def test_an_unknown_calendar_is_not_found(self, admin_client, db):
        response = admin_client.get(
            "/api/example/ticket/calendars/nope/",
            {"start": "2026-10-01", "end": "2026-11-01"},
        )

        assert response.status_code == 404

    def test_a_reader_who_may_not_move_is_told(self, reader_client, october):
        assert days(reader_client)["editable"] is False


class TestMoving:
    def test_a_record_gets_the_day_it_is_dropped_on(
        self, admin_client, october
    ):
        login = october["login"]
        response = admin_client.patch(
            move_url(login),
            {"date": "2026-10-09"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["start"] == "2026-10-09"
        login.refresh_from_db()
        assert login.due_on == datetime.date(2026, 10, 9)

    def test_refused_without_the_change_permission(
        self, reader_client, october
    ):
        response = reader_client.patch(
            move_url(october["login"]),
            {"date": "2026-10-09"},
            content_type="application/json",
        )

        assert response.status_code == 403

    def test_a_day_it_cannot_read_is_refused(self, admin_client, october):
        response = admin_client.patch(
            move_url(october["login"]),
            {"date": "Friday"},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_a_record_without_a_date_is_not_moved(self, admin_client, october):
        response = admin_client.patch(
            move_url(october["export"]),
            {"date": "2026-10-09"},
            content_type="application/json",
        )

        assert response.status_code == 400


class TestThePage:
    def test_the_page_carries_the_calendar_and_the_table(
        self, admin_client, db
    ):
        response = admin_client.get(PAGE)

        assert response.status_code == 200
        config = response.context["calendar_config"]
        assert config["url"] == DUE
        assert config["filterTable"] == "calendar-filter-table"
        assert config["moveUrl"] == "/api/example/ticket/{id}/calendars/due/"
        assert config["views"] == ["month", "week", "list"]
        assert response.context["filter_table"]["options"]["rowActions"] == []
        assert b"generic/js/calendar.js" in response.content

    def test_a_button_on_the_list_and_an_entry_in_the_navigation(
        self, admin_client, db
    ):
        response = admin_client.get("/example/ticket/")

        assert PAGE.encode() in response.content

    def test_a_reader_may_not_move(self, reader_client, db):
        response = reader_client.get(PAGE)

        assert response.context["calendar_config"]["moveUrl"] == ""
        assert response.context["calendar_config"]["addUrl"] == ""


class TestOtherShapes:
    """A date and time, and a record lasting several days."""

    def bound(self, **options):
        resource = type("Probe", (ModelResource,), {})(Ticket, site)

        return resource, bind_calendar(Calendar("probe", **options), resource)

    def request(self, admin_user):
        request = RequestFactory().get("/")
        request.user = admin_user

        return request

    def test_a_date_and_time_falls_on_its_local_day_with_its_time(
        self, admin_user, support_desk
    ):
        resource, bound = self.bound(date="opened_at")
        opened = timezone.make_aware(datetime.datetime(2026, 10, 6, 14, 30))
        Ticket.objects.filter(pk=support_desk["login"].pk).update(
            opened_at=opened
        )
        answer = bound.answer(
            self.request(admin_user),
            resource.get_queryset(self.request(admin_user)),
            {"start": "2026-10-06", "end": "2026-10-07"},
        )

        assert len(answer["events"]) == 1
        assert answer["events"][0]["start"] == "2026-10-06"
        assert answer["events"][0]["time"]

    def test_a_record_lasting_several_days_is_on_each(
        self, admin_user, support_desk
    ):
        resource, bound = self.bound(date="opened_at", end="due_on")
        Ticket.objects.filter(pk=support_desk["login"].pk).update(
            opened_at=timezone.make_aware(datetime.datetime(2026, 9, 28, 9)),
            due_on=datetime.date(2026, 10, 3),
        )
        request = self.request(admin_user)
        queryset = resource.get_queryset(request).filter(
            pk=support_desk["login"].pk
        )
        # It started before the range and ends inside it.
        answer = bound.answer(
            request, queryset, {"start": "2026-10-01", "end": "2026-11-01"}
        )

        assert answer["events"][0]["start"] == "2026-09-28"
        assert answer["events"][0]["end"] == "2026-10-03"

        # It ended before this one.
        answer = bound.answer(
            request, queryset, {"start": "2026-10-04", "end": "2026-11-01"}
        )

        assert answer["events"] == []

    def test_moving_keeps_the_time_and_the_length(
        self, admin_user, support_desk
    ):
        moved = bind_calendar(
            Calendar("probe", date="opened_at"),
            type("Probe", (ModelResource,), {})(Ticket, site),
        ).shifted(
            timezone.make_aware(datetime.datetime(2026, 10, 6, 14, 30)),
            datetime.timedelta(days=3),
        )

        assert moved.startswith("2026-10-09T14:30")


class TestDeclarations:
    def bind(self, *, editable_fields=(), **options):
        resource = type(
            "Probe", (ModelResource,), {"editable_fields": editable_fields}
        )(Ticket, site)

        return bind_calendar(Calendar(**options), resource)

    @pytest.mark.parametrize(
        "options, message",
        [
            ({"name": "Due", "date": "due_on"}, "lower case"),
            ({"name": "due", "date": "title"}, "not a date"),
            ({"name": "due", "date": "due_on", "end": "nope"}, "not a date"),
            ({"name": "due", "date": "due_on", "views": ("year",)}, "views"),
            ({"name": "due", "date": "due_on", "fields": "status"}, "tuple"),
            ({"name": "due", "date": "due_on", "color": "nope"}, "'nope'"),
            (
                {"name": "due", "date": "due_on", "editable": True},
                "editable_fields",
            ),
        ],
    )
    def test_mistakes_are_refused(self, options, message):
        with pytest.raises(ImproperlyConfigured, match=message):
            self.bind(**options)

    def test_editable_with_the_date_among_the_editable_fields(self):
        bound = self.bind(
            name="due",
            date="due_on",
            editable=True,
            editable_fields=("due_on",),
        )

        assert bound.definition.editable

    def test_the_widest_range(self):
        assert MAX_DAYS >= 42


ARRIVALS = "/api/example/ticket/calendars/arrivals/"


def at(day: int, hour: int, minute: int = 0) -> datetime.datetime:
    return timezone.make_aware(datetime.datetime(2026, 10, day, hour, minute))


class TestTheHours:
    """A calendar with ``hours``: records placed on the time of day."""

    def test_an_event_carries_its_wall_clock(self, admin_client, support_desk):
        Ticket.objects.filter(pk=support_desk["login"].pk).update(
            opened_at=at(6, 9, 30)
        )
        response = admin_client.get(
            ARRIVALS, {"start": "2026-10-05", "end": "2026-10-12"}
        )

        assert response.status_code == 200, response.content
        body = response.json()
        event = next(
            event
            for event in body["events"]
            if event["id"] == str(support_desk["login"].pk)
        )

        assert event["startsAt"] == "2026-10-06T09:30"
        assert event["endsAt"] == ""

    def test_the_page_carries_the_hours(self, admin_client, db):
        response = admin_client.get("/example/ticket/arrivals/")

        assert response.status_code == 200
        assert b"&quot;hours&quot;: [7, 20]" in response.content or (
            b'"hours": [7, 20]' in response.content
        )

    def test_a_moment_is_read_on_the_wall_clock(self):
        moment = parse_moment("2026-10-06T09:30", "start")

        assert wall_clock(moment) == "2026-10-06T09:30"

    @pytest.mark.parametrize("value", ["", "2026-10-06", "soon", None])
    def test_a_moment_without_its_time_is_refused(self, value):
        with pytest.raises(ValidationError):
            parse_moment(value, "start")


class TestMovingInTime:
    def bound(self, **options):
        resource = type(
            "Probe",
            (ModelResource,),
            {
                "list_display": ("reference", "opened_at", "due_on"),
                "editable_fields": ("opened_at", "due_on"),
            },
        )(Ticket, site)

        return bind_calendar(
            Calendar("probe", date="opened_at", editable=True, **options),
            resource,
        )

    def request(self, admin_user):
        request = RequestFactory().patch("/")
        request.user = admin_user

        return request

    def test_another_start(self, admin_user, support_desk):
        ticket = support_desk["login"]
        Ticket.objects.filter(pk=ticket.pk).update(opened_at=at(6, 9))
        ticket.refresh_from_db()
        self.bound(hours=(7, 20)).move(
            self.request(admin_user), ticket, {"start": "2026-10-07T14:15"}
        )
        ticket.refresh_from_db()

        assert ticket.opened_at == at(7, 14, 15)

    def test_an_end_where_there_is_none(self, admin_user, support_desk):
        ticket = support_desk["login"]

        with pytest.raises(ValidationError, match="no end"):
            self.bound(hours=(7, 20)).move(
                self.request(admin_user),
                ticket,
                {"end": "2026-10-07T14:15"},
            )

    def test_a_day_calendar_moves_by_the_day(self, admin_user, support_desk):
        ticket = support_desk["login"]
        Ticket.objects.filter(pk=ticket.pk).update(opened_at=at(6, 9))
        ticket.refresh_from_db()
        # No hours: "start" is not read, the day is.
        self.bound().move(
            self.request(admin_user), ticket, {"date": "2026-10-08"}
        )
        ticket.refresh_from_db()

        assert ticket.opened_at == at(8, 9)


class Timesheet(ModelResource):
    """Time entries laid on days, a ticket dropped on one logging an
    hour of it."""

    fields = ("ticket", "agent", "spent_on", "hours")

    def create_editable(self, request, values, fixed):
        from example.models import Agent

        fixed = {
            **fixed,
            "agent": Agent.objects.order_by("pk").first().pk,
            "hours": "1.00",
        }

        return super().create_editable(request, values, fixed)


class TestAllocating:
    def bound(self, **options):
        allocate = options.pop(
            "allocate",
            Allocate(
                "ticket",
                filters={
                    "match": "all",
                    "conditions": [
                        {
                            "column": "status",
                            "operator": "any_of",
                            "value": ["open"],
                        }
                    ],
                },
                fields=("team",),
                color="priority",
            ),
        )

        return bind_calendar(
            Calendar("days", date="spent_on", allocate=allocate, **options),
            Timesheet(TimeEntry, site),
        )

    def request(self, user, method="get"):
        request = getattr(RequestFactory(), method)("/")
        request.user = user

        return request

    def test_the_records_offered_are_the_filtered_ones(
        self, admin_user, support_desk
    ):
        answer = self.bound().sources(self.request(admin_user), {})

        assert [item["label"] for item in answer["items"]] == [
            str(support_desk["login"])
        ]
        item = answer["items"][0]
        assert item["url"]
        assert item["color"]
        assert item["cells"][0]["display"] == "Front office"
        assert answer["more"] is False

    def test_the_reader_s_search(self, admin_user, support_desk):
        bound = self.bound(allocate=Allocate("ticket", limit=1))
        request = self.request(admin_user)

        assert bound.sources(request, {"q": "blank"})["items"][0][
            "label"
        ] == str(support_desk["invoice"])
        # One at a time: more behind.
        assert bound.sources(request, {})["more"] is True
        assert len(bound.sources(request, {"page": "2"})["items"]) == 1

    def test_a_record_dropped_creates_one(self, admin_user, support_desk):
        ticket = support_desk["invoice"]
        entry = self.bound().allocate(
            self.request(admin_user, "post"),
            {"record": str(ticket.pk), "start": "2026-10-07"},
        )

        assert entry.ticket == ticket
        assert entry.spent_on == datetime.date(2026, 10, 7)

    def test_a_record_it_cannot_find(self, admin_user, support_desk):
        from rest_framework.exceptions import NotFound

        with pytest.raises(NotFound):
            self.bound().allocate(
                self.request(admin_user, "post"),
                {"record": "nope", "start": "2026-10-07"},
            )

    def test_refused_without_the_add_permission(
        self, django_user_model, support_desk
    ):
        from rest_framework.exceptions import PermissionDenied

        user = django_user_model.objects.create_user(username="reader")
        user.user_permissions.set(
            Permission.objects.filter(
                codename__in=["view_timeentry", "view_ticket"]
            )
        )
        bound = self.bound()

        assert not bound.can_allocate(self.request(user))

        with pytest.raises(PermissionDenied):
            bound.allocate(
                self.request(user, "post"),
                {
                    "record": str(support_desk["login"].pk),
                    "start": "2026-10-07",
                },
            )

    def test_the_page_is_told_how(self, admin_user, db):
        config = self.bound().get_allocate_config(self.request(admin_user))

        assert config["field"] == "ticket"
        assert config["url"].endswith("sources/")


class TestHourDeclarations:
    def bind(self, model=Ticket, **options):
        resource = type("Probe", (ModelResource,), {})(model, site)

        return bind_calendar(Calendar("probe", **options), resource)

    @pytest.mark.parametrize(
        "options, message",
        [
            ({"date": "opened_at", "hours": (20, 7)}, "two whole hours"),
            ({"date": "opened_at", "hours": (7,)}, "two whole hours"),
            ({"date": "due_on", "hours": (7, 20)}, "date-and-time"),
            ({"date": "opened_at", "step": 7}, "step"),
            ({"date": "opened_at", "allocate": 3}, "Allocate"),
            (
                {"date": "opened_at", "allocate": "title", "hours": (7, 20)},
                "not a foreign key",
            ),
            ({"date": "opened_at", "allocate": "customer"}, "hours="),
            (
                {
                    "date": "opened_at",
                    "hours": (7, 20),
                    "allocate": Allocate("customer", fields="name"),
                },
                "tuple",
            ),
            (
                {
                    "date": "opened_at",
                    "hours": (7, 20),
                    "allocate": Allocate("customer", duration=0),
                },
                "minutes",
            ),
        ],
    )
    def test_mistakes_are_refused(self, options, message):
        with pytest.raises(ImproperlyConfigured, match=message):
            self.bind(**options)

    def test_a_name_is_an_allocation(self):
        bound = self.bind(date="opened_at", hours=(7, 20), allocate="customer")

        assert bound.allocation == Allocate("customer")
        assert bound.hourly
