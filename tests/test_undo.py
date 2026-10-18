"""Undo: what a delete, a bulk action or a bulk edit just did, put back
from the history (generic.history.undo)."""

from __future__ import annotations

import time
from unittest import mock

import pytest
from django.contrib.auth.models import Permission
from django.test import RequestFactory, override_settings

from example.models import Tag, Ticket, TicketComment
from generic.history import acting_as
from generic.history.capture import capture
from generic.history.models import HistoryEntry
from generic.history.undo import (
    MESSAGE_TAG,
    Refused,
    deletion_is_recorded,
    from_message_tags,
    message_tags,
    offer,
    undo,
)
from generic.sites import site
from generic.templatetags.generic_tags import message_icon
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

TICKETS = "/api/example/ticket/"
CONTRACTS = "/api/testapp/contract/"


def post(client, url, body):
    return client.post(url, body, content_type="application/json")


def action(client, name, *tickets):
    response = post(
        client,
        f"{TICKETS}actions/",
        {"action": name, "ids": [str(ticket.pk) for ticket in tickets]},
    )
    assert response.status_code == 200, response.content

    return response.json()


def take_back(client, answer, url=f"{TICKETS}undo/"):
    return post(client, url, {"token": answer["undo"]["token"]})


class TestAfterABulkAction:
    def test_the_answer_offers_an_undo(self, worker_client, support_desk):
        answer = action(
            worker_client, "mark_billable", support_desk["invoice"]
        )

        assert answer["undo"]["url"] == f"{TICKETS}undo/"
        assert answer["undo"]["label"] == "Undo"
        assert answer["undo"]["count"] == 1
        assert answer["undo"]["seconds"] == 600

    def test_undo_puts_each_record_back(self, worker_client, support_desk):
        invoice, export = support_desk["invoice"], support_desk["export"]
        answer = action(worker_client, "mark_billable", invoice, export)

        response = take_back(worker_client, answer)

        assert response.status_code == 200, response.content
        assert response.json()["message"] == (
            "Undone: 2 records are back as they were."
        )
        invoice.refresh_from_db()
        export.refresh_from_db()
        assert (invoice.is_billable, export.is_billable) == (False, False)

    def test_the_undo_is_itself_in_the_history(
        self, worker_client, worker, support_desk
    ):
        invoice = support_desk["invoice"]
        take_back(
            worker_client,
            action(worker_client, "mark_billable", invoice),
        )

        newest = HistoryEntry.objects.filter(object_id=str(invoice.pk))[0]
        assert newest.source == "Undo"
        assert newest.user == worker
        assert newest.values["is_billable"] is False

    def test_a_transition_is_undone(self, worker_client, support_desk):
        login = support_desk["login"]
        answer = action(worker_client, "transition:close", login)
        assert Ticket.objects.get(pk=login.pk).status == "closed"

        assert take_back(worker_client, answer).status_code == 200

        assert Ticket.objects.get(pk=login.pk).status == "open"

    def test_an_undo_is_done_once(self, worker_client, support_desk):
        answer = action(
            worker_client, "mark_billable", support_desk["invoice"]
        )
        assert take_back(worker_client, answer).status_code == 200

        again = take_back(worker_client, answer)

        assert again.status_code == 409
        assert "has changed since" in again.json()["detail"]


