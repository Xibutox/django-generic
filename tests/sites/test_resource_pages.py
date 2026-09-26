"""Pages of a resource's own (``generic.sites.pages``).

The example declares one of each kind: a page of the customer resource
(the map, and its GeoJSON), a page of each ticket written as a view of
its own (the timeline), and a page of each row of a data resource (a
service's runbook). Below them, what the declaration allows and
refuses, on a site of the test's own.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.test import RequestFactory

from example import external
from example.models import Customer, Ticket
from generic.sites import (
    ModelResource,
    ResourcePage,
    ResourcePageView,
    page,
    site,
)
from generic.sites.pages import build_page_view
from generic.sites.site import GenericSite
from tests.sites.test_resource_api import user_with
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

MAP = "/example/customer/map/"
GEOJSON = "/example/customer/geojson/"


@pytest.fixture(autouse=True)
def fresh_services():
    keys = [external.CACHE_KEY, external.INCIDENTS_CACHE_KEY]
    cache.delete_many(keys)

    yield

    cache.delete_many(keys)


# ---------------------------------------------------------------------
# The example's pages
# ---------------------------------------------------------------------


class TestAPageOfTheResource:
    def test_the_map_is_drawn_in_the_frame(self, admin_client, support_desk):
        response = admin_client.get(MAP)
        context = response.context

        assert response.status_code == 200
        assert "example/pages/customer_map.html" in [
            template.name for template in response.templates
        ]
        assert context["page"].name == "map"
        assert context["resource"] is site.get_resource(Customer)
        assert context["object"] is None
        assert context["page_title"] == "Customer map"
        assert [crumb.url for crumb in context["breadcrumbs"]] == [
            "/example/customer/",
            "",
        ]

    def test_it_draws_what_the_method_returned(
        self, admin_client, support_desk
    ):
        context = admin_client.get(MAP).context
        placed = {marker["name"] for marker in context["map"]["markers"]}

        assert placed == set(Customer.objects.values_list("name", flat=True))
        # The customers' own table, apart from the list's.
        options = context["table"]["options"]

        assert options["syncUrl"] is False
        assert options["stateKey"].endswith(".in.map")

    def test_the_list_offers_it_and_so_does_the_navigation(
        self, admin_client, support_desk
    ):
        listing = admin_client.get("/example/customer/")
        navigation = listing.context["chrome"]["navigation"]
        urls = [item["url"] for group in navigation for item in group["items"]]

        assert MAP.encode() in listing.content
        assert MAP in urls

    def test_a_page_may_answer_json(self, admin_client, support_desk):
        response = admin_client.get(GEOJSON)
        body = json.loads(response.content)

        assert response["Content-Type"] == "application/json"
        assert body["type"] == "FeatureCollection"
        assert len(body["features"]) == Customer.objects.count()
        # No button of its own: the map links to it.
        assert (
            GEOJSON.encode()
            not in admin_client.get("/example/customer/").content
        )

    def test_the_resources_permission_guards_both(self, client, support_desk):
        client.force_login(user_with("view_ticket"))

        assert client.get(MAP).status_code == 403
        assert client.get(GEOJSON).status_code == 403
        # And nothing points at them.
        navigation = client.get("/").context["chrome"]["navigation"]
        urls = [item["url"] for group in navigation for item in group["items"]]

        assert MAP not in urls

    def test_signed_out_is_sent_to_sign_in(self, client):
        response = client.get(GEOJSON)

        assert response.status_code == 302
        assert "/login/" in response["Location"]


class TestAPageOfEachRecord:
    def url(self, ticket) -> str:
        return f"/example/ticket/{ticket.pk}/timeline/"

    def test_the_timeline_of_a_ticket(self, admin_client, support_desk):
        ticket = Ticket.objects.order_by("pk").first()
        response = admin_client.get(self.url(ticket))
        context = response.context
        kinds = {event["kind"] for event in context["events"]}

        assert response.status_code == 200
        assert context["object"] == ticket
        assert context["page_subtitle"] == str(ticket)
        assert "opened" in kinds
        assert [crumb.url for crumb in context["breadcrumbs"]] == [
            "/example/ticket/",
            f"/example/ticket/{ticket.pk}/",
            "",
        ]

    def test_events_come_in_order(self, admin_client, support_desk):
        ticket = Ticket.objects.order_by("pk").first()
        events = admin_client.get(self.url(ticket)).context["events"]
        moments = [event["at"] for event in events]

        assert moments == sorted(moments)

    def test_the_ticket_and_its_rows_offer_it(
        self, admin_client, support_desk
    ):
        ticket = Ticket.objects.order_by("pk").first()
        detail = admin_client.get(f"/example/ticket/{ticket.pk}/")
        config = admin_client.get("/example/ticket/").context["table_config"]
        menu = {
            action["name"]: action.get("url")
            for action in config["options"]["rowActions"]
        }

        assert self.url(ticket).encode() in detail.content
        assert menu["page-timeline"] == "/example/ticket/{_pk}/timeline/"

    def test_an_unknown_record_is_not_found(self, admin_client, support_desk):
        assert (
            admin_client.get("/example/ticket/999999/timeline/").status_code
            == 404
        )
        assert (
            admin_client.get("/example/ticket/abc/timeline/").status_code
            == 404
        )

    def test_the_resources_permission_guards_it(self, client, support_desk):
        ticket = Ticket.objects.order_by("pk").first()
        client.force_login(user_with("view_customer"))

        assert client.get(self.url(ticket)).status_code == 403


class TestAPageOfEachRow:
    RUNBOOK = "/data/services/paylane/runbook/"

    def test_the_runbook_of_a_service(self, admin_client):
        response = admin_client.get(self.RUNBOOK)
        context = response.context

        assert response.status_code == 200
        assert context["object"]["id"] == "paylane"
        assert "Paylane Payments" in context["runbook"]
        assert [incident["id"] for incident in context["ongoing"]] == [
            "inc-2050"
        ]
        assert [crumb.url for crumb in context["breadcrumbs"]] == [
            "/data/services/",
            "/data/services/paylane/",
            "",
        ]

    def test_the_services_page_offers_it(self, admin_client):
        assert (
            self.RUNBOOK.encode()
            in admin_client.get("/data/services/paylane/").content
        )

    def test_what_it_fetches_is_fetched_for_it_only(
        self, admin_client, monkeypatch
    ):
        asked = []
        real = external.runbook_of

        def spy(service):
            asked.append(service)

            return real(service)

        monkeypatch.setattr(external, "runbook_of", spy)

        admin_client.get("/data/services/paylane/")
        assert asked == []

        admin_client.get(self.RUNBOOK)
        assert asked == ["paylane"]

    def test_an_unknown_row_is_not_found(self, admin_client):
        assert (
            admin_client.get("/data/services/nothing/runbook/").status_code
            == 404
        )


# ---------------------------------------------------------------------
# What a declaration allows, on a site of the test's own
# ---------------------------------------------------------------------


@pytest.fixture
def other_site():
    """A site of the test's own, emptied afterwards: a registration
    connects signals that must not outlive the test."""
    created = GenericSite(name="pages_test")

    yield created

    for resource in created.get_resources():
        created.unregister(resource.model)


@pytest.fixture
def author(db):
    return Author.objects.create(name="Ursula")


def viewer(django_user_model, *codenames):
    user = django_user_model.objects.create_user("reader")
    user.user_permissions.set(
        Permission.objects.filter(
            content_type__app_label="testapp", codename__in=codenames
        )
    )

    return django_user_model.objects.get(pk=user.pk)


def call(view, user, method="get", **kwargs):
    request = getattr(RequestFactory(), method)("/somewhere/")
    request.user = user

    return view(request, **kwargs)


def register(other_site, **attributes):
    resource_class = type("AuthorPages", (ModelResource,), attributes)
    other_site.register(Author, resource_class)

    return other_site.get_resource(Author)


def as_page(name, function, **options):
    """``function`` as the ``@page`` method ``name`` of a resource."""
    function.__name__ = name

    return page(**options)(function)


class TestDeclaring:
    def test_pages_then_methods_in_the_order_written(self, other_site):
        class Base(ModelResource):
            pages = (ResourcePage("gallery", view=lambda request: None),)

            @page(title="Books by year")
            def books_by_year(self, request):
                return {}

            @page(detail=True)
            def letters(self, request, author):
                return {}

        other_site.register(Author, Base)
        resource = other_site.get_resource(Author)

        assert [p.name for p in resource.get_page_declarations()] == [
            "gallery",
            "books-by-year",
            "letters",
        ]
        assert (
            resource.get_page("books-by-year").get_title() == "Books by year"
        )
        assert resource.get_page("letters").get_title() == "Letters"

    def test_a_subclass_replaces_or_removes_a_page(self, other_site):
        class Base(ModelResource):
            @page()
            def report(self, request):
                return {}

            @page()
            def stats(self, request):
                return {}

        class Child(Base):
            @page(title="Better report")
            def report(self, request):
                return {}

            def stats(self, request):  # no longer a page
                return None

        other_site.register(Author, Child)
        declared = other_site.get_resource(Author).get_page_declarations()

        assert [(p.name, p.get_title()) for p in declared] == [
            ("report", "Better report")
        ]

    @pytest.mark.parametrize(
        "pages, message",
        [
            ((ResourcePage("Bad Name", view=print),), "lower case"),
            ((ResourcePage("change", view=print),), "generated pages"),
            (
                (
                    ResourcePage("twice", view=print),
                    ResourcePage("twice", view=print),
                ),
                "twice",
            ),
            ((ResourcePage("empty"),), "needs a view"),
            ((ResourcePage("broken", view="not a view"),), "needs a view"),
            (
                (
                    ResourcePage(
                        "nav", view=print, detail=True, navigation=True
                    ),
                ),
                "navigation",
            ),
            ((ResourcePage("menu", view=print, row_menu=True),), "row"),
            (("gallery",), "ResourcePage"),
        ],
    )
    def test_a_declaration_that_could_not_work_is_refused(
        self, other_site, pages, message
    ):
        with pytest.raises(ImproperlyConfigured, match=message):
            register(other_site, pages=pages)

    def test_a_method_page_answers_get_and_post_only(self, other_site):
        with pytest.raises(ImproperlyConfigured, match="answers"):
            register(
                other_site,
                upload=as_page(
                    "upload", lambda self, request: {}, methods=("put",)
                ),
            )


class TestPermissions:
    def test_the_resources_view_permission_first(
        self, other_site, django_user_model
    ):
        resource = register(other_site, pages=(ResourcePage("p", view=print),))
        request = RequestFactory().get("/")
        request.user = viewer(django_user_model)

        assert not resource.has_page_permission(
            request, resource.get_page("p")
        )

    @pytest.mark.parametrize(
        "required, codenames, allowed",
        [
            (None, ("view_author",), True),
            ("change", ("view_author",), False),
            ("change", ("view_author", "change_author"), True),
            ("testapp.delete_author", ("view_author",), False),
            (
                ("testapp.view_book", "testapp.view_author"),
                ("view_author", "view_book"),
                True,
            ),
            (lambda user: user.username == "reader", ("view_author",), True),
            (lambda user: False, ("view_author",), False),
        ],
    )
    def test_and_the_pages_own(
        self, other_site, django_user_model, required, codenames, allowed
    ):
        resource = register(
            other_site,
            pages=(ResourcePage("p", view=print, permission=required),),
        )
        request = RequestFactory().get("/")
        request.user = viewer(django_user_model, *codenames)

        assert (
            resource.has_page_permission(request, resource.get_page("p"))
            is allowed
        )

    def test_a_rule_of_the_record_by_overriding(
        self, other_site, author, admin_user
    ):
        class Resource(ModelResource):
            @page(detail=True, template="x.html")
            def letters(self, request, author):
                return {}

            def has_page_permission(self, request, page, obj=None):
                allowed = super().has_page_permission(request, page, obj)

                return allowed and (obj is None or obj.is_active)

        other_site.register(Author, Resource)
        resource = other_site.get_resource(Author)
        view = build_page_view(
            other_site, resource, resource.get_page("letters")
        )

        assert call(view, admin_user, pk=author.pk).status_code == 200

        author.is_active = False
        author.save()

        with pytest.raises(PermissionDenied):
            call(view, admin_user, pk=author.pk)


class TestMethodPages:
    def test_its_context_is_drawn_with_its_template(
        self, other_site, author, admin_user
    ):
        resource = register(
            other_site,
            letters=as_page(
                "letters",
                lambda self, request, obj: {"count": 3, "who": obj.name},
                detail=True,
                template="letters.html",
            ),
        )
        view = build_page_view(
            other_site, resource, resource.get_page("letters")
        )
        response = call(view, admin_user, pk=author.pk)

        assert response.template_name == ["letters.html"]
        assert response.context_data["count"] == 3
        assert response.context_data["who"] == "Ursula"
        assert response.context_data["object"] == author
        assert response.context_data["page_subtitle"] == "Ursula"

    def test_a_response_goes_through(self, other_site, admin_user):
        resource = register(
            other_site,
            feed=as_page(
                "feed", lambda self, request: JsonResponse({"ok": True})
            ),
        )
        view = build_page_view(other_site, resource, resource.get_page("feed"))

        assert json.loads(call(view, admin_user).content) == {"ok": True}

    def test_a_context_needs_a_template(self, other_site, admin_user):
        resource = register(
            other_site, bare=as_page("bare", lambda self, request: {})
        )
        view = build_page_view(other_site, resource, resource.get_page("bare"))

        with pytest.raises(ImproperlyConfigured, match="template"):
            call(view, admin_user)

    def test_anything_else_is_a_mistake(self, other_site, admin_user):
        resource = register(
            other_site,
            odd=as_page(
                "odd", lambda self, request: "text", template="x.html"
            ),
        )
        view = build_page_view(other_site, resource, resource.get_page("odd"))

        with pytest.raises(TypeError, match="returns the template"):
            call(view, admin_user)

    def test_post_only_where_declared(self, other_site, admin_user):
        def form(self, request):
            if request.method == "POST":
                return HttpResponse("saved")

            return {}

        def read(self, request):
            return form(self, request)

        def write(self, request):
            return form(self, request)

        resource = register(
            other_site,
            read=page(template="x.html")(read),
            write=page(template="x.html", methods=("get", "post"))(write),
        )
        read = build_page_view(other_site, resource, resource.get_page("read"))
        write = build_page_view(
            other_site, resource, resource.get_page("write")
        )

        assert call(read, admin_user, method="post").status_code == 405
        assert call(write, admin_user, method="post").content == b"saved"

    def test_a_record_that_is_not_there(self, other_site, admin_user):
        resource = register(
            other_site,
            letters=as_page(
                "letters",
                lambda self, request, obj: {},
                detail=True,
                template="x.html",
            ),
        )
        view = build_page_view(
            other_site, resource, resource.get_page("letters")
        )

        with pytest.raises(Http404):
            call(view, admin_user, pk=424242)


class TestViewsOfTheirOwn:
    def test_a_resource_page_view_gets_everything(
        self, other_site, author, admin_user
    ):
        class LettersView(ResourcePageView):
            template_name = "letters.html"

            def get_context_data(self, **kwargs):
                context = super().get_context_data(**kwargs)
                context["name"] = self.object.name

                return context

        resource = register(
            other_site,
            pages=(ResourcePage("letters", view=LettersView, detail=True),),
        )
        view = build_page_view(
            other_site, resource, resource.get_page("letters")
        )
        response = call(view, admin_user, pk=author.pk)

        assert response.context_data["name"] == "Ursula"
        assert response.context_data["resource"] is resource
        assert response.template_name == ["letters.html"]

    def test_any_view_gets_the_guard_then_its_arguments(
        self, other_site, author, admin_user, django_user_model
    ):
        seen = {}

        def letters(request, pk):
            seen["pk"] = pk

            return HttpResponse("letters")

        resource = register(
            other_site,
            pages=(ResourcePage("letters", view=letters, detail=True),),
        )
        view = build_page_view(
            other_site, resource, resource.get_page("letters")
        )

        assert call(view, AnonymousUser(), pk=author.pk).status_code == 302

        with pytest.raises(PermissionDenied):
            call(view, viewer(django_user_model), pk=author.pk)

        with pytest.raises(Http404):
            call(view, admin_user, pk=424242)

        assert call(view, admin_user, pk=author.pk).content == b"letters"
        assert seen == {"pk": author.pk}

    def test_an_exempt_view_stays_exempt(self, other_site):
        from django.views.decorators.csrf import csrf_exempt

        @csrf_exempt
        def hook(request):
            return HttpResponse()

        resource = register(
            other_site, pages=(ResourcePage("hook", view=hook),)
        )
        view = build_page_view(other_site, resource, resource.get_page("hook"))

        assert view.csrf_exempt is True


class TestRoutes:
    def test_under_the_resources_address(self, other_site):
        resource = register(
            other_site,
            pages=(
                ResourcePage("report", view=print),
                ResourcePage("letters", view=print, detail=True),
            ),
        )
        routes = {
            pattern.name: str(pattern.pattern)
            for pattern in resource.get_page_urlpatterns("testapp/author/")
        }

        assert routes == {
            "testapp_author_report": "testapp/author/report/",
            "testapp_author_letters": "testapp/author/<path:pk>/letters/",
        }

    def test_before_the_records_own_route(self):
        names = [getattr(pattern, "name", None) for pattern in site.get_urls()]

        assert names.index("example_ticket_timeline") < names.index(
            "example_ticket_detail"
        )
        assert names.index("data_services_runbook") < names.index(
            "data_services_detail"
        )
