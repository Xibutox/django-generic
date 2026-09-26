"""The global search: every word, negation, phrases, each row once."""

from __future__ import annotations

import pytest

from generic.api.filters import (
    MAX_SEARCH_TERMS,
    apply_search,
    split_search_terms,
)


class TestSplitSearchTerms:
    def test_words_are_split_on_whitespace(self):
        assert split_search_terms("invoice   blank") == [
            ("invoice", False),
            ("blank", False),
        ]

    def test_a_leading_bang_or_dash_negates_a_word(self):
        assert split_search_terms("!closed -spam") == [
            ("closed", True),
            ("spam", True),
        ]

    def test_quotes_keep_a_phrase_whole(self):
        assert split_search_terms('"password reset" -"on hold"') == [
            ("password reset", False),
            ("on hold", True),
        ]

    def test_a_hyphenated_reference_is_not_negated(self):
        assert split_search_terms("SD-1000") == [("SD-1000", False)]

    def test_a_lone_dash_is_just_a_character(self):
        assert split_search_terms("- x") == [("-", False), ("x", False)]

    def test_empty_terms_are_dropped(self):
        assert split_search_terms('   ""  ') == []
        assert split_search_terms("") == []

    def test_the_number_of_terms_is_capped(self):
        terms = split_search_terms(
            " ".join(f"w{index}" for index in range(40))
        )

        assert len(terms) == MAX_SEARCH_TERMS


@pytest.mark.django_db
class TestApplySearch:
    FIELDS = ("reference", "title", "tags__name")

    def search(self, raw: str) -> list[str]:
        from example.models import Ticket

        return sorted(
            apply_search(Ticket.objects.all(), self.FIELDS, raw).values_list(
                "reference", flat=True
            )
        )

    def test_every_word_must_match(self, support_desk):
        assert self.search("invoice blank") == ["SD-2"]

    def test_a_negated_word_excludes_its_matches(self, support_desk):
        assert self.search("invoice !blank") == ["SD-3"]

    def test_a_phrase_matches_as_written(self, support_desk):
        assert self.search('"password reset"') == ["SD-1"]
        assert self.search('"reset password"') == []

    def test_a_many_valued_path_lists_each_row_once(self, support_desk):
        # SD-1 carries "regression" and "release": both match "re", and
        # a plain join would list the ticket twice.
        assert self.search("re") == ["SD-1"]

    def test_excluding_through_a_many_valued_path(self, support_desk):
        assert self.search("-billing") == ["SD-1", "SD-3"]

    def test_no_field_means_no_filter(self, support_desk):
        from example.models import Ticket

        assert apply_search(Ticket.objects.all(), (), "anything").count() == 3