class TestAfterADelete:
    def test_deleted_records_come_back_with_what_went_with_them(
        self, worker_client, support_desk
    ):
        login = support_desk["login"]
        comments = list(
            login.comments.order_by("pk").values_list("pk", "body")
        )
        answer = action(worker_client, "delete_selected", login)
        assert not Ticket.objects.filter(pk=login.pk).exists()

        response = take_back(worker_client, answer)

        assert response.status_code == 200, response.content
        back = Ticket.objects.get(pk=login.pk)
        assert back.reference == "SD-1"
        assert back.opened_at == login.opened_at
        assert {tag.name for tag in back.tags.all()} == {
            "regression",
            "release",
        }
        assert (
            list(back.comments.order_by("pk").values_list("pk", "body"))
            == comments
        )

    def test_the_api_delete_answers_its_undo_when_asked(
        self, worker_client, support_desk
    ):
        invoice = support_desk["invoice"]

        response = worker_client.delete(f"{TICKETS}{invoice.pk}/?undo=1")

        assert response.status_code == 200
        assert take_back(worker_client, response.json()).status_code == 200
        assert Ticket.objects.filter(pk=invoice.pk).exists()

    def test_the_api_delete_still_answers_204_otherwise(
        self, worker_client, support_desk
    ):
        invoice = support_desk["invoice"]

        response = worker_client.delete(f"{TICKETS}{invoice.pk}/")

        assert response.status_code == 204

    def test_a_record_moved_to_the_trash_comes_out_of_it(self, admin_client):
        from tests.testapp.models import Contract

        lease = Contract.objects.create(title="Lease")

        response = admin_client.delete(f"{CONTRACTS}{lease.pk}/?undo=1")
        assert response.status_code == 200
        lease.refresh_from_db()
        assert lease.deleted_at is not None

        assert (
            take_back(admin_client, response.json(), f"{CONTRACTS}undo/")
        ).status_code == 200
        lease.refresh_from_db()
        assert lease.deleted_at is None
        assert lease.deleted_by is None

    def test_the_delete_page_carries_the_undo_to_the_next_page(
        self, worker_client, support_desk
    ):
        invoice = support_desk["invoice"]
        url = site.get_resource(Ticket).get_delete_url(invoice.pk)

        response = worker_client.post(url, follow=True)

        assert response.status_code == 200
        content = response.content.decode()
        assert 'data-undo-url="/api/example/ticket/undo/"' in content
        assert "js-undo-message" in content
        assert "message--success" in content

    def test_nothing_is_offered_when_a_link_would_be_lost(self, admin_client):
        # A tag's tickets point at it through the ticket's own
        # many-to-many: deleting it unlinks them, which no version of
        # theirs records.
        assert not deletion_is_recorded(site, Tag)
        tag = Tag.objects.create(name="spare")

        response = admin_client.delete(f"/api/example/tag/{tag.pk}/?undo=1")

        assert response.status_code == 204

    def test_a_record_taken_again_since_stops_the_undo(
        self, worker_client, support_desk
    ):
        invoice = support_desk["invoice"]
        answer = worker_client.delete(f"{TICKETS}{invoice.pk}/?undo=1").json()
        Ticket.objects.create(
            pk=invoice.pk,
            reference="SD-9",
            title="New",
            team=support_desk["front"],
        )

        response = take_back(worker_client, answer)

        assert response.status_code == 409
        assert Ticket.objects.get(pk=invoice.pk).reference == "SD-9"


class TestAfterABulkEdit:
    def test_a_committed_bulk_edit_is_undone(self, admin_client, support_desk):
        login, invoice = support_desk["login"], support_desk["invoice"]
        response = post(
            admin_client,
            f"{TICKETS}bulk-edit/",
            {
                "ids": [str(login.pk), str(invoice.pk)],
                "changes": {"priority": {"mode": "set", "value": "urgent"}},
                "commit": True,
            },
        )
        answer = response.json()
        assert answer["undo"]["count"] == 2

        assert take_back(admin_client, answer).status_code == 200

        login.refresh_from_db()
        invoice.refresh_from_db()
        assert (login.priority, invoice.priority) == ("high", "normal")

    def test_a_review_offers_nothing(self, admin_client, support_desk):
        response = post(
            admin_client,
            f"{TICKETS}bulk-edit/",
            {
                "ids": [str(support_desk["login"].pk)],
                "changes": {"priority": {"mode": "set", "value": "urgent"}},
            },
        )

        assert "undo" not in response.json()


