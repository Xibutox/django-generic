"""State machines: transitions as buttons, bulk actions and endpoints.

On ``tests.testapp.Manuscript``: draft -> submitted (only with a
summary) -> accepted (a permission, and a verdict asked for) or
rejected (confirmed, dangerous).
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured

from generic.history.models import HistoryEntry
from generic.sites import ModelResource, site
from generic.sites.site import GenericSite
from tests.factories import UserFactory
from tests.testapp.models import Manuscript

pytestmark = pytest.mark.django_db

API = "/api/testapp/manuscript/"


def person(*codenames):
    user = UserFactory()
    user.user_permissions.set(
        Permission.objects.filter(codename__in=codenames)
    )

    return user


@pytest.fixture
def editor(client):
    user = person("view_manuscript", "change_manuscript")
    client.force_login(user)

    return user


@pytest.fixture
def chief(client):
    user = person("view_manuscript", "change_manuscript", "accept_manuscript")
    client.force_login(user)

    return user


def names(client, manuscript) -> list[str]:
    response = client.get(f"{API}{manuscript.pk}/transitions/")

    assert response.status_code == 200, response.content

    return [entry["name"] for entry in response.json()]


def take(client, manuscript, name, **values):
    return client.post(
        f"{API}{manuscript.pk}/transitions/{name}/",
        values,
        content_type="application/json",
    )


class TestWhatIsOffered:
    def test_only_from_the_states_a_transition_leaves(self, client, editor):
        submitted = Manuscript.objects.create(title="A", state="submitted")

        assert names(client, submitted) == ["reject"]

    def test_a_condition_not_met_hides_it(self, client, editor):
        draft = Manuscript.objects.create(title="No summary")

        assert names(client, draft) == []

        draft.summary = "Something"
        draft.save()

        assert names(client, draft) == ["submit"]

    def test_a_permission_the_reader_lacks_hides_it(self, client, chief):
        submitted = Manuscript.objects.create(title="A", state="submitted")

        assert names(client, submitted) == ["accept", "reject"]

    def test_a_reader_who_may_not_change_sees_none(self, client):
        client.force_login(person("view_manuscript"))
        submitted = Manuscript.objects.create(title="A", state="submitted")

        assert names(client, submitted) == []

    def test_what_the_page_is_told(self, client, chief):
        submitted = Manuscript.objects.create(title="A", state="submitted")

        described = client.get(f"{API}{submitted.pk}/transitions/").json()
        accept, reject = described

        assert accept["fields"] == [
            {
                "name": "verdict",
                "label": "Verdict",
                "required": False,
                "multiline": True,
                "maxLength": None,
            }
        ]
        assert accept["target"] == "accepted"
        assert reject["variant"] == "danger"
        assert reject["confirm"] == "Reject this manuscript?"

    def test_the_summary_carries_them(self, client, chief):
        submitted = Manuscript.objects.create(title="A", state="submitted")

        body = client.get(f"{API}{submitted.pk}/summary/").json()

        assert [entry["name"] for entry in body["transitions"]] == [
            "accept",
            "reject",
        ]
        assert (
            body["urls"]["transitions"] == f"{API}{submitted.pk}/transitions/"
        )


class TestTakingOne:
    def test_it_moves_the_state(self, client, editor):
        draft = Manuscript.objects.create(title="A", summary="S")

        response = take(client, draft, "submit")

        assert response.status_code == 200, response.content
        draft.refresh_from_db()
        assert draft.state == "submitted"
        # The answer is the summary, as the page reads it.
        assert response.json()["transitions"][0]["name"] == "reject"

    def test_the_fields_it_asks_for_are_written(self, client, chief):
        submitted = Manuscript.objects.create(title="A", state="submitted")

        take(client, submitted, "accept", verdict="Well argued.")

        submitted.refresh_from_db()
        assert submitted.state == "accepted"
        assert submitted.verdict == "Well argued."

    def test_values_it_does_not_ask_for_are_ignored(self, client, chief):
        submitted = Manuscript.objects.create(title="A", state="submitted")

        take(client, submitted, "accept", verdict="Fine", title="Changed")

        submitted.refresh_from_db()
        assert submitted.title == "A"

    def test_the_history_says_which_transition(self, client, editor):
        draft = Manuscript.objects.create(title="A", summary="S")

        take(client, draft, "submit")

        entry = HistoryEntry.objects.filter(object_id=str(draft.pk)).first()
        assert entry.source == "Transition: Submit"

    def test_a_record_no_longer_in_the_state_is_a_conflict(
        self, client, editor
    ):
        """Someone moved it since the page was drawn."""
        submitted = Manuscript.objects.create(title="A", state="rejected")

        response = take(client, submitted, "reject")

        assert response.status_code == 409

    def test_a_condition_not_met_is_a_conflict(self, client, editor):
        draft = Manuscript.objects.create(title="No summary")

        assert take(client, draft, "submit").status_code == 409

    def test_without_its_permission_it_is_refused(self, client, editor):
        submitted = Manuscript.objects.create(title="A", state="submitted")

        response = take(client, submitted, "accept", verdict="x")

        assert response.status_code == 403
        submitted.refresh_from_db()
        assert submitted.state == "submitted"

    def test_without_the_change_permission_it_is_refused(self, client):
        client.force_login(person("view_manuscript"))
        submitted = Manuscript.objects.create(title="A", state="submitted")

        assert take(client, submitted, "reject").status_code == 403

    def test_an_unknown_name_is_not_found(self, client, editor):
        draft = Manuscript.objects.create(title="A")

        assert take(client, draft, "publish").status_code == 404
        # A method of the model that is no transition, either.
        assert take(client, draft, "save").status_code == 404

    def test_a_record_out_of_reach_is_not_found(self, client, editor):
        assert (
            client.post(
                f"{API}999999/transitions/reject/",
                {},
                content_type="application/json",
            ).status_code
            == 404
        )


class TestTheStateIsReadOnly:
    def test_a_form_cannot_write_it(self, client, editor):
        draft = Manuscript.objects.create(title="A")

        response = client.patch(
            f"{API}{draft.pk}/",
            {"state": "accepted"},
            content_type="application/json",
        )

        assert response.status_code == 200
        draft.refresh_from_db()
        assert draft.state == "draft"

    def test_a_grid_may_not_offer_it(self):
        from generic.sites.editable import columns_of

        resource = type(
            "EditableManuscript",
            (ModelResource,),
            {
                "list_display": ("title", "state"),
                "editable_fields": ("state",),
                "transitions": ("state",),
            },
        )(Manuscript, GenericSite(name="transitions-test"))

        with pytest.raises(ImproperlyConfigured, match="state field"):
            columns_of(resource)


class TestBulk:
    def run(self, client, action, ids):
        return client.post(
            f"{API}actions/",
            {"action": action, "ids": ids},
            content_type="application/json",
        )

    def test_rows_it_cannot_leave_are_skipped_and_counted(
        self, client, editor
    ):
        submitted = Manuscript.objects.create(title="A", state="submitted")
        draft = Manuscript.objects.create(title="B")

        response = self.run(
            client, "transition:reject", [submitted.pk, draft.pk]
        )

        assert response.status_code == 200, response.content
        assert response.json()["level"] == "warning"
        assert "1 done, 1 skipped" in response.json()["message"]
        submitted.refresh_from_db()
        draft.refresh_from_db()
        assert (submitted.state, draft.state) == ("rejected", "draft")

    def test_a_transition_asking_for_fields_is_no_bulk_action(
        self, client, chief
    ):
        request = client.get(f"{API}").wsgi_request
        request.user = chief
        resource = site.get_resource(Manuscript)

        assert sorted(resource.get_transition_actions(request)) == [
            "transition:reject",
            "transition:submit",
        ]

    def test_the_list_offers_them(self, client, editor):
        response = client.get("/testapp/manuscript/")
        names = [
            entry["name"]
            for entry in response.context["table_config"]["options"][
                "bulkActions"
            ]
        ]

        assert "transition:submit" in names


class TestDeclarations:
    def declare(self, **attributes):
        klass = type("Declared", (ModelResource,), attributes)

        return klass(Manuscript, GenericSite(name="transitions-test"))

    def test_a_field_that_is_not_a_state(self):
        with pytest.raises(ImproperlyConfigured, match="not a state field"):
            self.declare(transitions=("title",)).get_transitions()

    def test_an_unknown_field(self):
        with pytest.raises(ImproperlyConfigured, match="not a state field"):
            self.declare(transitions=("nope",)).get_transitions()

    def test_a_field_asked_for_that_does_not_exist(self, monkeypatch):
        meta = Manuscript.accept._django_fsm
        transition = next(iter(meta.transitions.values()))
        monkeypatch.setitem(transition.custom, "fields", ("nope",))

        with pytest.raises(ImproperlyConfigured, match="nope"):
            self.declare(transitions=("state",)).get_transitions()

    def test_an_unknown_variant(self, monkeypatch):
        meta = Manuscript.reject._django_fsm
        transition = next(iter(meta.transitions.values()))
        monkeypatch.setitem(transition.custom, "variant", "loud")

        with pytest.raises(ImproperlyConfigured, match="variant"):
            self.declare(transitions=("state",)).get_transitions()

    def test_without_django_fsm(self, monkeypatch):
        from generic.sites import transitions

        monkeypatch.setattr(transitions, "fsm", lambda: None)

        with pytest.raises(ImproperlyConfigured, match="django-fsm-2"):
            self.declare(transitions=("state",)).get_transitions()

    def test_no_transitions_declared_offers_nothing(self):
        assert self.declare().get_transitions() == {}
