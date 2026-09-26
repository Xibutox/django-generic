"""Pages of the example's own, beside the ones its resources generate.

Declared on the resources (resources.py) - ``@page`` methods, or
``ResourcePage(..., view=...)`` for a view of their own - and written
here: the framework mounts them at the resource's address, checks who
may open them, finds the record, and draws the frame. What they show is
the project's, and deliberately unlike anything generated:

- the customers on a map (``CustomerResource.map``), and the same as
  GeoJSON for another tool (``CustomerResource.geojson``);
- a ticket's timeline (``TicketTimelineView``): opened, commented,
  worked on, changed, due, in one column;
- a service's runbook, a long text on a page of its own
  (``ServiceResource.runbook``).
"""

from __future__ import annotations

import datetime
import math
from typing import Any, Iterable

from django.utils import formats, timezone
from django.utils.translation import pgettext

from generic.history.reading import build_history
from generic.sites import ResourcePageView

# ---------------------------------------------------------------------
# The customers on a map
# ---------------------------------------------------------------------
#
# No tiles and no library: a map a support desk needs is where its
# customers are, and a drawing of the country does that. Latitude and
# longitude come from the city, which is all a customer records.

#: Latitude, longitude.
CITIES: dict[str, tuple[float, float]] = {
    "Basel": (47.56, 7.59),
    "Bordeaux": (44.84, -0.58),
    "Grenoble": (45.19, 5.72),
    "Lille": (50.63, 3.06),
    "Lyon": (45.76, 4.84),
    "Marseille": (43.30, 5.37),
    "Montpellier": (43.61, 3.88),
    "Nantes": (47.22, -1.55),
    "Nice": (43.71, 7.26),
    "Paris": (48.86, 2.35),
    "Rennes": (48.12, -1.68),
    "Strasbourg": (48.57, 7.75),
    "Toulouse": (43.60, 1.44),
}

#: Mainland France, coarsely: longitude, latitude, clockwise from
#: Dunkirk. A schematic, not a survey.
FRANCE: tuple[tuple[float, float], ...] = (
    (2.54, 51.09),
    (3.20, 50.75),
    (4.15, 50.30),
    (4.85, 50.15),
    (5.40, 49.60),
    (6.30, 49.50),
    (7.10, 49.15),
    (8.20, 48.97),
    (7.60, 47.60),
    (7.00, 47.45),
    (6.10, 46.45),
    (6.95, 46.05),
    (7.00, 45.30),
    (6.60, 44.90),
    (7.00, 44.20),
    (7.55, 43.78),
    (6.90, 43.45),
    (6.20, 43.10),
    (5.30, 43.20),
    (4.80, 43.40),
    (4.00, 43.55),
    (3.20, 43.10),
    (3.10, 42.45),
    (1.70, 42.50),
    (0.70, 42.80),
    (-0.30, 42.80),
    (-1.35, 43.05),
    (-1.78, 43.37),
    (-1.45, 43.80),
    (-1.25, 44.60),
    (-1.20, 45.60),
    (-1.10, 46.20),
    (-2.00, 46.80),
    (-2.30, 47.20),
    (-3.00, 47.50),
    (-4.20, 47.80),
    (-4.70, 48.00),
    (-4.75, 48.40),
    (-4.00, 48.70),
    (-3.00, 48.80),
    (-2.00, 48.65),
    (-1.55, 48.65),
    (-1.60, 49.65),
    (-1.20, 49.40),
    (0.10, 49.45),
    (0.60, 49.85),
    (1.50, 50.20),
    (1.60, 50.90),
)

WEST, EAST, SOUTH, NORTH = -5.2, 8.6, 42.2, 51.3
#: Pixels per degree of latitude, and the margin around the drawing.
SCALE = 60
MARGIN = 20
#: A degree of longitude is shorter than one of latitude this far north.
SQUEEZE = math.cos(math.radians((SOUTH + NORTH) / 2))


def project(latitude: float, longitude: float) -> tuple[float, float]:
    """A point of the drawing, in pixels."""
    x = MARGIN + (longitude - WEST) * SQUEEZE * SCALE
    y = MARGIN + (NORTH - latitude) * SCALE

    return round(x, 1), round(y, 1)


WIDTH = round(2 * MARGIN + (EAST - WEST) * SQUEEZE * SCALE)
HEIGHT = round(2 * MARGIN + (NORTH - SOUTH) * SCALE)


