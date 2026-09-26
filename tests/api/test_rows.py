"""Rows that are not in the database, filtered as a queryset would be.

The conditions are the ones a model's table builds - same whitelist,
same engines, same ``Q`` - read against dicts instead of sent to SQL.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from generic.api.columns import FilterSpec
from generic.api.rows import (
    RowFilterTreeBuilder,
    RowList,
    as_date,
    as_datetime,
    as_number,
    filter_rows,
    order_rows,
    search_rows,
    values_at,
)

TODAY = datetime.date(2026, 9, 25)

ROWS = [
    {
        "id": "a",
        "name": "Alpha",
        "status": "up",
        "uptime": 99.9,
        "hits": 10,
        "regions": ["eu", "us"],
        "critical": True,
        "since": "2026-09-20",
        "checked": "2026-09-25T08:00:00Z",
        "owner": {"name": "Ann"},
    },
    {
        "id": "b",
        "name": "Beta",
        "status": "down",
        "uptime": "98.5",
        "hits": None,
        "regions": ["eu"],
        "critical": False,
        "since": None,
        "checked": "2026-09-01T08:00:00Z",
        "owner": {"name": "Bob"},
    },
    {
        "id": "c",
        "name": "gamma",
        "status": "up",
        "uptime": Decimal("100"),
        "hits": 3,
        "regions": [],
        "critical": "yes",
        "since": datetime.date(2026, 1, 2),
        "checked": None,
        "owner": None,
    },
]

SPECS = {
    "name": FilterSpec(field="name", type="text"),
    "status": FilterSpec(field="status", type="multiselect"),
    "uptime": FilterSpec(field="uptime", type="float", value_type="float"),
    "hits": FilterSpec(field="hits", type="integer", value_type="integer"),
    "regions": FilterSpec(field="regions", type="multiselect", many=True),
    "critical": FilterSpec(field="critical", type="boolean"),
    "since": FilterSpec(field="since", type="date", value_type="date"),
    "checked": FilterSpec(field="checked", type="date", value_type="datetime"),
    "owner": FilterSpec(field="owner__name", type="text"),
}


def ids(rows) -> list[str]:
    return [row["id"] for row in rows]


def where(*conditions, match="all") -> list[str]:
    tree = {"match": match, "conditions": list(conditions)}
    condition = RowFilterTreeBuilder(SPECS, None).build(tree)

    return ids(filter_rows(ROWS, [condition] if condition else []))


def condition(column, operator, value=None):
    node = {"column": column, "operator": operator}

    if value is not None:
        node["value"] = value

    return node


class TestText:
    def test_contains_ignores_case(self):
        assert where(condition("name", "contains", ["A"])) == ["a", "b", "c"]
        assert where(condition("name", "contains", ["amm"])) == ["c"]

    def test_several_values_any_of_them(self):
        assert where(condition("name", "equals", ["alpha", "Beta"])) == [
            "a",
            "b",
        ]

    def test_a_negation_means_none_of_them(self):
        assert where(condition("name", "not_contains", ["alp", "bet"])) == [
            "c"
        ]

    def test_starts_and_ends(self):
        assert where(condition("name", "starts_with", ["g"])) == ["c"]
        assert where(condition("name", "ends_with", ["TA"])) == ["b"]

    def test_a_path_walks_nested_dicts(self):
        assert where(condition("owner", "equals", ["bob"])) == ["b"]
        assert where(condition("owner", "empty")) == ["c"]


class TestNumbers:
    def test_text_numbers_are_numbers(self):
        # "98.5" came from an API as text; 100 as a Decimal.
        assert where(condition("uptime", "lt", "99")) == ["b"]
        assert where(condition("uptime", "gte", "99.9")) == ["a", "c"]

    def test_between_either_side(self):
        assert where(
            condition("uptime", "between", {"from": "99", "to": ""})
        ) == ["a", "c"]

    def test_a_missing_value_is_empty_and_matches_no_comparison(self):
        assert where(condition("hits", "empty")) == ["b"]
        assert where(condition("hits", "not_equals", "3")) == ["a", "b"]
        assert where(condition("hits", "gt", "1")) == ["a", "c"]


class TestChoices:
    def test_any_and_none_of(self):
        assert where(condition("status", "any_of", ["down"])) == ["b"]
        assert where(condition("status", "none_of", ["down"])) == ["a", "c"]

    def test_a_list_is_several_values(self):
        assert where(condition("regions", "any_of", ["us"])) == ["a"]
        assert where(condition("regions", "all_of", ["eu", "us"])) == ["a"]
        # Has none of them - and an empty list has none.
        assert where(condition("regions", "none_of", ["us"])) == ["b", "c"]
        assert where(condition("regions", "empty")) == ["c"]


class TestBooleans:
    def test_text_booleans_are_booleans(self):
        assert where(condition("critical", "is_true")) == ["a", "c"]
        assert where(condition("critical", "is_false")) == ["b"]


class TestDates:
    @pytest.fixture(autouse=True)
    def today(self, monkeypatch):
        monkeypatch.setattr(timezone, "localdate", lambda *args: TODAY)

    def test_text_and_real_dates_alike(self):
        assert where(condition("since", "on", "2026-01-02")) == ["c"]
        assert where(condition("since", "after", "2026-02-01")) == ["a"]
        assert where(condition("since", "empty")) == ["b"]

    def test_relative_periods(self):
        assert where(condition("since", "last_days", 7)) == ["a"]
        assert where(condition("since", "this_year")) == ["a", "c"]

    def test_datetimes_by_whole_days(self):
        assert where(condition("checked", "on", "2026-09-25")) == ["a"]
        assert where(
            condition(
                "checked",
                "between",
                {"from": "2026-09-01", "to": "2026-09-01"},
            )
        ) == ["b"]


class TestTrees:
    def test_any_of_several_conditions(self):
        assert where(
            condition("status", "any_of", ["down"]),
            condition("hits", "equals", "3"),
            match="any",
        ) == ["b", "c"]

    def test_an_unknown_column_is_refused(self):
        with pytest.raises(ValidationError):
            where(condition("password", "contains", ["x"]))


class TestSearchAndOrder:
    def test_every_word_somewhere(self):
        fields = ["name", "status", "owner__name"]

        assert ids(search_rows(ROWS, fields, "up")) == ["a", "c"]
        assert ids(search_rows(ROWS, fields, "up ann")) == ["a"]
        assert ids(search_rows(ROWS, fields, "up -ann")) == ["c"]

    def test_order_by_several_keys_empty_last(self):
        assert ids(order_rows(ROWS, ["hits"])) == ["c", "a", "b"]
        # Descending puts the empty value first, as PostgreSQL does.
        assert ids(order_rows(ROWS, ["-hits"])) == ["b", "a", "c"]
        assert ids(order_rows(ROWS, ["-status", "-name"])) == ["c", "a", "b"]

    def test_text_orders_without_regard_to_case(self):
        assert ids(order_rows(ROWS, ["name"])) == ["a", "b", "c"]


class TestReading:
    def test_values_flatten_lists_and_keep_what_is_missing(self):
        assert values_at(ROWS[0], "regions") == ["eu", "us"]
        assert values_at(ROWS[2], "regions") == []
        assert values_at(ROWS[2], "owner__name") == [None]

    def test_values_read_as_what_the_condition_compares(self):
        assert as_number("99.5") == Decimal("99.5")
        assert as_number("n/a") is None
        assert as_date("2026-09-25T23:30:00Z") is not None
        assert as_datetime("2026-09-25").tzinfo is not None

    def test_a_row_list_reads_as_a_queryset(self):
        rows = RowList([1, 2, 3])

        assert rows.count() == 3
        assert rows.count(2) == 1
        assert isinstance(rows[1:], RowList)
        assert rows[1:].exists()
        assert not rows[5:].exists()
        assert list(rows.iterator(chunk_size=2)) == [1, 2, 3]
