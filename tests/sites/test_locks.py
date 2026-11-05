"""Records that lock (generic.sites.locks).

The example's articles lock once released (``ArticleResource.lock``):
nothing changes but the cost and the flag itself, the bill of materials
- the BOM lines - locks with them, and neither is deleted. Every write
of the framework is tried against it: the form, the API, a grid's
cells and new rows, a bulk edit, the delete and the bulk delete, a
copy; transitions on the test app's manuscripts.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured

from example.models import Article, BomLine
from generic.sites import Lock, ModelResource, site
from generic.sites.locks import resolve
from tests.factories import UserFactory
from tests.testapp.models import Manuscript

pytestmark = pytest.mark.django_db

ARTICLES = "/api/example/article/"
LINES = "/api/example/bomline/"
MANUSCRIPTS = "/api/testapp/manuscript/"


def person(*codenames):
    user = UserFactory()
    user.user_permissions.set(
        Permission.objects.filter(codename__in=codenames)
    )

    return user


def send(client, method: str, url: str, data: dict | None = None):
    return getattr(client, method)(
        url, json.dumps(data or {}), content_type="application/json"
    )


@pytest.fixture
def maintainer(client):
    user = person(
        "view_article",
        "change_article",
        "add_article",
        "delete_article",
        "view_bomline",
        "change_bomline",
        "add_bomline",
        "delete_bomline",
    )
    client.force_login(user)

    return user


@pytest.fixture
def bike(db) -> dict:
    """A released bicycle made of a wheel, and a draft scooter."""
    wheel = Article.objects.create(reference="WH-1", name="Wheel")
    bicycle = Article.objects.create(
        reference="BK-1",
        name="Bicycle",
        kind="product",
        unit_cost=Decimal("100"),
        released=True,
    )
    scooter = Article.objects.create(reference="SC-1", name="Scooter")
    line = BomLine.objects.create(parent=bicycle, child=wheel, quantity=2)
    draft = BomLine.objects.create(parent=scooter, child=wheel, quantity=2)

    return {
        "wheel": wheel,
        "bicycle": bicycle,
        "scooter": scooter,
        "line": line,
        "draft": draft,
    }


@pytest.fixture
def relock(monkeypatch):
    """Give a resource another lock for one test."""

    def apply(resource, lock):
        monkeypatch.setattr(resource, "lock", lock, raising=False)
        resource.__dict__.pop("_lock", None)
        resource.__dict__.pop("_locks", None)

        for other in site._registry.values():
            other.__dict__.pop("_locks", None)

    yield apply

    for resource in site._registry.values():
        resource.__dict__.pop("_lock", None)
        resource.__dict__.pop("_locks", None)


class TestTheDeclaration:
    def resource(self, **attributes):
        klass = type("ProbeResource", (ModelResource,), attributes)

        return klass(Article, site)

    def test_off_by_default(self):
        assert resolve(self.resource()) is None

    def test_a_string_instead_of_a_tuple_raises(self):
        with pytest.raises(ImproperlyConfigured, match="tuple"):
            Lock("released", related="bom_lines")

    def test_an_unknown_field_raises(self):
        with pytest.raises(ImproperlyConfigured, match="no field 'sealed'"):
            resolve(self.resource(lock=Lock("sealed")))

    def test_a_path_through_a_value_raises(self):
        with pytest.raises(ImproperlyConfigured, match="not a foreign key"):
            resolve(self.resource(lock=Lock("name__released")))

    def test_a_path_through_many_records_raises(self):
        with pytest.raises(ImproperlyConfigured, match="many records"):
            resolve(self.resource(lock=Lock("bom_lines__quantity")))

    def test_a_frozen_name_the_model_lacks_raises(self):
        with pytest.raises(ImproperlyConfigured, match="neither a field"):
            resolve(self.resource(lock=Lock("released", fields=("colour",))))

    def test_a_related_name_that_is_not_one_raises(self):
        with pytest.raises(ImproperlyConfigured, match="related name"):
            resolve(self.resource(lock=Lock("released", related=("family",))))

    def test_anything_but_a_lock_raises(self):
        with pytest.raises(ImproperlyConfigured, match="Lock"):
            resolve(self.resource(lock="released"))

    def test_the_lock_field_is_never_frozen(self):
        bound = resolve(self.resource(lock=Lock("released")))

        assert not bound.freezes("released")
        assert bound.freezes("name")


class TestTheCondition:
    def resource(self, lock):
        klass = type("ProbeResource", (ModelResource,), {"lock": lock})

        return klass(Article, site)

    def test_a_boolean_locks_when_true(self, bike):
        bound = resolve(self.resource(Lock("released")))

        assert bound.is_set(bike["bicycle"])
        assert not bound.is_set(bike["scooter"])

    def test_values_lock_in_those_states(self, bike):
        bound = resolve(self.resource(Lock("kind", values=("product",))))

        assert bound.is_set(bike["bicycle"])
        assert not bound.is_set(bike["wheel"])

    def test_a_path_reads_the_record_pointed_at(self, bike):
        klass = type(
            "ProbeResource", (ModelResource,), {"lock": Lock("family__name")}
        )
        bound = resolve(klass(Article, site))

        # No family: nothing to read, not locked.
        assert not bound.is_set(bike["bicycle"])

    def test_the_sql_says_the_same(self, bike):
        for lock in (Lock("released"), Lock("kind", values=("product",))):
            bound = resolve(self.resource(lock))
            found = set(Article.objects.filter(bound.q()))

            assert found == {
                obj for obj in Article.objects.all() if bound.is_set(obj)
            }


class TestTheForm:
    def test_a_frozen_field_is_refused_with_the_message(
        self, client, maintainer, bike
    ):
        bicycle = bike["bicycle"]
        response = send(
            client, "patch", f"{ARTICLES}{bicycle.pk}/", {"name": "Bike"}
        )

        assert response.status_code == 400, response.content
        assert "released" in response.json()["name"][0]
        bicycle.refresh_from_db()
        assert bicycle.name == "Bicycle"

    def test_an_excluded_field_is_still_written(
        self, client, maintainer, bike
    ):
        bicycle = bike["bicycle"]
        response = send(
            client, "patch", f"{ARTICLES}{bicycle.pk}/", {"unit_cost": "120"}
        )

        assert response.status_code == 200, response.content
        bicycle.refresh_from_db()
        assert bicycle.unit_cost == Decimal("120")

    def test_unlocking_is_writing_the_flag(self, client, maintainer, bike):
        bicycle = bike["bicycle"]
        url = f"{ARTICLES}{bicycle.pk}/"

        assert send(client, "patch", url, {"released": False}).status_code == (
            200
        )
        assert send(client, "patch", url, {"name": "Bike"}).status_code == 200

    def test_sending_the_values_it_has_is_no_change(
        self, client, maintainer, bike
    ):
        bicycle = bike["bicycle"]
        response = send(
            client,
            "patch",
            f"{ARTICLES}{bicycle.pk}/",
            {"name": "Bicycle", "kind": "product", "reference": "BK-1"},
        )

        assert response.status_code == 200, response.content

    def test_a_record_that_is_not_locked_is_written(
        self, client, maintainer, bike
    ):
        scooter = bike["scooter"]
        response = send(
            client, "patch", f"{ARTICLES}{scooter.pk}/", {"name": "E-scooter"}
        )

        assert response.status_code == 200, response.content

    def test_the_change_page_says_what_is_frozen(
        self, client, maintainer, bike
    ):
        bicycle = bike["bicycle"]
        response = client.get(f"/example/article/{bicycle.pk}/change/")
        config = response.context["form_config"]

        assert config["readOnly"] is False
        assert config["lock"]["fields"] is None
        assert set(config["lock"]["except"]) == {"released", "unit_cost"}
        assert "bom_lines" not in config["lock"]["except"]

    def test_an_add_page_has_no_lock(self, client, maintainer, bike):
        config = client.get("/example/article/add/").context["form_config"]

        assert config["lock"] is None


class TestDeleting:
    def test_a_locked_record_is_not_deleted(self, client, maintainer, bike):
        bicycle = bike["bicycle"]
        response = client.delete(f"{ARTICLES}{bicycle.pk}/")

        assert response.status_code == 403
        assert "released" in response.json()["detail"]
        assert Article.objects.filter(pk=bicycle.pk).exists()

    def test_nor_from_its_page(self, client, maintainer, bike):
        bicycle = bike["bicycle"]

        assert (
            client.get(f"/example/article/{bicycle.pk}/delete/").status_code
            == 403
        )

    def test_nor_in_a_selection(self, client, maintainer, bike):
        response = send(
            client,
            "post",
            f"{ARTICLES}actions/",
            {
                "action": "delete_selected",
                "ids": [bike["bicycle"].pk, bike["scooter"].pk],
            },
        )

        assert response.status_code == 200, response.content
        assert response.json()["level"] == "error"
        # Nothing went: the draft stays with the released one.
        assert Article.objects.filter(pk=bike["scooter"].pk).exists()

    def test_delete_false_lets_it_go(self, client, maintainer, bike, relock):
        relock(
            site.get_resource(Article),
            Lock("released", delete=False),
        )
        response = client.delete(f"{ARTICLES}{bike['bicycle'].pk}/")

        assert response.status_code == 204


class TestTheRelatedRecords:
    def test_a_line_of_a_locked_record_is_locked(
        self, client, maintainer, bike
    ):
        response = send(
            client,
            "patch",
            f"{LINES}{bike['line'].pk}/",
            {"quantity": "3"},
        )

        assert response.status_code == 400, response.content
        assert "released" in response.json()["quantity"][0]

    def test_a_line_of_a_draft_is_not(self, client, maintainer, bike):
        response = send(
            client, "patch", f"{LINES}{bike['draft'].pk}/", {"quantity": "3"}
        )

        assert response.status_code == 200, response.content

    def test_no_line_is_added_under_it(self, client, maintainer, bike):
        response = send(
            client,
            "post",
            LINES,
            {
                "parent": bike["bicycle"].pk,
                "child": bike["scooter"].pk,
                "quantity": "1",
            },
        )

        assert response.status_code == 400, response.content
        assert "parent" in response.json()

    def test_nor_moved_under_it(self, client, maintainer, bike):
        response = send(
            client,
            "patch",
            f"{LINES}{bike['draft'].pk}/",
            {"parent": bike["bicycle"].pk},
        )

        assert response.status_code == 400, response.content
        assert "parent" in response.json()

    def test_nor_deleted(self, client, maintainer, bike):
        assert client.delete(f"{LINES}{bike['line'].pk}/").status_code == 403

    def test_its_cells_are_refused(self, client, maintainer, bike):
        related = f"_related=example.article.bom_lines:{bike['bicycle'].pk}"
        response = send(
            client,
            "patch",
            f"{LINES}{bike['line'].pk}/cells/?{related}",
            {"quantity": "16"},
        )

        assert response.status_code == 400, response.content
        assert "released" in response.json()["quantity"][0]
        bike["line"].refresh_from_db()
        assert bike["line"].quantity == 2

    def test_no_row_is_added_to_its_grid(self, client, maintainer, bike):
        related = f"_related=example.article.bom_lines:{bike['bicycle'].pk}"
        response = send(
            client,
            "post",
            f"{LINES}rows/?{related}",
            {"child": bike["scooter"].pk, "quantity": "1", "position": 20},
        )

        assert response.status_code == 400, response.content
        assert not BomLine.objects.filter(
            parent=bike["bicycle"], child=bike["scooter"]
        ).exists()

    def test_its_page_has_nothing_left_to_edit(self, client, maintainer, bike):
        response = client.get(f"/example/bomline/{bike['line'].pk}/change/")
        config = response.context["form_config"]

        assert config["readOnly"] is True
        assert config["lock"]["everything"] is True


class TestTheOtherWrites:
    def test_a_bulk_edit_counts_it_refused(self, client, maintainer, bike):
        resource = site.get_resource(Article)
        request = client.get("/").wsgi_request
        request.user = maintainer

        assert not resource.may_write_column(request, "name", bike["bicycle"])
        assert resource.may_write_column(request, "unit_cost", bike["bicycle"])
        assert resource.may_write_column(request, "name", bike["scooter"])

    def test_the_summary_says_why(self, client, maintainer, bike):
        response = client.get(f"{ARTICLES}{bike['bicycle'].pk}/summary/")
        body = response.json()

        assert "released" in body["lock"]["message"]
        assert body["urls"]["delete"] == ""
        # Unlocking is an edit: the button stays.
        assert body["urls"]["change"]
        # Nothing is added to its bill.
        tabs = {tab["name"]: tab for tab in body["related"]}
        assert tabs["bom_lines"]["addUrl"] == ""

        scooter = client.get(f"{ARTICLES}{bike['scooter'].pk}/summary/")
        assert scooter.json()["lock"] is None

    def test_a_copy_starts_unlocked(self, client, maintainer, bike):
        resource = site.get_resource(Article)
        request = client.get("/").wsgi_request
        request.user = maintainer

        initial = resource.get_duplicate_initial(request, bike["bicycle"])

        assert "released" not in initial["values"]
        assert initial["values"]["name"] == "Bicycle"

    def test_unlocked_narrows_a_selection(self, client, maintainer, bike):
        resource = site.get_resource(Article)
        request = client.get("/").wsgi_request
        request.user = maintainer

        assert set(resource.unlocked(request, Article.objects.all())) == {
            bike["wheel"],
            bike["scooter"],
        }
        lines = site.get_resource(BomLine)

        assert set(lines.unlocked(request, BomLine.objects.all())) == {
            bike["draft"]
        }

    def test_its_permission_is_not_held_back(
        self, client, maintainer, bike, relock
    ):
        relock(
            site.get_resource(Article),
            Lock(
                "released",
                related=("bom_lines",),
                permission="example.delete_article",
            ),
        )
        bicycle = bike["bicycle"]
        response = send(
            client, "patch", f"{ARTICLES}{bicycle.pk}/", {"name": "Bike"}
        )

        assert response.status_code == 200, response.content
        assert send(
            client, "patch", f"{LINES}{bike['line'].pk}/", {"quantity": "5"}
        ).status_code == (200)

    def test_a_callable_permission_decides_per_record(
        self, client, maintainer, bike, relock
    ):
        relock(
            site.get_resource(Article),
            Lock(
                "released",
                permission=lambda request, obj: obj is not None
                and obj.kind == "product",
            ),
        )
        resource = site.get_resource(Article)
        request = client.get("/").wsgi_request
        request.user = maintainer

        assert not resource.is_locked(request, bike["bicycle"])
        assert bike["bicycle"] in resource.unlocked(
            request, Article.objects.all()
        )


class TestTransitions:
    @pytest.fixture
    def editor(self, client):
        user = person("view_manuscript", "change_manuscript")
        client.force_login(user)

        return user

    def names(self, client, manuscript) -> list[str]:
        response = client.get(f"{MANUSCRIPTS}{manuscript.pk}/transitions/")

        return [entry["name"] for entry in response.json()]

    def test_a_lock_on_the_state_keeps_its_way_out(
        self, client, editor, relock
    ):
        from generic.sites import site as default

        relock(
            default.get_resource(Manuscript),
            Lock("state", values=("accepted",)),
        )
        accepted = Manuscript.objects.create(
            title="A", summary="S", state="accepted"
        )

        # The state is the lock's field: rejecting is still offered.
        assert self.names(client, accepted) == ["reject"]
        response = send(
            client,
            "patch",
            f"{MANUSCRIPTS}{accepted.pk}/",
            {"title": "B"},
        )
        assert response.status_code == 400, response.content

    def test_a_lock_freezing_the_state_holds_the_transitions(
        self, client, editor, relock
    ):
        from generic.sites import site as default

        relock(default.get_resource(Manuscript), Lock("summary"))
        submitted = Manuscript.objects.create(
            title="A", summary="S", state="submitted"
        )

        assert self.names(client, submitted) == []
        response = send(
            client,
            "post",
            f"{MANUSCRIPTS}{submitted.pk}/transitions/reject/",
        )

        assert response.status_code == 403
        submitted.refresh_from_db()
        assert submitted.state == "submitted"


class TestATicketLockedWhileBillable:
    """The example's tickets, locked for one test while billable: their
    comments are an inline of the form, and a bulk edit changes them."""

    TICKETS = "/api/example/ticket/"

    @pytest.fixture
    def locked(self, relock):
        from example.models import Ticket

        relock(
            site.get_resource(Ticket),
            Lock("is_billable", exclude=("priority",), related=("comments",)),
        )

    def test_a_bulk_edit_counts_it_refused(
        self, admin_client, support_desk, locked
    ):
        login, invoice = support_desk["login"], support_desk["invoice"]
        invoice.is_billable = False
        invoice.save()
        response = send(
            admin_client,
            "post",
            f"{self.TICKETS}bulk-edit/",
            {
                "changes": {"due_on": "2030-01-01"},
                "commit": True,
                "ids": [str(login.pk), str(invoice.pk)],
            },
        )

        assert response.status_code == 200, response.content
        counts = response.json()["counts"]
        assert counts["refused"] == 1
        assert counts["changed"] == 1
        login.refresh_from_db()
        assert login.due_on is None

    def test_an_excluded_field_is_edited_in_bulk(
        self, admin_client, support_desk, locked
    ):
        login = support_desk["login"]
        response = send(
            admin_client,
            "post",
            f"{self.TICKETS}bulk-edit/",
            {
                "changes": {"priority": "low"},
                "commit": True,
                "ids": [str(login.pk)],
            },
        )

        assert response.json()["counts"]["changed"] == 1

    def test_its_inline_rows_are_read_only(
        self, admin_client, support_desk, locked
    ):
        login = support_desk["login"]
        response = send(
            admin_client,
            "patch",
            f"{self.TICKETS}{login.pk}/",
            {"_inlines": {"comments": [{"body": "Sneaked in"}]}},
        )

        assert response.status_code == 400, response.content
        assert not login.comments.filter(body="Sneaked in").exists()


def test_the_message_speaks_french():
    from django.utils import translation

    from generic.sites.locks import DEFAULT_MESSAGE, delete_refusal

    with translation.override("fr"):
        assert str(DEFAULT_MESSAGE) == (
            "Cet enregistrement est verrouillé : il ne peut pas être modifié."
        )
        assert delete_refusal(2).endswith("sont verrouillés.")
