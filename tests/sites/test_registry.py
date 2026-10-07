"""The site: registration, navigation, search and the frame."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured

from example.models import Tag, Team, Ticket
from generic.sites import (
    AlreadyRegistered,
    GenericSite,
    ModelResource,
    register,
    site,
)


class QuietResource(ModelResource):
    """No live updates: a throwaway site must not touch the topics."""

    realtime = False


@pytest.fixture
def probe() -> GenericSite:
    return GenericSite(name="probe")


def request_for(rf, user, path="/"):
    request = rf.get(path)
    request.user = user

    return request


class TestRegistration:
    def test_a_model_registers_once(self, probe):
        probe.register(Tag, QuietResource)

        with pytest.raises(AlreadyRegistered):
            probe.register(Tag, QuietResource)

    def test_keyword_options_build_a_resource_class(self, probe):
        probe.register(Tag, QuietResource, icon="sell", order=3)
        resource = probe.get_resource(Tag)

        assert resource.icon == "sell"
        assert resource.order == 3
        assert isinstance(resource, QuietResource)

    def test_unregistering_forgets_the_model(self, probe):
        probe.register(Tag, QuietResource)
        probe.unregister(Tag)

        assert not probe.is_registered(Tag)

        with pytest.raises(ImproperlyConfigured):
            probe.unregister(Tag)

    def test_the_decorator_registers_on_the_site_given(self, probe):
        @register(Team, site=probe)
        class TeamResource(QuietResource):
            icon = "groups"

        assert type(probe.get_resource(Team)) is TeamResource

    def test_only_resource_classes_can_be_registered(self, probe):
        with pytest.raises(ValueError):
            register(Team, site=probe)(object)

    def test_the_example_resources_are_discovered_at_start_up(self):
        assert site.is_registered(Ticket)
        assert site.get_resource(Ticket).get_label_plural() == "Tickets"


class TestNavigation:
    def labels(self, groups):
        return [group["label"] for group in groups]

    def test_an_anonymous_user_gets_no_navigation(self, rf):
        assert site.get_navigation(request_for(rf, AnonymousUser())) == []

    def test_a_superuser_sees_every_group(self, rf, admin_user):
        groups = site.get_navigation(request_for(rf, admin_user))

        assert {"Support", "Organisation", "Classic views"} <= set(
            self.labels(groups)
        )

        support = next(
            group for group in groups if group["label"] == "Support"
        )
        # The comments resource is registered but kept out of the menu;
        # the customer map is a page of the customers' own, right after
        # them, as the tickets' calendar is right after the tickets; the
        # Triage grid is a page added to the group, and the external
        # services rows that are no model's.
        assert [item["label"] for item in support["items"]] == [
            "Tickets",
            "Due dates",
            "Customers",
            "Customer map",
            "Time entries",
            "Triage",
            "External services",
        ]

    def test_the_dashboard_comes_first(self, rf, admin_user):
        first = site.get_navigation(request_for(rf, admin_user))[0]

        assert first["label"] == ""
        assert first["items"][0]["icon"] == "dashboard"

    def test_resources_follow_the_permissions(self, rf, user, worker):
        plain = self.labels(site.get_navigation(request_for(rf, user)))
        working = self.labels(site.get_navigation(request_for(rf, worker)))

        assert "Support" not in plain
        assert "Support" in working

    def test_the_longest_matching_entry_is_the_current_one(
        self,
        rf,
        admin_user,
    ):
        groups = site.get_navigation(
            request_for(rf, admin_user, "/example/ticket/5/change/")
        )
        current = [
            item["label"]
            for group in groups
            for item in group["items"]
            if item.get("is_current")
        ]

        assert current == ["Tickets"]

    def test_a_link_may_require_a_permission(self, probe, rf, user, worker):
        probe.add_link(
            "Secret", url="/secret/", permission="example.view_ticket"
        )

        assert probe.get_navigation(request_for(rf, user)) == []
        assert (
            probe.get_navigation(request_for(rf, worker))[0]["items"][0][
                "label"
            ]
            == "Secret"
        )

    def test_settings_can_add_groups(self, probe, rf, admin_user, settings):
        settings.GENERIC = {
            "NAVIGATION": [
                {
                    "title": "Reports",
                    "items": [
                        {
                            "title": "Weekly",
                            "url": "/weekly/",
                            "icon": "bar_chart",
                        }
                    ],
                }
            ]
        }

        groups = probe.get_navigation(request_for(rf, admin_user))

        assert groups == [
            {
                "label": "Reports",
                "items": [
                    {
                        "label": "Weekly",
                        "url": "/weekly/",
                        "icon": "bar_chart",
                        "order": 0,
                        "target": "",
                    }
                ],
            }
        ]

    def test_a_link_to_an_unknown_route_is_left_out(
        self, probe, rf, admin_user
    ):
        probe.add_link("Nowhere", route="no-such-route")

        assert probe.get_navigation(request_for(rf, admin_user)) == []


class TestAppList:
    def test_the_dashboard_lists_what_the_user_may_reach(self, rf, worker):
        groups = site.get_app_list(request_for(rf, worker))
        tickets = groups[0]["resources"][0]

        assert groups[0]["label"] == "Support"
        assert tickets["list_url"] == "/example/ticket/"
        assert tickets["add_url"] == "/example/ticket/add/"

        # Teams may be looked at, not added.
        organisation = next(
            group for group in groups if group["label"] == "Organisation"
        )
        teams = organisation["resources"][0]
        assert teams["list_url"] and not teams["add_url"]

    def test_index_context_functions_feed_the_dashboard(self, probe, rf):
        @probe.index_context
        def answer(request):
            return {"answer": 42}

        assert probe.get_index_context(rf.get("/")) == {"answer": 42}


class TestSearch:
    def test_records_are_found_and_link_to_their_page(
        self,
        rf,
        admin_user,
        support_desk,
    ):
        groups = site.search(request_for(rf, admin_user), "invoice")
        tickets = next(
            group for group in groups if group["label"] == "Tickets"
        )

        assert sorted(item["label"] for item in tickets["items"]) == [
            "SD-2 - Invoice PDF is blank",
            "SD-3 - Invoice export is slow",
        ]
        assert tickets["items"][0]["url"].startswith("/example/ticket/")

    def test_pages_are_found_by_name(self, rf, admin_user):
        groups = site.search(request_for(rf, admin_user), "live updates")

        assert groups[0]["label"] == "Pages"
        assert groups[0]["items"][0]["label"] == "Live updates"

    def test_a_blank_term_finds_nothing(self, rf, admin_user):
        assert site.search(request_for(rf, admin_user), "   ") == []

    def test_records_the_user_may_not_see_are_left_out(
        self,
        rf,
        user,
        support_desk,
    ):
        groups = site.search(request_for(rf, user), "invoice")

        assert "Tickets" not in [group["label"] for group in groups]

    def test_the_search_endpoint_answers_json(
        self,
        auth_client,
        admin_user,
        client,
        support_desk,
    ):
        client.force_login(admin_user)
        response = client.get("/api/search/", {"q": "blank"})

        assert response.status_code == 200
        assert response.json()["groups"][0]["items"][0]["label"] == (
            "SD-2 - Invoice PDF is blank"
        )


class TestChrome:
    def test_theme_overrides_are_sanitised(self, settings):
        settings.GENERIC = {
            "THEME": {
                "--color-accent": "#7c3aed",
                "--evil": "red;}</style><script>alert(1)</script>",
                "not-a-token": "blue",
            }
        }

        css = site.get_theme_css()

        assert "--color-accent: #7c3aed;" in css
        assert "script" not in css
        assert "not-a-token" not in css

    def test_no_override_means_no_style(self):
        assert site.get_theme_css() == ""

    def test_the_client_configuration_names_the_endpoints(
        self, rf, admin_user
    ):
        chrome = site.get_chrome(request_for(rf, admin_user))

        assert chrome["client"]["api"]["notifications"] == (
            "/api/generic/notifications/"
        )
        assert chrome["client"]["urls"]["search"] == "/api/search/"
        assert chrome["client"]["websocketUrl"] == "/ws/events/"
        assert chrome["user"]["authenticated"] is True

    def test_every_framework_endpoint_is_found(self):
        """Each is looked up by route name, and a name that finds
        nothing becomes "" - which a page then posts to, itself. The
        bell's *Mark all as read* did, for a 405: it asked for
        ``notification-read-all``, while DRF names the action after its
        method, ``notification-mark-all-read``."""
        api = site.get_framework_api()

        assert [key for key, url in api.items() if not url] == []
        assert api["notificationsReadAll"] == (
            "/api/generic/notifications/read-all/"
        )

    def test_an_anonymous_user_gets_no_socket(self, rf):
        chrome = site.get_chrome(request_for(rf, AnonymousUser()))

        assert chrome["client"]["websocketUrl"] == ""
        assert chrome["navigation"] == []

    def test_initials_come_from_the_name_or_the_login(
        self,
        rf,
        django_user_model,
    ):
        named = django_user_model(
            username="x", first_name="Ada", last_name="Lovelace"
        )
        bare = django_user_model(username="grace")

        from generic.sites.site import user_initials

        assert user_initials(named) == "AL"
        assert user_initials(bare) == "GR"

    def test_the_admin_link_is_for_staff_only(
        self, rf, user, staff_user, settings
    ):
        assert site.get_admin_url(user) == ""

        # The test project has no admin mounted: no link, not an error.
        assert site.get_admin_url(staff_user) == ""
