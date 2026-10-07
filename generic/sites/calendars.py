"""Records on a calendar: a month, a week, or a list of days.

Declared on the resource of the records, naming the date they fall on::

    @register(Ticket)
    class TicketResource(ModelResource):
        editable_fields = ("due_on", ...)
        calendars = (
            Calendar(
                "due",
                date="due_on",
                title=_("Due dates"),
                color="priority",
                fields=("customer", "status"),
                editable=True,
            ),
        )

    @register(Booking)
    class BookingResource(ModelResource):
        calendars = (Calendar("plan", date="starts_at", end="ends_at"),)

Each calendar is a page of the resource, ``<model>/<name>/``, with a
button on the list. The resource's own table sits above it, rows
hidden: its search box and filter editor choose what the calendar
shows, exactly as they would choose the rows of the list. A record
spanning several days (``end``) is drawn on each of them.

The browser asks for a range of days - never more than
``MAX_DAYS`` - and the endpoint, ``GET api/<app>/<model>/calendars/
<name>/?start=&end=``, answers the records of that range through the
resource's list queryset and the table's filter backends; a reader is
never shown a record the list would not show them.

With ``editable``, a record dragged to another day is written through
the table's own cell writer (``save_editable``): the date must be one
of the resource's ``editable_fields``, and the change permission, the
per-row ``can_edit_column`` and the form's validation all apply. A
date and time keeps its time; an end moves with its start.
"""

from __future__ import annotations

import dataclasses
import datetime
import re
from typing import Any, Sequence

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.db.models import Q
from django.utils import formats, timezone
from django.utils.encoding import force_str
from django.utils.translation import gettext, gettext_lazy
from rest_framework.exceptions import ValidationError

from generic.sites.dashboard import check_entry
from generic.sites.pages import ResourcePage, ResourcePageView

#: A calendar's name is a piece of its endpoint's address and its page's.
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: The widest range one request may ask for: six weeks and then some.
MAX_DAYS = 62

#: The most records one range answers; past it, ``truncated``.
MAX_EVENTS = 2000

#: How a calendar may be looked at.
VIEWS = ("month", "week", "list")


@dataclasses.dataclass(frozen=True)
class Calendar:
    """Declare one calendar of the resource's records."""

    #: Lower case letters, digits and dashes: the page is ``<name>/``.
    name: str
    #: The date the record falls on: a date or a date-and-time field.
    date: str
    #: The day it ends, included - the same kind of field. None: one
    #: day.
    end: str | None = None
    title: Any = None
    icon: str = "calendar_month"
    description: Any = ""
    #: The event's text: a field, a resource method or a model
    #: attribute. Default: the record's label.
    label: str | None = None
    #: Where its colour comes from: a field (or a ``tags=`` method) the
    #: resource draws as coloured tags - its first tag's colour.
    color: str | None = None
    #: Values shown with the event, as a summary page shows them.
    fields: Sequence[str] = ()
    #: Records dragged to another day are written - see the module.
    editable: bool = False
    #: Offered ways of looking, the first one opening.
    views: Sequence[str] = VIEWS
    #: An entry of the navigation, in the resource's group.
    navigation: bool = False
    #: Needed besides the resource's view permission (as a page's).
    permission: Any = None


def date_field(resource: Any, name: str, role: str, calendar: str) -> Any:
    """``name``, a date or date-and-time field of the model, or a
    refusal naming the declaration."""
    try:
        field = resource.model._meta.get_field(name)
    except FieldDoesNotExist:
        field = None

    if not isinstance(field, models.DateField):
        raise ImproperlyConfigured(
            f"{type(resource).__name__}.calendars: the {role} of "
            f"'{calendar}', '{name}', is not a date or date-and-time "
            f"field of {resource.model.__name__}."
        )

    return field


