"""A record copied into a new one (generic.sites.duplicates).

The example duplicates tickets (``duplicate = True``: tags and comments
come along on the form) and articles, with their bill of materials
copied on request (``Duplicate(related=("bom_lines",))``).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured

from example.models import Article, BomLine, Ticket
from generic.sites import Duplicate, ModelResource, site
from generic.sites.duplicates import resolve

pytestmark = pytest.mark.django_db

TICKETS = "/api/example/ticket/"
ARTICLES = "/api/example/article/"


def page_config(client, url: str) -> dict:
    response = client.get(url)

    assert response.status_code == 200, response.content

    return response.context["form_config"]


def user_with(django_user_model, name: str, *codenames: str):
    user = django_user_model.objects.create_user(username=name)
    user.user_permissions.set(
        Permission.objects.filter(codename__in=codenames)
    )

    return user


class TestTheForm:
    def test_opens_with_the_record_s_values(self, admin_client, support_desk):
        login = support_desk["login"]
        config = page_config(
            admin_client, f"/example/ticket/{login.pk}/duplicate/"
        )
        values = config["initial"]

        assert config["mode"] == "create"
        assert values["title"] == "Login fails after password reset"
        assert values["team"] == login.team_id
        assert values["priority"] == "high"
        assert sorted(values["tags"]) == sorted(
            login.tags.values_list("pk", flat=True)
        )
        assert config["initialDisplay"]["team"]

    def test_leaves_out_unique_fields_files_and_read_only_ones(
        self, admin_client, support_desk
    ):
        login = support_desk["login"]
        values = page_config(
            admin_client, f"/example/ticket/{login.pk}/duplicate/"
        )["initial"]

        assert "reference" not in values  # unique
        assert "attachment" not in values  # a file
        assert "status" not in values  # moved by its transitions only

    def test_offers_the_many_to_many_values_and_the_inline_rows(
        self, admin_client, support_desk
    ):
        login = support_desk["login"]
        config = page_config(
            admin_client, f"/example/ticket/{login.pk}/duplicate/"
        )
        copies = {copy["name"]: copy for copy in config["duplicate"]["copies"]}

        assert copies["tags"]["kind"] == "field"
        assert copies["tags"]["count"] == 2
        assert copies["tags"]["checked"] is True
        assert copies["comments"]["kind"] == "inline"
        rows = config["initialInlines"]["comments"]
        assert len(rows) == login.comments.count()
        # New rows: no key, no pointer at the record copied.
        assert all("id" not in row and "ticket" not in row for row in rows)

    def test_offers_a_declared_relation_unticked(self, admin_client, bom):
        config = page_config(
            admin_client, f"/example/article/{bom['BK-1'].pk}/duplicate/"
        )
        copies = {copy["name"]: copy for copy in config["duplicate"]["copies"]}

        assert copies["bom_lines"] == {
            "name": "bom_lines",
            "kind": "related",
            "label": "BOM lines",
            "count": 2,
            "checked": False,
            "disabled": False,
        }

    def test_cancel_leads_back_to_the_record(self, admin_client, support_desk):
        login = support_desk["login"]
        config = page_config(
            admin_client, f"/example/ticket/{login.pk}/duplicate/"
        )

        assert config["cancelUrl"] == f"/example/ticket/{login.pk}/"
        assert config["duplicate"]["source"] == str(login.pk)

    def test_a_field_the_reader_may_not_change_is_not_copied(
        self, client, django_user_model, bom
    ):
        # unit_cost is guarded by change_article (field_permissions).
        user = user_with(
            django_user_model, "maker", "view_article", "add_article"
        )
        client.force_login(user)
        bom["BK-1"].unit_cost = Decimal("120.00")
        bom["BK-1"].save()

        values = page_config(
            client, f"/example/article/{bom['BK-1'].pk}/duplicate/"
        )["initial"]

        assert "unit_cost" not in values
        assert values["name"] == "City bicycle"

    def test_the_record_s_page_and_row_menu_offer_it(
        self, admin_client, support_desk
    ):
        login = support_desk["login"]
        response = admin_client.get(f"/example/ticket/{login.pk}/")
        urls = [item.url for item in response.context["toolbar_items"]]

        assert f"/example/ticket/{login.pk}/duplicate/" in urls

        resource = site.get_resource(Ticket)
        request = response.wsgi_request
        names = [
            action["name"] for action in resource.get_row_actions(request)
        ]
        assert "duplicate" in names


class TestPermissions:
    def test_refused_without_the_add_permission(
        self, client, django_user_model, support_desk
    ):
        client.force_login(
            user_with(django_user_model, "reader", "view_ticket")
        )
        login = support_desk["login"]

        assert (
            client.get(f"/example/ticket/{login.pk}/duplicate/").status_code
            == 403
        )

        response = client.get(f"/example/ticket/{login.pk}/")
        urls = [item.url for item in response.context["toolbar_items"]]
        assert f"/example/ticket/{login.pk}/duplicate/" not in urls

    def test_a_record_out_of_reach_is_a_404(self, admin_client):
        assert (
            admin_client.get("/example/ticket/999999/duplicate/").status_code
            == 404
        )

    def test_a_resource_without_duplicate_has_no_page(self, admin_client):
        from example.models import TimeEntry

        # TimeEntryResource declares nothing: no route, no button.
        resource = site.get_resource(TimeEntry)

        assert resource.get_duplicate_url(1) == ""
        assert resource.get_duplicate() is None


class TestTheCopy:
    def payload(self, ticket, **values) -> dict:
        return {
            "reference": "SD-9",
            "title": ticket.title,
            "team": ticket.team_id,
            "priority": ticket.priority,
            "tags": list(ticket.tags.values_list("pk", flat=True)),
            **values,
        }

    def test_a_copy_is_an_ordinary_new_record(
        self, admin_client, support_desk
    ):
        login = support_desk["login"]
        body = self.payload(
            login, _duplicate={"source": login.pk, "related": []}
        )
        response = admin_client.post(
            TICKETS, body, content_type="application/json"
        )

        assert response.status_code == 201, response.content
        copy = Ticket.objects.get(reference="SD-9")
        assert set(copy.tags.all()) == set(login.tags.all())
        assert Ticket.objects.filter(reference="SD-1").exists()

    def test_copies_the_relations_ticked(self, admin_client, bom):
        bike = bom["BK-1"]
        body = {
            "reference": "BK-2",
            "name": "City bicycle, blue",
            "kind": "product",
            "unit": bike.unit,
            "family": bike.family_id,
            "_duplicate": {"source": bike.pk, "related": ["bom_lines"]},
        }
        response = admin_client.post(
            ARTICLES, body, content_type="application/json"
        )

        assert response.status_code == 201, response.content
        copy = Article.objects.get(reference="BK-2")
        assert sorted(
            copy.bom_lines.values_list(
                "child__reference", "position", "quantity"
            )
        ) == [("SC-1", 20, Decimal("12")), ("WH-1", 10, Decimal("2"))]
        # The source keeps its own.
        assert bike.bom_lines.count() == 2

    def test_nothing_is_copied_unticked(self, admin_client, bom):
        bike = bom["BK-1"]
        body = {
            "reference": "BK-2",
            "name": "Bare bicycle",
            "kind": "product",
            "unit": bike.unit,
            "_duplicate": {"source": bike.pk, "related": []},
        }
        response = admin_client.post(
            ARTICLES, body, content_type="application/json"
        )

        assert response.status_code == 201, response.content
        assert not Article.objects.get(reference="BK-2").bom_lines.exists()

    def test_an_undeclared_relation_is_refused(
        self, admin_client, support_desk
    ):
        login = support_desk["login"]
        body = self.payload(
            login, _duplicate={"source": login.pk, "related": ["time_entries"]}
        )
        response = admin_client.post(
            TICKETS, body, content_type="application/json"
        )

        assert response.status_code == 400
        assert "_duplicate" in response.json()
        assert not Ticket.objects.filter(reference="SD-9").exists()

    def test_an_unknown_source_is_a_404(self, admin_client, support_desk):
        body = self.payload(
            support_desk["login"], _duplicate={"source": 999999}
        )
        response = admin_client.post(
            TICKETS, body, content_type="application/json"
        )

        assert response.status_code == 404
        assert not Ticket.objects.filter(reference="SD-9").exists()

    def test_relations_need_their_own_add_permission(
        self, client, django_user_model, bom
    ):
        user = user_with(
            django_user_model,
            "maker",
            "view_article",
            "add_article",
            "change_article",
            "view_bomline",
        )
        client.force_login(user)
        bike = bom["BK-1"]
        body = {
            "reference": "BK-2",
            "name": "City bicycle, blue",
            "kind": "product",
            "unit": bike.unit,
            "_duplicate": {"source": bike.pk, "related": ["bom_lines"]},
        }

        # Not offered on the form...
        config = page_config(client, f"/example/article/{bike.pk}/duplicate/")
        assert "bom_lines" not in [
            c["name"] for c in config["duplicate"]["copies"]
        ]

        # ... and refused by the endpoint, the record rolled back with it.
        response = client.post(ARTICLES, body, content_type="application/json")
        assert response.status_code == 403
        assert not Article.objects.filter(reference="BK-2").exists()

    def test_a_refused_related_record_rolls_the_copy_back(
        self, admin_client, bom, monkeypatch
    ):
        from rest_framework.exceptions import ValidationError

        resource = site.get_resource(BomLine)

        def refuse(request, serializer, change):
            raise ValidationError({"quantity": ["No."]})

        monkeypatch.setattr(resource, "save_model", refuse)
        bike = bom["BK-1"]
        body = {
            "reference": "BK-2",
            "name": "City bicycle, blue",
            "kind": "product",
            "unit": bike.unit,
            "_duplicate": {"source": bike.pk, "related": ["bom_lines"]},
        }
        response = admin_client.post(
            ARTICLES, body, content_type="application/json"
        )

        assert response.status_code == 400
        assert not Article.objects.filter(reference="BK-2").exists()


class TestTheDeclaration:
    def resource(self, **attributes):
        klass = type("ProbeResource", (ModelResource,), attributes)

        return klass(Article, site)

    def test_off_by_default(self):
        assert resolve(self.resource()) is None

    def test_true_copies_the_form(self):
        bound = resolve(self.resource(duplicate=True))

        assert bound.related == {}

    def test_a_relation_that_is_not_a_reverse_foreign_key_raises(self):
        with pytest.raises(ImproperlyConfigured, match="related name"):
            resolve(self.resource(duplicate=Duplicate(related=("family",))))

    def test_an_unknown_excluded_field_raises(self):
        with pytest.raises(ImproperlyConfigured, match="not a field"):
            resolve(self.resource(duplicate=Duplicate(exclude=("colour",))))

    def test_a_string_instead_of_a_tuple_raises(self):
        with pytest.raises(ImproperlyConfigured, match="tuple"):
            Duplicate(related="bom_lines")

    def test_values_are_applied_to_the_copy(self, rf, admin_user, bom):
        resource = self.resource(
            duplicate=Duplicate(
                values=lambda request, obj: {"name": f"{obj.name} (copy)"}
            )
        )
        request = rf.get("/")
        request.user = admin_user

        initial = resource.get_duplicate_initial(request, bom["BK-1"])

        assert initial["values"]["name"] == "City bicycle (copy)"
