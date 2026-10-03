"""Numbers made from a pattern: ``LEG-CTR-2026-0042``.

A pattern is text with fields between braces. The project gives the
values of its own fields - a team's code, a document type's - and the
framework the date and the running number:

::

    from generic.numbering import Pattern, allocate

    allocate("{team}-{type}-{year}-{seq:04}", team="LEG", type="CTR")
    # "LEG-CTR-2026-0001", then "LEG-CTR-2026-0002"...

    Pattern("{team}/{seq:05}", fields=("team",)).validate()   # a form's check

=============  ===========================================
``{seq}``      the running number - required; ``{seq:04}``
               pads it to four digits
``{year}``     2026          ``{yy}``    26
``{month}``    10            ``{day}``   03
anything else  a value the caller passes
=============  ===========================================

Each series counts on its own: the counter is named by everything the
pattern says except the number, so ``{year}`` starts again at 1 each
year and two teams never share a count. The counter is a row
(:class:`~generic.numbering.models.Sequence`) taken under a lock: two
requests at once never get the same number. See ``docs/numbering.md``.
"""

from __future__ import annotations

import hashlib
import string
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Iterable

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

__all__ = [
    "DATE_FIELDS",
    "Pattern",
    "allocate",
    "next_value",
    "peek",
]

#: The fields every pattern may use: today's date, in the project's zone.
DATE_FIELDS = ("year", "yy", "month", "day")

#: The running number's field.
SEQUENCE_FIELD = "seq"

#: A number's longest padding: wider is surely a mistake.
MAX_WIDTH = 12

#: Tries before giving up on a number nobody holds yet.
MAX_TRIES = 100


def dates(today: date | None = None) -> dict[str, str]:
    today = today or timezone.localdate()

    return {
        "year": f"{today.year:04d}",
        "yy": f"{today.year % 100:02d}",
        "month": f"{today.month:02d}",
        "day": f"{today.day:02d}",
    }


@dataclass(frozen=True)
class Pattern:
    """A number's pattern, and the fields its owner offers.

    ``fields`` names the values the caller passes - with the date's and
    ``seq``, the only ones the pattern may use. Empty, any name is
    accepted (and must then be passed).
    """

    text: str
    fields: Iterable[str] = field(default=())

    def parts(self) -> list[tuple[str, str | None, str]]:
        """``(literal, name, spec)`` as ``string.Formatter`` reads them;
        a malformed pattern raises ``ValidationError``."""
        try:
            parsed = list(string.Formatter().parse(self.text))
        except ValueError as error:
            raise ValidationError(
                _("This pattern cannot be read: %(error)s"),
                params={"error": error},
                code="malformed",
            ) from error

        return [
            (literal, name, spec or "")
            for literal, name, spec, _conversion in parsed
        ]

    def validate(self) -> None:
        """Raise ``ValidationError`` unless the pattern can number."""
        allowed = {*self.fields, *DATE_FIELDS, SEQUENCE_FIELD}
        names = []

        for _literal, name, spec in self.parts():
            if name is None:
                continue

            names.append(name)

            if self.fields and name not in allowed:
                raise ValidationError(
                    _("Unknown field {%(name)s}: use %(fields)s."),
                    params={
                        "name": name,
                        "fields": ", ".join(
                            "{" + entry + "}" for entry in sorted(allowed)
                        ),
                    },
                    code="unknown",
                )

            if name == SEQUENCE_FIELD:
                width(spec)
            elif spec:
                raise ValidationError(
                    _("Only {seq} takes a width, as in {seq:04}."),
                    code="spec",
                )

        if SEQUENCE_FIELD not in names:
            raise ValidationError(
                _("The pattern needs {seq}, the running number."),
                code="no_sequence",
            )

    def render(
        self,
        number: int | None,
        values: dict[str, Any],
        today: date | None = None,
    ) -> str:
        """The pattern filled in; ``number`` None leaves ``#`` in place
        of the running number - the name of its series."""
        known = {**dates(today), **{k: str(v) for k, v in values.items()}}
        text = []

        for literal, name, spec in self.parts():
            text.append(literal)

            if name is None:
                continue

            if name == SEQUENCE_FIELD:
                text.append(
                    "#"
                    if number is None
                    else str(number).zfill(width(spec) or 1)
                )
            elif name in known:
                text.append(known[name])
            else:
                raise ValidationError(
                    _("No value for {%(name)s}."),
                    params={"name": name},
                    code="missing",
                )

        return "".join(text)


def width(spec: str) -> int:
    """The padding ``{seq:04}`` asks for: 4. Empty: none."""
    if not spec:
        return 0

    if not spec.isdigit():
        raise ValidationError(
            _("{seq} takes a width in digits, as in {seq:04}."),
            code="spec",
        )

    if int(spec) > MAX_WIDTH:
        raise ValidationError(
            _("{seq} is padded to %(max)s digits at most."),
            params={"max": MAX_WIDTH},
            code="spec",
        )

    return int(spec)


def series_key(namespace: str, key: str) -> str:
    """The counter's name: the pattern filled in but for its number,
    shortened by a digest when it would not fit its column."""
    name = f"{namespace}:{key}" if namespace else key

    if len(name) <= 255:
        return name

    digest = hashlib.sha256(name.encode()).hexdigest()

    return f"{name[:190]}~{digest}"


def next_value(key: str) -> int:
    """The next number of the series ``key``, taken for good.

    The series' row is locked until the caller's transaction ends:
    whoever asks at the same time waits, then gets the number after.
    """
    from generic.numbering.models import Sequence

    with transaction.atomic():
        try:
            # Its own savepoint: a series two requests create at once
            # makes one of them fail here, and only here.
            with transaction.atomic():
                Sequence.objects.get_or_create(key=key)
        except IntegrityError:
            pass

        sequence = Sequence.objects.select_for_update().get(key=key)
        sequence.value += 1
        sequence.updated_at = timezone.now()
        sequence.save(update_fields=("value", "updated_at"))

        return sequence.value


def peek(pattern: str | Pattern, *, namespace: str = "", **values: Any) -> str:
    """The number :func:`allocate` would give now - nothing is taken."""
    from generic.numbering.models import Sequence

    pattern = pattern if isinstance(pattern, Pattern) else Pattern(pattern)
    pattern.validate()
    key = series_key(namespace, pattern.render(None, values))
    last = (
        Sequence.objects.filter(key=key)
        .values_list("value", flat=True)
        .first()
    )

    return pattern.render((last or 0) + 1, values)


def allocate(
    pattern: str | Pattern,
    *,
    namespace: str = "",
    exists: Callable[[str], bool] | None = None,
    **values: Any,
) -> str:
    """The next number of ``pattern`` with ``values``, taken for good.

    ``namespace`` keeps apart two kinds of record numbered with the
    same pattern. ``exists`` - ``lambda code: Model.objects.filter(
    code=code).exists()`` - skips a number something already holds (one
    given by hand, or by an older pattern), so the result is unique.
    Call it inside the transaction that stores the number.
    """
    pattern = pattern if isinstance(pattern, Pattern) else Pattern(pattern)
    pattern.validate()
    today = timezone.localdate()
    series = series_key(namespace, pattern.render(None, values, today))

    for _attempt in range(MAX_TRIES):
        number = pattern.render(next_value(series), values, today)

        if exists is None or not exists(number):
            return number

    raise RuntimeError(
        f"No free number in the series {series!r} after {MAX_TRIES} tries."
    )
