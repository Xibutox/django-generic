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

A calendar of dates and times may draw its week and its day as hours
(``hours=(8, 19)``): each record at its time, as tall as it lasts.
Records are then dragged to another time - snapped to ``step``
minutes - and their end dragged to make them longer or shorter; a
stretch of empty time selected opens the add form with the start and
the end filled in. With ``allocate``, records of a relation are listed
beside the calendar - the tasks a timesheet's entries point at - and
one dropped on a time creates a record pointing at it, there::

    @register(TimeEntry)
    class TimeEntryResource(ModelResource):
        editable_fields = ("started_at", "ended_at")
        calendars = (
            Calendar(
                "week",
                date="started_at",
                end="ended_at",
                hours=(8, 19),
                editable=True,
                allocate=Allocate("task", filters=OPEN_TASKS),
            ),
        )
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
VIEWS = ("month", "week", "day", "list")

#: The views of the default: a day is offered when asked for.
DEFAULT_VIEWS = ("month", "week", "list")

#: The minutes a record of an hourly calendar snaps to.
STEPS = (5, 10, 15, 20, 30, 60)

#: The most records of a relation the allocation panel lists at once.
MAX_SOURCES = 50


@dataclasses.dataclass(frozen=True)
class Allocate:
    """Records of a relation listed beside an hourly calendar, dropped
    on a time to create a record pointing at them there."""

    #: A foreign key of the calendar's model: the records listed are
    #: its related model's, through that model's registered resource.
    field: str
    #: The panel's heading. Default: the related model's plural.
    title: Any = None
    #: A filter tree over the related resource's list columns, as
    #: ``presets`` write it: which records are offered.
    filters: Any = None
    #: Their order; default the related resource's.
    ordering: Sequence[str] = ()
    #: Values shown on each, as its summary page shows them.
    fields: Sequence[str] = ()
    #: A tag field of the related resource: each takes its colour.
    color: str | None = None
    #: Minutes a dropped record lasts, when the calendar has an end.
    duration: int = 60
    #: Records listed a page at a time (at most ``MAX_SOURCES``).
    limit: int = 20


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
    views: Sequence[str] = DEFAULT_VIEWS
    #: An entry of the navigation, in the resource's group.
    navigation: bool = False
    #: Needed besides the resource's view permission (as a page's).
    permission: Any = None
    #: ``(first, last)`` hours drawn by the week and the day, a record
    #: at its time and as tall as it lasts: a date-and-time ``date``
    #: only. None: the week lists each day's records.
    hours: tuple[int, int] | None = None
    #: The minutes a record moved or stretched on the hours snaps to.
    step: int = 15
    #: ``Allocate(...)`` or a foreign key's name: records of that
    #: relation listed beside the hours, dropped on a time to create a
    #: record pointing at them.
    allocate: Any = None


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


def parse_moment(value: Any, name: str) -> datetime.datetime:
    """A date and time the browser sends - the reader's wall clock,
    ``YYYY-MM-DDTHH:MM`` - as the database compares it."""
    try:
        moment = datetime.datetime.fromisoformat(force_str(value or ""))
    except ValueError:
        moment = None

    if moment is None or len(force_str(value)) < 16:
        raise ValidationError(
            {name: [gettext("A date and time is expected.")]}
        )

    if timezone.is_naive(moment) and _uses_tz():
        moment = timezone.make_aware(moment)

    return moment


