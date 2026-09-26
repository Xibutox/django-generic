"""The dashboard's hub: cards pointing at what matters first.

The site is a singleton that the example has already declared against,
so every test here adds to it inside a fixture that puts it back.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from generic.sites import Shortcut, site

pytestmark = pytest.mark.django_db


@pytest.fixture
def hub():
    """The site's shortcuts, restored afterwards whatever happens."""
    declared = list(site._shortcuts)
    providers = list(site._shortcut_providers)
    site._shortcuts.clear()
    site._shortcut_providers.clear()

    yield site

    site._shortcuts[:] = declared
    site._shortcut_providers[:] = providers


def blocks(client) -> list:
    return client.get("/").context["shortcuts"]


def labels(client) -> list[str]:
    return [
        item["label"] for block in blocks(client) for item in block["items"]
    ]


def one(client, label: str) -> dict:
    return next(
        item
        for block in blocks(client)
        for item in block["items"]
        if item["label"] == label
    )


class TestWhatIsShown:
    def test_a_shortcut_reaches_the_dashboard(self, hub, admin_client):
        hub.add_shortcut("Handbook", url="/wiki/", icon="menu_book")

        assert labels(admin_client) == ["Handbook"]

    def test_a_route_is_resolved_to_its_address(self, hub, admin_client):
        hub.add_shortcut("Tickets", route="site:example_ticket_list")

        assert one(admin_client, "Tickets")["url"] == "/example/ticket/"

    def test_a_route_that_is_not_mounted_shows_nothing(
        self,
        hub,
        admin_client,
    ):
        """A card pointing nowhere is worse than no card."""
        hub.add_shortcut("Elsewhere", route="not_installed:index")

        assert labels(admin_client) == []

    def test_a_description_and_an_icon_travel_with_it(
        self,
        hub,
        admin_client,
    ):
        hub.add_shortcut(
            "Handbook",
            url="/wiki/",
            icon="menu_book",
            description="How the desk works.",
        )
        entry = one(admin_client, "Handbook")

        assert entry["description"] == "How the desk works."
        assert entry["icon"] == "menu_book"


class TestWhoSeesIt:
    def test_a_permission_hides_it(self, hub, auth_client, admin_client):
        hub.add_shortcut(
            "Tickets",
            url="/example/ticket/",
            permission="example.view_ticket",
        )

        assert labels(auth_client) == []
        assert labels(admin_client) == ["Tickets"]

    def test_several_permissions_are_all_required(self, hub, worker_client):
        hub.add_shortcut(
            "Both",
            url="/example/ticket/",
            permission=("example.view_ticket", "example.delete_customer"),
        )

        assert labels(worker_client) == []

    def test_a_callable_decides_too(self, hub, admin_client, auth_client):
        hub.add_shortcut(
            "Staff only",
            url="/example/ticket/",
            permission=lambda user: user.is_superuser,
        )

        assert labels(admin_client) == ["Staff only"]
        assert labels(auth_client) == []


