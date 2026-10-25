"""Fields people add to a model while the application runs.

A resource opens its model to them with one option::

    @register(Equipment)
    class EquipmentResource(ModelResource):
        custom_fields = True            # or CustomFields(...)

    auto(Supplier, custom_fields=True)

Whoever holds ``<app>.customize_<model>`` then adds fields to it from
the list's *Customize fields*: a text, a number, a yes/no, a date, a
time, a choice - labelled in each language of the project, with limits.
Each is a form control, a line of the summary page, a column of the
table (filtered, sorted, exported), a key of the API, and its changes
are versions of the record's history, like a field of the model.

The definitions and the values live in two tables of the framework
(:mod:`generic.customfields.models`); see ``docs/custom-fields.md``.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from django.utils.translation import gettext_lazy as _

#: Every type a field may be, in the order the form offers them.
TYPES = (
    "text",
    "textarea",
    "email",
    "url",
    "integer",
    "decimal",
    "boolean",
    "date",
    "time",
    "datetime",
    "choice",
)


@dataclasses.dataclass(frozen=True)
class CustomFields:
    """How a model is opened to custom fields.

    ``section`` titles the form's and the summary's section holding
    them; ``types`` narrows the types offered (all by default);
    ``max_fields`` caps the fields of the model (``None``: the setting
    ``CUSTOM_FIELDS_MAX_PER_MODEL``); ``permission`` replaces
    ``<app>.customize_<model>`` as what lets somebody manage them.
    """

    section: Any = _("Additional fields")
    types: tuple[str, ...] | None = None
    max_fields: int | None = None
    permission: str | None = None

    def __post_init__(self) -> None:
        if self.types is not None:
            unknown = [kind for kind in self.types if kind not in TYPES]

            if unknown or not self.types:
                raise ValueError(
                    f"CustomFields.types: unknown type(s) "
                    f"{', '.join(map(repr, unknown)) or '(none given)'}. "
                    f"Known types: {', '.join(TYPES)}."
                )

        if self.max_fields is not None and self.max_fields < 1:
            raise ValueError("CustomFields.max_fields must be at least 1.")


__all__ = ["TYPES", "CustomFields"]