def customer_map(resource: Any, customers: Iterable[Any]) -> dict[str, Any]:
    """What the map page draws: the country, a bubble per customer
    sized by its open tickets, and those it cannot place."""
    markers = []
    unplaced = []
    per_city: dict[str, int] = {}

    for customer in customers:
        where = CITIES.get(customer.city)
        opened = getattr(customer, "open_ticket_count", 0)

        if where is None:
            unplaced.append(customer)
            continue

        x, y = project(*where)
        # Two customers of one city side by side, not one on the other.
        rank = per_city.get(customer.city, 0)
        per_city[customer.city] = rank + 1
        x += rank * 18

        markers.append(
            {
                "name": customer.name,
                "city": customer.city,
                "segment": customer.segment,
                "segment_label": customer.get_segment_display(),
                "open": opened,
                "url": resource.get_object_url(customer.pk),
                "x": x,
                "y": y,
                "r": round(6 + 3 * math.sqrt(opened), 1),
                # Against the eastern edge - Basel - the name goes to the
                # left, where it has room.
                "anchor": "end" if x > WIDTH * 0.82 else "start",
            }
        )

    for marker in markers:
        offset = marker["r"] + 5
        marker["label_x"] = (
            marker["x"] - offset
            if marker["anchor"] == "end"
            else marker["x"] + offset
        )

    # The key: every segment the model knows, with how many are drawn.
    segments = [
        {
            "value": value,
            "label": label,
            "count": sum(
                1 for marker in markers if marker["segment"] == value
            ),
        }
        for value, label in resource.model.Segment.choices
    ]

    return {
        "width": WIDTH,
        "height": HEIGHT,
        "outline": " ".join(
            "{},{}".format(*project(latitude, longitude))
            for longitude, latitude in FRANCE
        ),
        "markers": markers,
        "unplaced": unplaced,
        "segments": segments,
    }


def customers_geojson(
    resource: Any,
    request: Any,
    customers: Iterable[Any],
) -> dict[str, Any]:
    """The same customers as a GeoJSON feature collection."""
    features = []

    for customer in customers:
        where = CITIES.get(customer.city)

        if where is None:
            continue

        latitude, longitude = where
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [longitude, latitude],
                },
                "properties": {
                    "name": customer.name,
                    "code": customer.code,
                    "city": customer.city,
                    "segment": customer.segment,
                    "open_tickets": getattr(customer, "open_ticket_count", 0),
                    "url": request.build_absolute_uri(
                        resource.get_object_url(customer.pk)
                    ),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------
# A ticket's timeline
# ---------------------------------------------------------------------


def day_end(day: datetime.date) -> datetime.datetime:
    """A day with no time - hours logged on it - placed after whatever
    else happened that day: the work follows what it was for."""
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(23, 59))
    )


class TicketTimelineView(ResourcePageView):
    """Everything that happened to a ticket, oldest first.

    A view of its own rather than a ``@page`` method, to show that way:
    declared with ``ResourcePage("timeline", view=TicketTimelineView,
    detail=True)``, it gets ``self.resource``, ``self.page`` and the
    ticket as ``self.object`` - already found, already allowed - and
    does what any ``TemplateView`` does.
    """

    template_name = "example/pages/ticket_timeline.html"

    def get_events(self) -> list[dict[str, Any]]:
        ticket = self.object
        events = [
            {
                "kind": "opened",
                "icon": "add_circle",
                "at": ticket.opened_at,
                "title": pgettext("ticket timeline", "Opened"),
                "who": ticket.customer.name if ticket.customer else "",
                "text": ticket.description,
            }
        ]

        for comment in ticket.comments.all():
            events.append(
                {
                    "kind": "comment",
                    "icon": "chat",
                    "at": comment.created_at,
                    "title": pgettext("ticket timeline", "Comment"),
                    "who": comment.author,
                    "text": comment.body,
                }
            )

        for entry in ticket.time_entries.select_related("agent"):
            hours = formats.number_format(entry.hours, decimal_pos=2)
            events.append(
                {
                    "kind": "time",
                    "icon": "schedule",
                    "at": day_end(entry.spent_on),
                    "day_only": True,
                    "title": pgettext("ticket timeline", "%(hours)s h logged")
                    % {"hours": hours},
                    "who": entry.agent.name,
                    "text": entry.note,
                }
            )

        # The changes the history recorded - not the first version,
        # which is the ticket being opened, already above.
        history = build_history(self.resource, self.request, ticket, limit=100)

        for entry in history["results"]:
            if not (entry["changes"] and entry["at"]):
                continue

            events.append(
                {
                    "kind": "change",
                    "icon": "edit",
                    "at": datetime.datetime.fromisoformat(entry["at"]),
                    "title": pgettext("ticket timeline", "Changed"),
                    "who": entry["who"],
                    "changes": entry["changes"],
                }
            )

        if ticket.due_on:
            events.append(
                {
                    "kind": "due",
                    "icon": "event",
                    "at": day_end(ticket.due_on),
                    "day_only": True,
                    "title": pgettext("ticket timeline", "Due"),
                    "upcoming": ticket.due_on >= timezone.localdate(),
                }
            )

        return sorted(events, key=lambda event: event["at"])

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["ticket"] = self.object
        context["events"] = self.get_events()

        return context
