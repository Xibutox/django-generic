"""generic.testing.PageSweep, the helper itself.

Its tests are the framework's own page sweep (tests/test_pages.py);
these cover what it decides: what is parametrised, what an address
gets, what is skipped and expected, and the gap it reports.
"""

from __future__ import annotations

import pytest

from generic.testing import PageSweep, discover, is_api

pytestmark = pytest.mark.django_db


class Recorder:
    """A stand-in for pytest's metafunc: what would be parametrised."""

    def __init__(self, *names: str) -> None:
        self.fixturenames = names
        self.calls: dict[str, list] = {}

    def parametrize(self, name, values, ids=None):
        self.calls[name] = list(values)


def test_pages_come_from_the_urlconf_and_leave_the_api_out():
    names = [name for name, _arguments in discover()]

    assert "site:index" in names
    assert "site:example_ticket_detail" in names
    assert not any(name.startswith("site:api_") for name in names)


def test_an_api_path_is_recognised_under_a_prefix():
    assert is_api("^app/api/example/ticket/$")
    assert not is_api("app/example/ticket/")


def test_the_parametrisation_follows_the_subclass():
    class Sweep(PageSweep):
        languages = ("en", "fr")

    metafunc = Recorder("page", "resource", "language")
    Sweep().pytest_generate_tests(metafunc)

    assert "site:index" in metafunc.calls["page"]
    assert "example.ticket" in metafunc.calls["resource"]
    assert metafunc.calls["language"] == ["en", "fr"]


def test_without_languages_each_page_is_opened_once():
    metafunc = Recorder("language")
    PageSweep().pytest_generate_tests(metafunc)

    assert metafunc.calls["language"] == [None]


def test_skipped_and_expected_add_to_the_framework_own():
    class Sweep(PageSweep):
        skipped = {"site:index": "not today"}
        expected = {"site:help": (302,)}

    sweep = Sweep()

    assert sweep.get_skipped()["site:logout"]
    assert sweep.get_skipped()["site:index"] == "not today"
    assert sweep.get_expected("site:help") == (302,)
    assert sweep.get_expected("site:generic_taskrun_add") == (403,)
    assert sweep.get_expected("site:index") == (200,)


def test_an_address_takes_the_record_of_its_resource(support_desk):
    login = support_desk["login"]
    records = {"example.ticket": login}

    url = PageSweep().address("site:example_ticket_detail", records)

    assert url == f"/example/ticket/{login.pk}/"


def test_a_missing_record_names_what_to_do():
    with pytest.raises(LookupError, match="records"):
        PageSweep().address("site:example_ticket_detail", {})


def test_an_address_nobody_can_fill_is_reported():
    class Sweep(PageSweep):
        urlconf = "tests.sweep_urls"

    with pytest.raises(AssertionError) as failure:
        Sweep().test_every_page_is_covered()

    assert "odd-page" in str(failure.value)


def test_skipping_it_is_the_way_out():
    class Sweep(PageSweep):
        urlconf = "tests.sweep_urls"
        skipped = {"odd-page": "takes a thing"}

    Sweep().test_every_page_is_covered()