def wall_clock(value: Any) -> str:
    """``value`` as the reader's wall clock, to the minute - what the
    browser places on the hours: ``2026-10-07T09:30``."""
    if not isinstance(value, datetime.datetime):
        return ""

    if timezone.is_aware(value):
        value = timezone.localtime(value)

    return value.strftime("%Y-%m-%dT%H:%M")


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
        self.allocation = (
            Allocate(definition.allocate)
            if isinstance(definition.allocate, str)
            else definition.allocate
        )

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def timed(self) -> bool:
        return isinstance(self.date_field, models.DateTimeField)

    @property
    def hourly(self) -> bool:
        """The week and the day drawn as hours."""
        return bool(self.definition.hours) and self.timed

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
            # The reader's wall clock, placing the record on the hours.
            "startsAt": wall_clock(begins),
            "endsAt": wall_clock(ends),
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
        definition = self.definition
        locked = self.resource.get_locked_fields(request)

        return bool(
            definition.editable
            and self.resource.has_change_permission(request)
            and definition.date not in locked
            and (not definition.end or definition.end not in locked)
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

        if self.hourly and ("start" in data or "end" in data):
            self.move_in_time(request, obj, data)
            return

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

    def move_in_time(self, request: Any, obj: Any, data: dict) -> None:
        """Another start (the end moving with it, its length kept), or
        another end (longer or shorter), or both: ``{"start", "end"}``
        on the reader's wall clock."""
        definition = self.definition
        begins = getattr(obj, definition.date)
        ends = getattr(obj, definition.end) if definition.end else None
        changes: dict[str, Any] = {}
        start = begins

        if "start" in data:
            start = parse_moment(data.get("start"), "start")
            changes[definition.date] = start.isoformat()

            if (
                definition.end
                and ends is not None
                and begins is not None
                and "end" not in data
            ):
                changes[definition.end] = (ends + (start - begins)).isoformat()

        if "end" in data:
            if not definition.end:
                raise ValidationError(
                    {"end": [gettext("This calendar's records have no end.")]}
                )

            end = parse_moment(data.get("end"), "end")

            if start is not None and end <= start:
                raise ValidationError(
                    {"end": [gettext("The end must come after the start.")]}
                )

            changes[definition.end] = end.isoformat()

        if changes:
            self.resource.save_editable(request, obj, changes)

    # -- creating a record on a time -------------------------------------

    def related_resource(self) -> Any:
        """The registered resource of the allocated relation's model."""
        field = self.resource.model._meta.get_field(self.allocation.field)
        related = self.resource.site.get_resource(field.related_model)

        if related is None:
            raise ImproperlyConfigured(
                f"{type(self.resource).__name__}.calendars: '{self.name}' "
                f"allocates {field.related_model.__name__} records, which "
                f"have no registered resource."
            )

        return related

    def can_allocate(self, request: Any) -> bool:
        return bool(
            self.allocation is not None
            and self.resource.has_add_permission(request)
            and self.related_resource().has_view_permission(request)
        )

    def sources(self, request: Any, params: Any) -> dict[str, Any]:
        """The related records offered: the declared filters, the
        reader's search (``q``), a page at a time (``page``)."""
        from generic.api.filters import apply_search
        from generic.sites.dashboard import as_tree
        from generic.sites.summary import describe_entry, record_url

        allocation = self.allocation
        related = self.related_resource()

        if not related.has_view_permission(request):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied()

        queryset = related.get_list_queryset(request)
        tree = as_tree(allocation.filters)

        if tree is not None:
            from generic.api.filters import FilterTreeBuilder

            specs = related.get_table_serializer_class().get_filter_specs()
            condition = FilterTreeBuilder(specs, related.model).build(tree)

            if condition is not None:
                queryset = queryset.filter(condition)

        term = force_str(params.get("q") or "").strip()[:200]

        if term:
            queryset = apply_search(
                queryset,
                related.visible_paths(
                    request, related.get_search_fields(request)
                ),
                term,
            )

        ordering = list(allocation.ordering or related.get_ordering(request))

        if not {"pk", "-pk"} & set(ordering):
            ordering.append("pk")

        try:
            page = max(1, int(params.get("page") or 1))
        except (TypeError, ValueError):
            page = 1

        size = max(1, min(int(allocation.limit), MAX_SOURCES))
        offset = (page - 1) * size
        rows = list(
            queryset.order_by(*ordering).distinct()[offset : offset + size + 1]
        )
        items = []

        for row in rows[:size]:
            item = {
                "id": force_str(row.pk),
                "label": related.get_object_label(row),
                "url": record_url(related.site, request, row),
                "color": "",
                "background": "",
                "cells": [],
            }

            if allocation.color:
                tags = (
                    describe_entry(
                        related, request, row, allocation.color
                    ).get("items")
                    or []
                )

                if tags:
                    item["color"] = force_str(tags[0].get("color") or "")
                    item["background"] = force_str(
                        tags[0].get("background") or ""
                    )

            for name in allocation.fields:
                entry = describe_entry(related, request, row, name)
                entry.pop("wide", None)
                item["cells"].append(entry)

            items.append(item)

        return {"items": items, "more": len(rows) > size, "page": page}

    def allocate(self, request: Any, data: Any) -> Any:
        """Create a record on a time, pointing at the record dropped:
        ``{"record", "start", "end"?}``, through the resource's
        ``create_editable`` - the add form's serializer and
        ``save_model``."""
        from rest_framework.exceptions import NotFound, PermissionDenied

        if not self.can_allocate(request):
            raise PermissionDenied(
                gettext("Records are not created on this calendar.")
            )

        if not isinstance(data, dict):
            raise ValidationError(gettext("Send the record and the time."))

        definition = self.definition
        related = self.related_resource()
        key = force_str(data.get("record") or "")

        try:
            target = related.get_queryset(request).get(pk=key)
        except (related.model.DoesNotExist, ValueError, TypeError):
            raise NotFound(gettext("That record cannot be found.")) from None
        except Exception:  # a key the field cannot read: not one
            raise NotFound(gettext("That record cannot be found.")) from None

        start: datetime.date
        end: datetime.date

        if self.timed:
            start = parse_moment(data.get("start"), "start")
            end = (
                parse_moment(data.get("end"), "end")
                if data.get("end")
                else start
                + datetime.timedelta(minutes=int(self.allocation.duration))
            )

            if end <= start:
                raise ValidationError(
                    {"end": [gettext("The end must come after the start.")]}
                )
        else:
            start = parse_day(data.get("start"), "start")
            end = start

        fixed: dict[str, Any] = {
            definition.date: start.isoformat(),
            self.allocation.field: target.pk,
        }

        if definition.end:
            fixed[definition.end] = end.isoformat()

        return self.resource.create_editable(request, {}, fixed)

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
            "endField": self.definition.end or "",
            "topics": [resource.topic_name] if resource.realtime else [],
            "resource": resource.label_lower,
            # Drawn as hours: the week and the day, from the first hour
            # to the last, snapped to ``step`` minutes.
            "hours": (
                list(self.definition.hours or ()) if self.hourly else None
            ),
            "step": int(self.definition.step),
            "timed": self.timed,
            "now": wall_clock(timezone.now()) if self.timed else "",
            "allocate": self.get_allocate_config(request),
        }

    def get_allocate_config(self, request: Any) -> dict[str, Any] | None:
        """The panel of records to drop on the hours, for a reader who
        may create them."""
        if self.allocation is None or not self.can_allocate(request):
            return None

        related = self.related_resource()
        url = self.resource._reverse(
            self.resource.api_url_name("calendar-sources"),
            calendar=self.name,
        )

        return {
            "title": force_str(
                self.allocation.title or related.get_label_plural()
            ),
            "url": url,
            "createUrl": self.get_api_url(),
            "duration": int(self.allocation.duration),
            "field": self.allocation.field,
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
            bulkEdit={},
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

    check_hours(bound, name)

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


def check_hours(bound: BoundCalendar, name: str) -> None:
    """``hours``, ``step`` and ``allocate``: what they need."""
    definition = bound.definition
    hours = definition.hours

    if hours is not None:
        if (
            not isinstance(hours, (tuple, list))
            or len(hours) != 2
            or not all(isinstance(hour, int) for hour in hours)
            or not 0 <= hours[0] < hours[1] <= 24
        ):
            raise ImproperlyConfigured(
                f"{name}.calendars: the hours of '{definition.name}' are "
                f"(first, last), two whole hours from 0 to 24, the first "
                f"before the last - not {hours!r}."
            )

        if not bound.timed:
            raise ImproperlyConfigured(
                f"{name}.calendars: '{definition.name}' draws hours, so "
                f"its date, '{definition.date}', must be a date-and-time "
                f"field."
            )

    if definition.step not in STEPS:
        raise ImproperlyConfigured(
            f"{name}.calendars: the step of '{definition.name}' is one of "
            f"{', '.join(str(step) for step in STEPS)} minutes."
        )

    allocation = bound.allocation

    if allocation is None:
        return

    if not isinstance(allocation, Allocate):
        raise ImproperlyConfigured(
            f"{name}.calendars: the allocate of '{definition.name}' is "
            f"Allocate(...) or a foreign key's name."
        )

    try:
        field = bound.resource.model._meta.get_field(allocation.field)
    except FieldDoesNotExist:
        field = None

    if not isinstance(field, models.ForeignKey):
        raise ImproperlyConfigured(
            f"{name}.calendars: '{definition.name}' allocates through "
            f"'{allocation.field}', which is not a foreign key of "
            f"{bound.resource.model.__name__}."
        )

    if bound.timed and not bound.hourly:
        raise ImproperlyConfigured(
            f"{name}.calendars: '{definition.name}' allocates on a date "
            f"and time, so it draws hours: give it hours=(first, last)."
        )

    if isinstance(allocation.fields, str):
        raise ImproperlyConfigured(
            f"{name}.calendars: the fields of '{definition.name}''s "
            f"allocate are a tuple of names, not one string."
        )

    if not isinstance(allocation.duration, int) or allocation.duration < 1:
        raise ImproperlyConfigured(
            f"{name}.calendars: the duration of '{definition.name}''s "
            f"allocate is a number of minutes."
        )

    try:
        from generic.sites.dashboard import as_tree

        as_tree(allocation.filters)
    except TypeError:
        raise ImproperlyConfigured(
            f"{name}.calendars: the filters of '{definition.name}''s "
            f"allocate are a filter tree (a dict, as presets write it)."
        ) from None


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
    "Allocate",
    "BoundCalendar",
    "Calendar",
    "CalendarPageView",
    "MAX_DAYS",
    "bind_calendar",
]