class TestRefusals:
    def test_another_persons_token_opens_nothing(
        self, worker_client, support_desk, client
    ):
        answer = action(
            worker_client, "mark_billable", support_desk["invoice"]
        )
        other = UserFactory()
        other.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label="example", codename="change_ticket"
            )
        )
        client.force_login(other)

        response = take_back(client, answer)

        assert response.status_code == 400
        support_desk["invoice"].refresh_from_db()
        assert support_desk["invoice"].is_billable is True

    def test_another_resources_endpoint_refuses_the_token(
        self, worker_client, support_desk
    ):
        answer = action(
            worker_client, "mark_billable", support_desk["invoice"]
        )

        response = take_back(
            worker_client, answer, "/api/example/ticketcomment/undo/"
        )

        assert response.status_code == 400

    def test_a_token_too_old_has_expired(self, worker_client, support_desk):
        answer = action(
            worker_client, "mark_billable", support_desk["invoice"]
        )

        later = time.time() + 601
        with mock.patch("django.core.signing.time.time", return_value=later):
            response = take_back(worker_client, answer)

        assert response.status_code == 400
        assert response.json()["detail"] == "This can no longer be undone."

    @pytest.mark.parametrize("token", ["", "forged", None, 3])
    def test_a_bad_token_is_a_400(self, worker_client, token):
        response = post(worker_client, f"{TICKETS}undo/", {"token": token})

        assert response.status_code == 400

    def test_a_change_made_since_stops_everything(
        self, worker_client, support_desk
    ):
        invoice, export = support_desk["invoice"], support_desk["export"]
        answer = action(worker_client, "mark_billable", invoice, export)
        export.title = "Changed by somebody else"
        export.save()

        response = take_back(worker_client, answer)

        assert response.status_code == 409
        assert "has changed since" in response.json()["detail"]
        invoice.refresh_from_db()
        assert invoice.is_billable is True

    def test_without_the_permission_any_more_nothing_is_undone(
        self, worker_client, worker, support_desk
    ):
        invoice = support_desk["invoice"]
        answer = action(worker_client, "mark_billable", invoice)
        worker.user_permissions.remove(
            Permission.objects.get(
                content_type__app_label="example", codename="change_ticket"
            )
        )

        response = take_back(worker_client, answer)

        assert response.status_code == 403
        invoice.refresh_from_db()
        assert invoice.is_billable is True

    def test_a_resource_may_offer_none(self, worker_client, support_desk):
        resource = site.get_resource(Ticket)

        with mock.patch.object(resource, "undo", False):
            answer = action(
                worker_client, "mark_billable", support_desk["invoice"]
            )

        assert "undo" not in answer

    @override_settings(GENERIC={"UNDO_SECONDS": None})
    def test_a_project_may_offer_none(self, worker_client, support_desk):
        answer = action(
            worker_client, "mark_billable", support_desk["invoice"]
        )

        assert "undo" not in answer


class TestFromCode:
    def request(self, user):
        request = RequestFactory().post("/")
        request.user = user

        return request

    def test_records_created_are_deleted(self, admin_user, support_desk):
        resource = site.get_resource(TicketComment)
        request = self.request(admin_user)

        with capture() as captured, acting_as(admin_user):
            note = TicketComment.objects.create(
                ticket=support_desk["invoice"], author="Bot", body="Auto."
            )

        offered = offer(resource, request, captured)
        undo(resource, request, offered["token"])

        assert not TicketComment.objects.filter(pk=note.pk).exists()

    def test_a_change_with_no_version_before_is_not_offered(
        self, admin_user, support_desk
    ):
        resource = site.get_resource(Ticket)
        invoice = support_desk["invoice"]
        HistoryEntry.objects.filter(object_id=str(invoice.pk)).delete()

        with capture() as captured, acting_as(admin_user):
            invoice.title = "Renamed"
            invoice.save()

        assert offer(resource, self.request(admin_user), captured) is None

    def test_nothing_written_offers_nothing(self, admin_user):
        resource = site.get_resource(Ticket)

        with capture() as captured:
            pass

        assert offer(resource, self.request(admin_user), captured) is None

    def test_refused_names_its_status(self):
        assert Refused("no").status == 409


class TestTheMessage:
    def test_an_offer_travels_as_one_tag(self):
        tags = message_tags({"url": "/api/x/undo/", "token": "a:b"})

        assert tags.startswith(MESSAGE_TAG)
        assert from_message_tags(f"success {tags}") == {
            "url": "/api/x/undo/",
            "token": "a:b",
            "label": "Undo",
        }

    def test_another_site_is_not_read(self):
        tags = message_tags({"url": "//elsewhere/undo/", "token": "t"})

        assert from_message_tags(tags) is None

    def test_the_token_is_no_level(self):
        # Letters of a token may spell "error"; the message is a success.
        tags = f"{MESSAGE_TAG}/api/x/undo/|xerrorx success"

        assert message_icon(tags) == "success"