def parse_day(value: Any, name: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(force_str(value or ""))
    except ValueError:
        raise ValidationError(
            {name: [gettext("A date is expected (YYYY-MM-DD).")]}
        ) from None


def start_of(day: datetime.date) -> datetime.datetime:
    """The first instant of ``day``, in the active time zone."""
    moment = datetime.datetime.combine(day, datetime.time.min)

    if timezone.is_naive(moment) and _uses_tz():
        moment = timezone.make_aware(moment)

    return moment


def _uses_tz() -> bool:
    from django.conf import settings

    return bool(settings.USE_TZ)


def local_day(value: Any) -> datetime.date:
    """The day a stored value falls on, for the reader."""
    if isinstance(value, datetime.datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)

        return value.date()

    return value


class BoundCalendar:
    """A calendar resolved against its resource."""

    def __init__(self, definition: Calendar, resource: Any) -> None:
        self.definition = definition
        self.resource = resource
        self.date_field = date_field(
            resource, definition.date, "date", definition.name
        )
        self.end_field = (
            date_field(resource, definition.end, "end", definition.name)
            if definition.end
            else None
        )

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def timed(self) -> bool:
        return isinstance(self.date_field, models.DateTimeField)

    def get_title(self) -> str:
        return force_str(self.definition.title or gettext("Calendar"))

    # -- the records of a range ----------------------------------------

    def bound(self, day: datetime.date) -> Any:
        """``day``'s first instant, as the date field compares."""
        return start_of(day) if self.timed else day

    def in_range(self, start: datetime.date, stop: datetime.date) -> Q:
        """Records on a day of ``[start, stop)``: starting before it
        ends, and ending - or, without an end, starting - after it
        starts."""
        date = self.definition.date
        low, high = self.bound(start), self.bound(stop)
        starts_before = Q(**{f"{date}__lt": high})

        if self.end_field is None:
            return starts_before & Q(**{f"{date}__gte": low})

        end = self.definition.end
        end_low = (
            start_of(start)
            if isinstance(self.end_field, models.DateTimeField)
            else start
        )

        return starts_before & (
            Q(**{f"{end}__gte": end_low})
            | (Q(**{f"{end}__isnull": True}) & Q(**{f"{date}__gte": low}))
        )

    def read_range(self, params: Any) -> tuple[datetime.date, datetime.date]:
        start = parse_day(params.get("start"), "start")
        stop = parse_day(params.get("end"), "end")

        if stop <= start:
            raise ValidationError(
                {"end": [gettext("The end must come after the start.")]}
            )

        if (stop - start).days > MAX_DAYS:
            raise ValidationError(
                {
                    "end": [
                        gettext("At most %(days)s days at a time.")
                        % {"days": MAX_DAYS}
                    ]
                }
            )

        return start, stop

    def answer(
        self, request: Any, queryset: Any, params: Any
    ) -> dict[str, Any]:
        """The records of the asked range, as events.

        ``queryset`` is the list's, the table's filters applied.
        """
        start, stop = self.read_range(params)
        date = self.definition.date
        rows = list(
            queryset.filter(self.in_range(start, stop)).order_by(date, "pk")[
                : MAX_EVENTS + 1
            ]
        )
        truncated = len(rows) > MAX_EVENTS
        editable = self.can_move(request)

        return {
            "start": start.isoformat(),
            "end": stop.isoformat(),
            "truncated": truncated,
            "editable": editable,
            "events": [
                self.describe(request, row, editable)
                for row in rows[:MAX_EVENTS]
            ],
        }

    def describe(self, request: Any, obj: Any, editable: bool) -> dict:
        from generic.sites.summary import describe_entry, record_url

        definition = self.definition
        begins = getattr(obj, definition.date)
        ends = getattr(obj, definition.end) if definition.end else None
        first = local_day(begins)
        last = local_day(ends) if ends is not None else first

        if last < first:
            last = first

        label = self.resource.get_object_label(obj)

        if definition.label:
            entry = describe_entry(
                self.resource, request, obj, definition.label
            )
            label = force_str(entry.get("display") or label)

        event = {
            "id": force_str(obj.pk),
            "label": label,
            "url": record_url(self.resource.site, request, obj),
            "start": first.isoformat(),
            "end": last.isoformat(),
            "time": (
                formats.time_format(
                    (
                        timezone.localtime(begins)
                        if timezone.is_aware(begins)
                        else begins
                    ),
                    "TIME_FORMAT",
                )
                if isinstance(begins, datetime.datetime)
                else ""
            ),
            "color": "",
            "background": "",
            "cells": [],
            "editable": editable,
        }

        if definition.color:
            entry = describe_entry(
                self.resource, request, obj, definition.color
            )
            items = entry.get("items") or []

            if items:
                event["color"] = force_str(items[0].get("color") or "")
                event["background"] = force_str(
                    items[0].get("background") or ""
                )

        for name in definition.fields:
            entry = describe_entry(self.resource, request, obj, name)
            entry.pop("wide", None)
            event["cells"].append(entry)

        return event

    # -- moving a record -------------------------------------------------

    def can_move(self, request: Any) -> bool:
        return bool(
            self.definition.editable
            and self.resource.has_change_permission(request)
        )

    def move(self, request: Any, obj: Any, data: Any) -> None:
        """Put ``obj`` on another day, through the cell writer."""
        if not self.can_move(request):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                gettext("Records of this calendar are not moved here.")
            )

        if not isinstance(data, dict):
            raise ValidationError(gettext("Send the day to move it to."))

        day = parse_day(data.get("date"), "date")
        definition = self.definition
        begins = getattr(obj, definition.date)

        if begins is None:
            raise ValidationError(
                {"date": [gettext("This record has no date to move.")]}
            )

        delta = day - local_day(begins)
        changes = {definition.date: self.shifted(begins, delta)}

        if definition.end:
            ends = getattr(obj, definition.end)

            if ends is not None:
                changes[definition.end] = self.shifted(ends, delta)

        self.resource.save_editable(request, obj, changes)

    @staticmethod
    def shifted(value: Any, delta: datetime.timedelta) -> str:
        """``value`` moved by whole days, as a form would send it: a
        date and time keeps its time of day, in the reader's zone."""
        if isinstance(value, datetime.datetime):
            if timezone.is_aware(value):
                value = timezone.localtime(value)
                moved = timezone.make_aware(
                    (value + delta).replace(tzinfo=None)
                )
            else:
                moved = value + delta

            return moved.isoformat()

        return (value + delta).isoformat()

    # -- where it shows --------------------------------------------------

    def get_api_url(self) -> str:
        return self.resource._reverse(
            self.resource.api_url_name("calendar"), calendar=self.name
        )

    def get_move_url_template(self) -> str:
        from generic.sites.resources import PK_PLACEHOLDER

        url = self.resource._reverse(
            self.resource.api_url_name("calendar-move"),
            pk=PK_PLACEHOLDER,
            calendar=self.name,
        )

        return url.replace(PK_PLACEHOLDER, "{id}") if url else ""

    def get_page_url(self) -> str:
        return self.resource.get_page_url(self.name)

    def get_config(self, request: Any) -> dict[str, Any]:
        """What the browser needs to draw the calendar."""
        resource = self.resource
        first_day = formats.get_format("FIRST_DAY_OF_WEEK")

        return {
            "name": self.name,
            "url": self.get_api_url(),
            "moveUrl": (
                self.get_move_url_template() if self.can_move(request) else ""
            ),
            "views": list(self.definition.views),
            "firstDay": int(first_day or 0),
            "today": timezone.localdate().isoformat(),
            "maxDays": MAX_DAYS,
            # The id of a table whose filters choose the records.
            "filterTable": None,
            "label": resource.get_label(),
            "labelPlural": resource.get_label_plural(),
            "addUrl": (
                resource.get_add_url()
                if resource.has_add_permission(request)
                else ""
            ),
            "dateField": self.definition.date,
            "topics": [resource.topic_name] if resource.realtime else [],
            "resource": resource.label_lower,
        }

    def get_filter_table_config(self, request: Any) -> dict[str, Any]:
        """The resource's own table, for its filter editor and search
        box: the calendar shows the records they select. Its rows are
        not shown."""
        return self.resource.get_page_table_config(
            request,
            f"calendar-{self.name}",
            pageLength=10,
            lengthMenu=[10],
            stateSave=False,
            columnSelector=False,
            filterRow=False,
            excel=False,
            csv=False,
            copy=False,
            print=False,
            rowActions=[],
            bulkActions=[],
            presets={},
            mailingUrl="",
            savedViewsUrl="",
            realtimeTopic="",
        )


