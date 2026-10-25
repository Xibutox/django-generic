"""What the ISO apps share: navigation groups, colours, numbering, and
the scales risks and severities are rated on.

Kept small on purpose: each app stays readable on its own, and a
project that installs only one of them pulls in nothing else.
"""

from __future__ import annotations

from typing import Any

from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from generic.numbering import allocate

# Navigation groups: the apps share a few, so the sidebar of a project
# installing all twelve stays short.
GROUP_ISMS = _("ISMS")
GROUP_ASSETS = _("Assets and suppliers")
GROUP_RISKS = _("Risks and controls")
GROUP_OPERATIONS = _("Security operations")
GROUP_CONTINUITY = _("Continuity")
GROUP_AUDITS = _("Audits and improvement")
GROUP_STAFF = _("Staff and access")

# The framework's tag colours, by meaning.
BLUE = "#2563eb"
AMBER = "#d97706"
GREEN = "#16a34a"
GREY = "#64748b"
RED = "#dc2626"
DARK_RED = "#991b1b"
PURPLE = "#7c3aed"
TEAL = "#0d9488"


class Severity(models.TextChoices):
    """One scale for every rating: incidents, vulnerabilities,
    suppliers' criticality, services."""

    LOW = "low", _("Low")
    MEDIUM = "medium", _("Medium")
    HIGH = "high", _("High")
    CRITICAL = "critical", _("Critical")


SEVERITY_COLORS = {
    "low": GREY,
    "medium": AMBER,
    "high": RED,
    "critical": {"background": DARK_RED, "color": "#ffffff"},
}


class Classification(models.TextChoices):
    """How much harm a disclosure would do (ISO/IEC 27002 5.12)."""

    PUBLIC = "public", _("Public")
    INTERNAL = "internal", _("Internal")
    CONFIDENTIAL = "confidential", _("Confidential")
    RESTRICTED = "restricted", _("Restricted")


CLASSIFICATION_COLORS = {
    "public": GREEN,
    "internal": BLUE,
    "confidential": AMBER,
    "restricted": {"background": DARK_RED, "color": "#ffffff"},
}


def number(
    instance: Any,
    pattern: str,
    namespace: str,
    field: str = "reference",
    **values: Any,
) -> None:
    """Give ``instance`` its next reference, once, before it is saved.

    Call it inside the transaction that saves the record: the series
    stays locked until it commits (``generic.numbering``), so two
    records saved at once never share a number.
    """
    if getattr(instance, field):
        return

    manager = type(instance)._default_manager

    setattr(
        instance,
        field,
        allocate(
            pattern,
            namespace=namespace,
            exists=lambda code: manager.filter(**{field: code}).exists(),
            **values,
        ),
    )


def save_numbered(
    instance: Any,
    pattern: str,
    namespace: str,
    save: Any,
    *args: Any,
    **kwargs: Any,
) -> None:
    """``number`` then the model's own ``save``, in one transaction."""
    with transaction.atomic():
        number(instance, pattern, namespace)
        save(*args, **kwargs)


def is_installed(app: str) -> bool:
    """Whether a sibling ISO app is installed in this project."""
    from django.apps import apps

    return apps.is_installed(app)


def next_year(day: Any) -> Any:
    """The same day a year later; 28 February after a 29th."""
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(year=day.year + 1, day=28)