class TestWhereItPoints:
    def test_an_address_outside_opens_in_a_new_tab(self, hub, admin_client):
        hub.add_shortcut("Django", url="https://docs.djangoproject.com/")

        assert one(admin_client, "Django")["external"] is True

    def test_a_page_of_this_site_does_not(self, hub, admin_client):
        hub.add_shortcut("Tickets", url="/example/ticket/")

        assert one(admin_client, "Tickets")["external"] is False

    def test_the_declaration_wins_over_the_guess(self, hub, admin_client):
        hub.add_shortcut(
            "Tickets",
            url="/example/ticket/",
            external=True,
        )

        assert one(admin_client, "Tickets")["external"] is True

    def test_a_mail_address_is_allowed(self, hub, admin_client):
        hub.add_shortcut("Write in", url="mailto:desk@example.test")

        assert one(admin_client, "Write in")["external"] is True

    def test_a_script_is_refused_when_it_is_declared(self, hub):
        """It ends up in an href, so it is refused where it is written
        rather than where it would be clicked."""
        with pytest.raises(ImproperlyConfigured) as refusal:
            hub.add_shortcut("Trouble", url="javascript:alert(1)")

        assert "Trouble" in str(refusal.value)
        assert hub._shortcuts == []

    def test_hiding_the_scheme_does_not_help(self, hub):
        with pytest.raises(ImproperlyConfigured):
            hub.add_shortcut("Trouble", url="java\tscript:alert(1)")

    def test_declaring_a_route_resolves_nothing_yet(self, hub):
        """A resources.py is imported while the site is still being
        built. Reversing anything there freezes a URLconf holding only
        what is registered so far, and every screen added after it -
        the task, history and people ones - disappears.
        """
        from unittest import mock

        with mock.patch("generic.sites.shortcuts.reverse") as reversing:
            hub.add_shortcut("Tickets", route="site:example_ticket_list")

        assert not reversing.called

    def test_the_page_renders_the_link_as_declared(self, hub, admin_client):
        hub.add_shortcut("Django", url="https://docs.djangoproject.com/")
        html = admin_client.get("/").content.decode()

        assert 'href="https://docs.djangoproject.com/"' in html
        assert 'rel="noopener noreferrer"' in html


class TestTheFigureOnTheCard:
    def test_a_callable_is_asked_per_request(self, hub, admin_client):
        hub.add_shortcut("Tickets", url="/example/ticket/", count=lambda r: 7)

        assert one(admin_client, "Tickets")["count"] == "7"

    def test_a_plain_value_works_too(self, hub, admin_client):
        hub.add_shortcut("Tickets", url="/example/ticket/", count=3)

        assert one(admin_client, "Tickets")["count"] == "3"

    def test_a_figure_that_cannot_be_computed_is_no_badge(
        self,
        hub,
        admin_client,
    ):
        """A hub is a signpost: one broken count must not take the
        dashboard down with it."""

        def explode(request):
            raise RuntimeError("no database today")

        hub.add_shortcut("Tickets", url="/example/ticket/", count=explode)

        assert one(admin_client, "Tickets")["count"] == ""


class TestGrouping:
    def test_the_ungrouped_ones_come_first(self, hub, admin_client):
        hub.add_shortcut(
            "Away", url="https://example.test/", group="Elsewhere"
        )
        hub.add_shortcut("Here", url="/example/ticket/")

        assert [block["title"] for block in blocks(admin_client)] == [
            "",
            "Elsewhere",
        ]

    def test_order_then_label_inside_a_block(self, hub, admin_client):
        hub.add_shortcut("Second", url="/a/", order=1)
        hub.add_shortcut("Third", url="/b/", order=2)
        hub.add_shortcut("First", url="/c/", order=0)

        assert labels(admin_client) == ["First", "Second", "Third"]


class TestTheOtherTwoWaysToDeclareOne:
    @override_settings(
        GENERIC={
            "SHORTCUTS": [
                {
                    "label": "Handbook",
                    "url": "https://example.test/handbook",
                    "icon": "book",
                }
            ]
        }
    )
    def test_the_setting_is_read(self, hub, admin_client):
        assert labels(admin_client) == ["Handbook"]

    @override_settings(GENERIC={"SHORTCUTS": [{"url": "/nowhere/"}]})
    def test_an_entry_without_a_label_is_refused(self, hub, admin_client):
        with pytest.raises(ImproperlyConfigured):
            blocks(admin_client)

    @override_settings(
        GENERIC={"SHORTCUTS": [{"label": "X", "ur1": "/typo/"}]}
    )
    def test_a_misspelled_key_is_refused_by_name(self, hub, admin_client):
        """Otherwise it is a card that silently never appears."""
        with pytest.raises(ImproperlyConfigured) as refusal:
            blocks(admin_client)

        assert "ur1" in str(refusal.value)

    def test_a_provider_adds_its_own_per_request(self, hub, admin_client):
        @hub.shortcut_provider
        def bookmarks(request):
            return [
                Shortcut(
                    label=f"For {request.user.username}",
                    url="/example/ticket/",
                )
            ]

        assert labels(admin_client) == ["For admin"]