def bind_calendar(definition: Any, resource: Any) -> BoundCalendar:
    name = type(resource).__name__

    if not isinstance(definition, Calendar):
        raise ImproperlyConfigured(
            f"{name}.calendars holds {definition!r}, which is not a "
            f"Calendar(...)."
        )

    if not isinstance(definition.name, str) or not NAME_PATTERN.match(
        definition.name
    ):
        raise ImproperlyConfigured(
            f"{name}.calendars: calendar name {definition.name!r} must be "
            f"lower case letters, digits and dashes - it is part of an "
            f"address."
        )

    bound = BoundCalendar(definition, resource)
    views = tuple(definition.views or ())

    if not views or any(view not in VIEWS for view in views):
        raise ImproperlyConfigured(
            f"{name}.calendars: the views of '{definition.name}' are "
            f"among {', '.join(VIEWS)}."
        )

    if isinstance(definition.fields, str):
        raise ImproperlyConfigured(
            f"{name}.calendars: the fields of '{definition.name}' are a "
            f"tuple of names, not one string."
        )

    for entry in (
        *([definition.label] if definition.label else ()),
        *([definition.color] if definition.color else ()),
        *definition.fields,
    ):
        check_entry(resource, "calendars", entry)

    if definition.editable:
        editable = set(resource.editable_fields or ())
        missing = [
            field
            for field in (definition.date, definition.end)
            if field and field not in editable
        ]

        if missing:
            raise ImproperlyConfigured(
                f"{name}.calendars: '{definition.name}' moves records "
                f"(editable=True), so {', '.join(missing)} must be in "
                f"{name}.editable_fields - the writer it goes through."
            )

    return bound


def calendar_page(bound: BoundCalendar) -> ResourcePage:
    return ResourcePage(
        bound.name,
        view=CalendarPageView,
        title=bound.definition.title or gettext_lazy("Calendar"),
        icon=bound.definition.icon,
        description=bound.definition.description,
        navigation=bound.definition.navigation,
        permission=bound.definition.permission,
    )


class CalendarPageView(ResourcePageView):
    """The page of a calendar, its filters above it."""

    template_name = "generic/resource/calendar.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        bound = self.resource.get_calendar(self.page.name)
        context["calendar"] = bound
        context["calendar_config"] = bound.get_config(self.request)
        context["calendar_config"]["filterTable"] = "calendar-filter-table"
        context["filter_table"] = bound.get_filter_table_config(self.request)

        return context


__all__ = [
    "BoundCalendar",
    "Calendar",
    "CalendarPageView",
    "MAX_DAYS",
    "bind_calendar",
]
