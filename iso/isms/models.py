"""The management system's own records (ISO/IEC 27001 clauses 4 to 10).

What an auditor reads first: the scope, the context the ISMS answers,
the parties it serves, its objectives and how they are measured, the
policies and who acknowledged them, who to call, and the management
reviews with the actions they decided.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

USER = settings.AUTH_USER_MODEL


class Scope(models.Model):
    """The ISMS scope statement, one row per version (clause 4.3)."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        APPROVED = "approved", _("Approved")
        SUPERSEDED = "superseded", _("Superseded")

    title = models.CharField(_("title"), max_length=200)
    version = models.CharField(_("version"), max_length=20, default="1.0")
    status = models.CharField(
        _("status"), max_length=12, choices=Status.choices, default="draft"
    )
    statement = models.TextField(
        _("statement"),
        help_text=_("What the ISMS covers: activities, sites, systems."),
    )
    exclusions = models.TextField(
        _("exclusions"),
        blank=True,
        help_text=_("What is left out, and why."),
    )
    interfaces = models.TextField(
        _("interfaces and dependencies"),
        blank=True,
        help_text=_("Activities done by others the ISMS depends on."),
    )
    approved_by = models.ForeignKey(
        USER,
        verbose_name=_("approved by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_on = models.DateField(_("approved on"), null=True, blank=True)

    class Meta:
        ordering = ("-approved_on", "-pk")
        verbose_name = _("scope")
        verbose_name_plural = _("scopes")

    def __str__(self) -> str:
        return f"{self.title} ({self.version})"


class ContextIssue(models.Model):
    """An internal or external issue the ISMS must answer (clause 4.1)."""

    class Kind(models.TextChoices):
        INTERNAL = "internal", _("Internal")
        EXTERNAL = "external", _("External")

    class Category(models.TextChoices):
        POLITICAL = "political", _("Political")
        ECONOMIC = "economic", _("Economic")
        SOCIAL = "social", _("Social")
        TECHNOLOGICAL = "technological", _("Technological")
        LEGAL = "legal", _("Legal")
        ENVIRONMENTAL = "environmental", _("Environmental and climate")
        ORGANISATIONAL = "organisational", _("Organisational")

    class Effect(models.TextChoices):
        THREAT = "threat", _("Threat")
        OPPORTUNITY = "opportunity", _("Opportunity")
        BOTH = "both", _("Both")

    title = models.CharField(_("title"), max_length=200)
    kind = models.CharField(_("kind"), max_length=10, choices=Kind.choices)
    category = models.CharField(
        _("category"), max_length=16, choices=Category.choices
    )
    effect = models.CharField(
        _("effect"), max_length=12, choices=Effect.choices, default="threat"
    )
    description = models.TextField(_("description"), blank=True)
    climate_related = models.BooleanField(
        _("climate related"),
        default=False,
        help_text=_("Climate change is relevant to it (Amd. 1:2024)."),
    )
    reviewed_on = models.DateField(_("reviewed on"), null=True, blank=True)

    class Meta:
        ordering = ("kind", "category", "title")
        verbose_name = _("context issue")
        verbose_name_plural = _("context issues")

    def __str__(self) -> str:
        return self.title


class InterestedParty(models.Model):
    """Who expects something of the ISMS, and what (clause 4.2)."""

    class Kind(models.TextChoices):
        CUSTOMER = "customer", _("Customer")
        EMPLOYEE = "employee", _("Employee")
        REGULATOR = "regulator", _("Regulator")
        SHAREHOLDER = "shareholder", _("Shareholder")
        SUPPLIER = "supplier", _("Supplier")
        PARTNER = "partner", _("Partner")
        PUBLIC = "public", _("Public")

    name = models.CharField(_("name"), max_length=200)
    kind = models.CharField(_("kind"), max_length=12, choices=Kind.choices)
    requirements = models.TextField(
        _("requirements"),
        help_text=_("What they expect: laws, contracts, wishes."),
    )
    addressed = models.BooleanField(_("addressed by the ISMS"), default=True)
    how_addressed = models.TextField(_("how it is addressed"), blank=True)
    climate_requirements = models.BooleanField(
        _("climate requirements"),
        default=False,
        help_text=_("They have requirements about climate change."),
    )
    reviewed_on = models.DateField(_("reviewed on"), null=True, blank=True)

    class Meta:
        ordering = ("kind", "name")
        verbose_name = _("interested party")
        verbose_name_plural = _("interested parties")

    def __str__(self) -> str:
        return self.name


class Objective(models.Model):
    """A measurable information security objective (clause 6.2)."""

    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        ON_TRACK = "on_track", _("On track")
        AT_RISK = "at_risk", _("At risk")
        ACHIEVED = "achieved", _("Achieved")
        ABANDONED = "abandoned", _("Abandoned")

    class Direction(models.TextChoices):
        HIGHER = "higher", _("Higher is better")
        LOWER = "lower", _("Lower is better")

    title = models.CharField(_("title"), max_length=200)
    description = models.TextField(_("description"), blank=True)
    owner = models.ForeignKey(
        USER,
        verbose_name=_("owner"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    target = models.DecimalField(
        _("target"), max_digits=12, decimal_places=2, null=True, blank=True
    )
    unit = models.CharField(_("unit"), max_length=20, blank=True)
    direction = models.CharField(
        _("direction"),
        max_length=8,
        choices=Direction.choices,
        default="higher",
    )
    method = models.TextField(
        _("how it is measured"),
        blank=True,
        help_text=_("The source, the formula, how often (clause 9.1)."),
    )
    due_on = models.DateField(_("due on"), null=True, blank=True)
    status = models.CharField(
        _("status"), max_length=10, choices=Status.choices, default="planned"
    )

    class Meta:
        ordering = ("due_on", "title")
        verbose_name = _("objective")
        verbose_name_plural = _("objectives")

    def __str__(self) -> str:
        return self.title

    @property
    def latest(self) -> "Measurement | None":
        return self.measurements.order_by("-measured_on", "-pk").first()

    def is_met(self, value) -> bool | None:
        """Whether ``value`` reaches the target, None without one."""
        if self.target is None or value is None:
            return None
        if self.direction == self.Direction.LOWER:
            return value <= self.target
        return value >= self.target


class Measurement(models.Model):
    """One reading of an objective's indicator (clause 9.1)."""

    objective = models.ForeignKey(
        Objective,
        verbose_name=_("objective"),
        on_delete=models.CASCADE,
        related_name="measurements",
    )
    measured_on = models.DateField(
        _("measured on"), default=timezone.localdate
    )
    value = models.DecimalField(_("value"), max_digits=12, decimal_places=2)
    comment = models.CharField(_("comment"), max_length=300, blank=True)
    measured_by = models.ForeignKey(
        USER,
        verbose_name=_("measured by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ("-measured_on", "-pk")
        verbose_name = _("measurement")
        verbose_name_plural = _("measurements")

    def __str__(self) -> str:
        return f"{self.objective} - {self.measured_on}: {self.value}"


class Policy(models.Model):
    """An information security policy and its review cycle (A.5.1)."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        APPROVED = "approved", _("Approved")
        RETIRED = "retired", _("Retired")

    code = models.CharField(_("code"), max_length=20, unique=True)
    title = models.CharField(_("title"), max_length=200)
    version = models.CharField(_("version"), max_length=20, default="1.0")
    status = models.CharField(
        _("status"), max_length=10, choices=Status.choices, default="draft"
    )
    summary = models.TextField(_("summary"), blank=True)
    owner = models.ForeignKey(
        USER,
        verbose_name=_("owner"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_by = models.ForeignKey(
        USER,
        verbose_name=_("approved by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_on = models.DateField(_("approved on"), null=True, blank=True)
    next_review_on = models.DateField(
        _("next review on"), null=True, blank=True
    )
    requires_acknowledgement = models.BooleanField(
        _("requires acknowledgement"),
        default=True,
        help_text=_("Every user must say they read it (A.5.1, A.5.10)."),
    )
    document = models.FileField(
        _("document"), upload_to="iso/policies/", blank=True
    )
    url = models.URLField(_("link"), blank=True)

    class Meta:
        ordering = ("code",)
        verbose_name = _("policy")
        verbose_name_plural = _("policies")

    def __str__(self) -> str:
        return f"{self.code} {self.title}"


class Acknowledgement(models.Model):
    """A person saying they read a version of a policy (A.5.1, A.6.3)."""

    policy = models.ForeignKey(
        Policy,
        verbose_name=_("policy"),
        on_delete=models.CASCADE,
        related_name="acknowledgements",
    )
    version = models.CharField(_("version"), max_length=20)
    user = models.ForeignKey(
        USER,
        verbose_name=_("user"),
        on_delete=models.CASCADE,
        related_name="policy_acknowledgements",
    )
    acknowledged_at = models.DateTimeField(
        _("acknowledged at"), default=timezone.now
    )

    class Meta:
        ordering = ("-acknowledged_at",)
        verbose_name = _("acknowledgement")
        verbose_name_plural = _("acknowledgements")
        constraints = [
            models.UniqueConstraint(
                fields=("policy", "version", "user"),
                name="isms_one_acknowledgement_per_version",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} - {self.policy.code} {self.version}"


class Contact(models.Model):
    """Who to call outside: authorities, CERTs, groups (A.5.5, A.5.6)."""

    class Kind(models.TextChoices):
        AUTHORITY = "authority", _("Authority")
        REGULATOR = "regulator", _("Regulator")
        LAW_ENFORCEMENT = "police", _("Law enforcement")
        CERT = "cert", _("CERT / CSIRT")
        INTEREST_GROUP = "group", _("Special interest group")
        EMERGENCY = "emergency", _("Emergency service")

    name = models.CharField(_("name"), max_length=200)
    kind = models.CharField(_("kind"), max_length=10, choices=Kind.choices)
    purpose = models.TextField(
        _("when to contact"),
        help_text=_("The situations this contact is for."),
    )
    phone = models.CharField(_("phone"), max_length=40, blank=True)
    email = models.EmailField(_("e-mail"), blank=True)
    url = models.URLField(_("website"), blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        ordering = ("kind", "name")
        verbose_name = _("contact")
        verbose_name_plural = _("contacts")

    def __str__(self) -> str:
        return self.name


class ManagementReview(models.Model):
    """A management review: its inputs and decisions (clause 9.3)."""

    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        HELD = "held", _("Held")

    title = models.CharField(_("title"), max_length=200)
    held_on = models.DateField(_("date"))
    status = models.CharField(
        _("status"), max_length=8, choices=Status.choices, default="planned"
    )
    chair = models.ForeignKey(
        USER,
        verbose_name=_("chair"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    attendees = models.ManyToManyField(
        USER, verbose_name=_("attendees"), blank=True, related_name="+"
    )
    inputs = models.TextField(
        _("inputs"),
        blank=True,
        help_text=_(
            "Previous actions, changes in context, feedback, audit and "
            "monitoring results, risks, opportunities (9.3.2)."
        ),
    )
    decisions = models.TextField(
        _("decisions"),
        blank=True,
        help_text=_("Improvements and changes to the ISMS (9.3.3)."),
    )

    class Meta:
        ordering = ("-held_on",)
        verbose_name = _("management review")
        verbose_name_plural = _("management reviews")

    def __str__(self) -> str:
        return self.title


class ReviewAction(models.Model):
    """An action a management review decided (clauses 9.3.3, 10.1)."""

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        DONE = "done", _("Done")
        CANCELLED = "cancelled", _("Cancelled")

    review = models.ForeignKey(
        ManagementReview,
        verbose_name=_("management review"),
        on_delete=models.CASCADE,
        related_name="actions",
    )
    title = models.CharField(_("title"), max_length=200)
    owner = models.ForeignKey(
        USER,
        verbose_name=_("owner"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    due_on = models.DateField(_("due on"), null=True, blank=True)
    status = models.CharField(
        _("status"), max_length=10, choices=Status.choices, default="open"
    )
    done_on = models.DateField(_("done on"), null=True, blank=True)

    class Meta:
        ordering = ("due_on", "pk")
        verbose_name = _("review action")
        verbose_name_plural = _("review actions")

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs) -> None:
        if self.status == self.Status.DONE and self.done_on is None:
            self.done_on = timezone.localdate()
        elif self.status != self.Status.DONE:
            self.done_on = None
        super().save(*args, **kwargs)
