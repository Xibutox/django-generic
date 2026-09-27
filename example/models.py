"""A small support desk.

Chosen because it needs every field type the framework renders: text,
choices, booleans, decimals, floats, dates, timestamps, URLs, a
nullable foreign key, a many-to-many and child collections - and
because its records have many related records each, which is what the
summary pages are for: a customer has hundreds of tickets, a ticket
dozens of time entries.

The delete rules are deliberate too:

* ``Ticket.team`` is PROTECT, so deleting a team that still has tickets
  is refused - which is what the delete page has to explain.
* ``TicketComment.ticket`` is CASCADE, so deleting a ticket takes its
  comments with it - which is what the delete page has to preview.
"""

from __future__ import annotations

from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy
from django_fsm import FSMField, transition


class Team(models.Model):
    name = models.CharField(_("name"), max_length=80, unique=True)
    code = models.CharField(_("code"), max_length=10, unique=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = _("team")
        verbose_name_plural = _("teams")

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("example:team-detail", kwargs={"pk": self.pk})


class Agent(models.Model):
    name = models.CharField(_("name"), max_length=80)
    email = models.EmailField(_("email"), blank=True, default="")
    team = models.ForeignKey(
        Team,
        verbose_name=_("team"),
        on_delete=models.CASCADE,
        related_name="agents",
    )
    is_active = models.BooleanField(_("active"), default=True)
    hired_on = models.DateField(_("hired on"), null=True, blank=True)
    capacity_hours = models.DecimalField(
        _("weekly capacity"),
        max_digits=5,
        decimal_places=2,
        default=35,
        help_text=_("Hours available per week."),
    )

    class Meta:
        ordering = ("name",)
        verbose_name = _("agent")
        verbose_name_plural = _("agents")

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("example:agent-detail", kwargs={"pk": self.pk})


class Customer(models.Model):
    """A company the desk works for: many tickets, much time spent."""

    class Segment(models.TextChoices):
        ENTERPRISE = "enterprise", _("Enterprise")
        SMALL = "small", _("Small business")
        PUBLIC = "public", _("Public sector")

    name = models.CharField(_("name"), max_length=120, unique=True)
    code = models.CharField(_("code"), max_length=12, unique=True)
    segment = models.CharField(
        _("segment"),
        max_length=12,
        choices=Segment.choices,
        default=Segment.SMALL,
    )
    city = models.CharField(_("city"), max_length=80, blank=True, default="")
    website = models.URLField(_("website"), blank=True, default="")
    account_manager = models.ForeignKey(
        Agent,
        verbose_name=_("account manager"),
        on_delete=models.SET_NULL,
        related_name="accounts",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(_("active"), default=True)
    customer_since = models.DateField(
        _("customer since"), null=True, blank=True
    )
    notes = models.TextField(_("notes"), blank=True, default="")

    class Meta:
        ordering = ("name",)
        verbose_name = _("customer")
        verbose_name_plural = _("customers")

    def __str__(self) -> str:
        return self.name


class Tag(models.Model):
    """A label with its own colours, drawn as a coloured tag."""

    name = models.CharField(_("name"), max_length=40, unique=True)
    # Either one colour, which tints the tag, or a background with the
    # text colour over it: both ways of drawing a tag are shown.
    color = models.CharField(
        _("colour"),
        max_length=30,
        blank=True,
        default="",
        help_text=_("Alone, the colour the tag is tinted with."),
    )
    background = models.CharField(
        _("background"),
        max_length=30,
        blank=True,
        default="",
        help_text=_("Draws the tag on this colour, the text in 'colour'."),
    )

    class Meta:
        ordering = ("name",)
        verbose_name = _("tag")
        verbose_name_plural = _("tags")

    def __str__(self) -> str:
        return self.name


class Ticket(models.Model):
    # These labels carry a context: "Open" as a state and "Open" as the
    # framework's row action are one word in English and two in most
    # other languages, and a catalog is keyed on the word alone.
    class Priority(models.TextChoices):
        LOW = "low", pgettext_lazy("ticket priority", "Low")
        NORMAL = "normal", pgettext_lazy("ticket priority", "Normal")
        HIGH = "high", pgettext_lazy("ticket priority", "High")
        URGENT = "urgent", pgettext_lazy("ticket priority", "Urgent")

    class Status(models.TextChoices):
        OPEN = "open", pgettext_lazy("ticket status", "Open")
        PENDING = "pending", pgettext_lazy("ticket status", "Pending")
        RESOLVED = "resolved", pgettext_lazy("ticket status", "Resolved")
        CLOSED = "closed", pgettext_lazy("ticket status", "Closed")

    reference = models.CharField(_("reference"), max_length=12, unique=True)
    title = models.CharField(_("title"), max_length=200)
    description = models.TextField(_("description"), blank=True, default="")
    # A file of the customer's: chosen on the ticket's form, downloaded
    # from its page through the ticket's own endpoint - never from a
    # public folder. The extensions become the chooser's filter.
    attachment = models.FileField(
        _("attachment"),
        upload_to="tickets/%Y/%m/",
        blank=True,
        validators=[
            FileExtensionValidator(
                ["pdf", "png", "jpg", "jpeg", "txt", "csv", "xlsx"]
            )
        ],
    )

    # PROTECT: the delete page has to explain why a busy team cannot go.
    team = models.ForeignKey(
        Team,
        verbose_name=_("team"),
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    assignee = models.ForeignKey(
        Agent,
        verbose_name=_("assignee"),
        on_delete=models.SET_NULL,
        related_name="tickets",
        null=True,
        blank=True,
    )
    customer = models.ForeignKey(
        Customer,
        verbose_name=_("customer"),
        on_delete=models.SET_NULL,
        related_name="tickets",
        null=True,
        blank=True,
    )
    tags = models.ManyToManyField(
        Tag,
        verbose_name=_("tags"),
        related_name="tickets",
        blank=True,
    )

    priority = models.CharField(
        _("priority"),
        max_length=10,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    # A state machine: the status moves through the transitions below,
    # which the ticket's page offers as buttons and the list as bulk
    # actions (TicketResource.transitions) - never through a form.
    status = FSMField(
        _("status"),
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
    )
    resolution = models.TextField(
        _("resolution"),
        blank=True,
        default="",
        help_text=_("What was done, written when the ticket is resolved."),
    )

    is_billable = models.BooleanField(_("billable"), default=False)
    estimated_hours = models.DecimalField(
        _("estimated hours"),
        max_digits=6,
        decimal_places=2,
        default=0,
    )
    satisfaction = models.FloatField(
        _("satisfaction"),
        null=True,
        blank=True,
        help_text=_("Score out of 5, once the ticket is closed."),
    )

    opened_at = models.DateTimeField(_("opened at"), default=timezone.now)
    due_on = models.DateField(_("due on"), null=True, blank=True)

    class Meta:
        ordering = ("-opened_at", "-pk")
        verbose_name = _("ticket")
        verbose_name_plural = _("tickets")
        permissions = [("reopen_ticket", _("Can reopen a ticket"))]

    def __str__(self) -> str:
        return f"{self.reference} - {self.title}"

    # -- the life of a ticket ----------------------------------------------

    @transition(
        field=status,
        source=Status.OPEN,
        target=Status.PENDING,
        custom={"label": _("Wait for the customer"), "icon": "hourglass_top"},
    )
    def wait(self) -> None:
        """The desk asked the customer something."""

    @transition(
        field=status,
        source=Status.PENDING,
        target=Status.OPEN,
        custom={"label": _("Customer answered"), "icon": "reply"},
    )
    def resume(self) -> None:
        """Back on the desk's side."""

    @transition(
        field=status,
        source=[Status.OPEN, Status.PENDING],
        target=Status.RESOLVED,
        custom={
            "label": _("Resolve"),
            "icon": "task_alt",
            "fields": ("resolution",),
        },
    )
    def resolve(self) -> None:
        """Done, and said how: the resolution is asked first."""

    @transition(
        field=status,
        source=[Status.OPEN, Status.PENDING, Status.RESOLVED],
        target=Status.CLOSED,
        custom={
            "label": _("Close"),
            "icon": "lock",
            "confirm": _("Close this ticket?"),
        },
    )
    def close(self) -> None:
        """Nothing more to do."""

    @transition(
        field=status,
        source=[Status.RESOLVED, Status.CLOSED],
        target=Status.OPEN,
        permission="example.reopen_ticket",
        custom={
            "label": _("Reopen"),
            "icon": "undo",
            "confirm": _("Reopen this ticket?"),
            "variant": "danger",
        },
    )
    def reopen(self) -> None:
        """It was not over: only a supervisor may say so."""

    def get_absolute_url(self) -> str:
        return reverse("example:ticket-detail", kwargs={"pk": self.pk})

    @property
    def age_in_days(self) -> int:
        return (timezone.now() - self.opened_at).days


class TicketComment(models.Model):
    """Edited as a tabular inline on the ticket form."""

    ticket = models.ForeignKey(
        Ticket,
        verbose_name=_("ticket"),
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.CharField(_("author"), max_length=80)
    body = models.TextField(_("comment"))
    position = models.PositiveIntegerField(_("order"), default=0)
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    class Meta:
        ordering = ("position", "pk")
        verbose_name = _("comment")
        verbose_name_plural = _("comments")
        constraints = (
            # Makes the inline exercise a constraint that spans the
            # parent, which is what the delete-then-create ordering in
            # the inline processor exists for.
            models.UniqueConstraint(
                fields=("ticket", "position"),
                name="example_comment_unique_position",
            ),
        )

    def __str__(self) -> str:
        return f"{self.author}: {self.body[:40]}"


class TimeEntry(models.Model):
    """Time an agent spent on a ticket - many of them per ticket."""

    ticket = models.ForeignKey(
        Ticket,
        verbose_name=_("ticket"),
        on_delete=models.CASCADE,
        related_name="time_entries",
    )
    # PROTECT: an agent who logged time is kept for the record.
    agent = models.ForeignKey(
        Agent,
        verbose_name=_("agent"),
        on_delete=models.PROTECT,
        related_name="time_entries",
    )
    spent_on = models.DateField(_("date"), default=timezone.localdate)
    hours = models.DecimalField(_("hours"), max_digits=5, decimal_places=2)
    is_billable = models.BooleanField(_("billable"), default=True)
    note = models.CharField(_("note"), max_length=200, blank=True, default="")

    class Meta:
        ordering = ("-spent_on", "-pk")
        verbose_name = _("time entry")
        verbose_name_plural = _("time entries")

    def __str__(self) -> str:
        return f"{self.hours} h by {self.agent} on {self.spent_on}"


# ---------------------------------------------------------------------
# The desk's equipment: declared with auto(), and nothing else
# ---------------------------------------------------------------------
#
# Three models whose pages nobody wrote: example/resources.py gives each
# one line, and the framework works the rest out from what is below -
# the columns, the search, the tags, the form, the tables of related
# rows and the rows edited on the form.


class Supplier(models.Model):
    """Who the desk buys its equipment from."""

    name = models.CharField(_("name"), max_length=120, unique=True)
    email = models.EmailField(_("email"), blank=True, default="")
    phone = models.CharField(_("phone"), max_length=30, blank=True, default="")
    website = models.URLField(_("website"), blank=True, default="")
    country = models.CharField(
        _("country"), max_length=60, blank=True, default=""
    )
    is_preferred = models.BooleanField(_("preferred"), default=False)
    notes = models.TextField(_("notes"), blank=True, default="")

    class Meta:
        ordering = ("name",)
        verbose_name = _("supplier")
        verbose_name_plural = _("suppliers")

    def __str__(self) -> str:
        return self.name


class Equipment(models.Model):
    """A laptop, a screen, a headset: what the agents work with."""

    class Kind(models.TextChoices):
        LAPTOP = "laptop", _("Laptop")
        SCREEN = "screen", _("Screen")
        PHONE = "phone", _("Phone")
        HEADSET = "headset", _("Headset")
        OTHER = "other", _("Other")

    class State(models.TextChoices):
        IN_USE = "in_use", _("In use")
        SPARE = "spare", _("Spare")
        REPAIR = "repair", _("Being repaired")
        RETIRED = "retired", _("Retired")

    name = models.CharField(_("name"), max_length=120)
    serial_number = models.CharField(
        _("serial number"), max_length=60, unique=True
    )
    kind = models.CharField(
        _("kind"), max_length=10, choices=Kind.choices, default=Kind.LAPTOP
    )
    state = models.CharField(
        _("state"), max_length=10, choices=State.choices, default=State.SPARE
    )
    # PROTECT: a supplier who sold the desk something stays on record.
    supplier = models.ForeignKey(
        Supplier,
        verbose_name=_("supplier"),
        on_delete=models.PROTECT,
        related_name="equipment",
    )
    assigned_to = models.ForeignKey(
        Agent,
        verbose_name=_("assigned to"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipment",
    )
    purchased_on = models.DateField(_("purchased on"), null=True, blank=True)
    price = models.DecimalField(
        _("price"), max_digits=8, decimal_places=2, default=0
    )
    notes = models.TextField(_("notes"), blank=True, default="")

    class Meta:
        ordering = ("name", "serial_number")
        verbose_name = _("equipment")
        verbose_name_plural = _("equipment")

    def __str__(self) -> str:
        return f"{self.name} ({self.serial_number})"


class Maintenance(models.Model):
    """A repair or a check of one piece of equipment."""

    equipment = models.ForeignKey(
        Equipment,
        verbose_name=_("equipment"),
        on_delete=models.CASCADE,
        related_name="maintenances",
    )
    performed_on = models.DateField(
        _("performed on"), default=timezone.localdate
    )
    description = models.CharField(_("description"), max_length=200)
    cost = models.DecimalField(
        _("cost"), max_digits=8, decimal_places=2, default=0
    )
    is_done = models.BooleanField(_("done"), default=False)

    class Meta:
        ordering = ("-performed_on", "-pk")
        verbose_name = _("maintenance visit")
        verbose_name_plural = _("maintenance visits")

    def __str__(self) -> str:
        return f"{self.description} ({self.performed_on})"
