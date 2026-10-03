"""Numbers made from a pattern (``generic.numbering``): what a pattern
may say, the number it gives, and each series counting on its own."""

from __future__ import annotations

from datetime import date
from unittest import mock

import pytest
from django.core.exceptions import ValidationError

from generic.numbering import Pattern, allocate, next_value, peek
from generic.numbering.models import Sequence

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 3)


@pytest.fixture(autouse=True)
def today():
    with mock.patch(
        "generic.numbering.timezone.localdate", return_value=TODAY
    ):
        yield


def test_a_pattern_is_filled_in_with_the_date_and_the_values():
    pattern = Pattern("{team}-{type}-{year}{month}{day}-{yy}-{seq:04}")

    assert pattern.render(7, {"team": "LEG", "type": "CTR"}, TODAY) == (
        "LEG-CTR-20261003-26-0007"
    )


def test_numbers_follow_each_other():
    assert [allocate("DOC-{seq:05}") for _ in range(3)] == [
        "DOC-00001",
        "DOC-00002",
        "DOC-00003",
    ]


def test_without_a_width_the_number_is_as_long_as_it_needs():
    assert allocate("N{seq}") == "N1"


def test_each_series_counts_on_its_own():
    assert allocate("{team}-{seq:03}", team="LEG") == "LEG-001"
    assert allocate("{team}-{seq:03}", team="ENG") == "ENG-001"
    assert allocate("{team}-{seq:03}", team="LEG") == "LEG-002"
    assert set(Sequence.objects.values_list("key", "value")) == {
        ("LEG-#", 2),
        ("ENG-#", 1),
    }


def test_a_pattern_with_the_year_starts_again_each_year():
    assert allocate("{year}/{seq}") == "2026/1"

    with mock.patch(
        "generic.numbering.timezone.localdate",
        return_value=date(2027, 1, 1),
    ):
        assert allocate("{year}/{seq}") == "2027/1"

    assert allocate("{year}/{seq}") == "2026/2"


def test_a_namespace_keeps_two_kinds_of_record_apart():
    assert allocate("{seq}", namespace="invoices") == "1"
    assert allocate("{seq}", namespace="orders") == "1"


def test_a_number_already_held_is_skipped():
    held = {"A-1", "A-2"}

    assert allocate("A-{seq}", exists=held.__contains__) == "A-3"


def test_peek_shows_the_next_number_and_takes_nothing():
    allocate("P-{seq:02}")

    assert peek("P-{seq:02}") == "P-02"
    assert peek("P-{seq:02}") == "P-02"
    assert peek("Q-{seq:02}") == "Q-01"
    assert allocate("P-{seq:02}") == "P-02"


def test_next_value_starts_a_series_at_one():
    assert next_value("fresh") == 1
    assert next_value("fresh") == 2


def test_a_very_long_series_is_named_by_a_digest():
    long = "x" * 300

    assert allocate(long + "{seq}") == long + "1"
    assert len(Sequence.objects.get().key) <= 255


@pytest.mark.parametrize(
    ("text", "fields", "code"),
    [
        ("DOC-", (), "no_sequence"),
        ("{team}-{seq}", ("type",), "unknown"),
        ("{seq:abc}", (), "spec"),
        ("{seq:099}", (), "spec"),
        ("{team:>5}-{seq}", ("team",), "spec"),
        ("{seq", (), "malformed"),
    ],
)
def test_a_pattern_that_cannot_number_is_refused(text, fields, code):
    with pytest.raises(ValidationError) as error:
        Pattern(text, fields=fields).validate()

    assert error.value.code == code


def test_a_pattern_naming_known_fields_is_valid():
    Pattern("{team}/{year}/{seq:4}", fields=("team",)).validate()


def test_a_missing_value_is_said():
    with pytest.raises(ValidationError) as error:
        allocate("{team}-{seq}")

    assert error.value.code == "missing"
