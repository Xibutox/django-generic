"""Asking someone by e-mail to join a wiki."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from generic.wiki.models import Wiki, WikiInvitation, WikiMember
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

WIKIS = "/wiki/api/wikis/"


def send(client, method: str, url: str, data=None):
    return getattr(client, method)(url, data, content_type="application/json")


@pytest.fixture
def wiki():
    return Wiki.objects.create(name="Team", slug="team", access="private")


@pytest.fixture
def guest():
    return UserFactory(email="Guest@Example.com")


def invite(client, wiki, email="guest@example.com", role="editor"):
    return send(
        client,
        "post",
        f"{WIKIS}{wiki.pk}/invitations/",
        {"email": email, "role": role},
    )


def link_in(message) -> str:
    return re.search(r"https?://\S+", message.body).group(0)


class TestInvite:
    def test_an_e_mail_with_a_link(self, admin_client, wiki):
        response = invite(admin_client, wiki)

        assert response.status_code == 201
        assert response.json()["sent"] is True
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["guest@example.com"]
        assert "Team" in mail.outbox[0].subject
        assert "/wiki/invitations/" in link_in(mail.outbox[0])

    def test_only_a_digest_of_the_secret_is_kept(self, admin_client, wiki):
        invite(admin_client, wiki)
        secret = link_in(mail.outbox[0]).rstrip("/").rsplit("/", 1)[-1]

        assert WikiInvitation.objects.get().token != secret
        assert not WikiInvitation.objects.filter(token=secret).exists()

    def test_listed_until_accepted(self, admin_client, wiki):
        invite(admin_client, wiki)

        rows = admin_client.get(f"{WIKIS}{wiki.pk}/invitations/").json()

        assert [(row["email"], row["role"]) for row in rows] == [
            ("guest@example.com", "editor")
        ]

    def test_again_replaces_the_first(self, admin_client, wiki):
        invite(admin_client, wiki)
        invite(admin_client, wiki, email="GUEST@example.com", role="reader")

        assert WikiInvitation.objects.get().role == "reader"

    def test_a_bad_address_is_refused(self, admin_client, wiki):
        response = invite(admin_client, wiki, email="nobody")

        assert response.status_code == 400
        assert not mail.outbox

    def test_an_unknown_role_is_refused(self, admin_client, wiki):
        assert invite(admin_client, wiki, role="king").status_code == 400

    def test_only_who_manages_the_wiki(self, client, wiki):
        editor = UserFactory()
        WikiMember.objects.create(wiki=wiki, user=editor, role="editor")
        client.force_login(editor)

        assert invite(client, wiki).status_code == 403
        assert client.get(f"{WIKIS}{wiki.pk}/invitations/").status_code == 403

    def test_a_manager_invites(self, client, wiki):
        manager = UserFactory()
        WikiMember.objects.create(wiki=wiki, user=manager, role="manager")
        client.force_login(manager)

        assert invite(client, wiki).status_code == 201

    def test_withdrawn_its_link_stops_working(
        self, admin_client, client, wiki, guest
    ):
        invite(admin_client, wiki)
        link = link_in(mail.outbox[0])
        send(
            admin_client,
            "post",
            f"{WIKIS}{wiki.pk}/uninvite/",
            {"invitation": WikiInvitation.objects.get().pk},
        )
        client.force_login(guest)

        client.post(link)

        assert not WikiMember.objects.filter(user=guest).exists()


class TestAccept:
    def test_the_page_says_who_invites(
        self, admin_client, client, wiki, guest
    ):
        invite(admin_client, wiki)
        client.force_login(guest)

        response = client.get(link_in(mail.outbox[0]))

        assert response.status_code == 200
        assert "Accept the invitation" in response.content.decode()

    def test_opening_the_link_changes_nothing(
        self, admin_client, client, wiki, guest
    ):
        invite(admin_client, wiki)
        client.force_login(guest)

        client.get(link_in(mail.outbox[0]))

        assert not WikiMember.objects.filter(user=guest).exists()

    def test_accepted_makes_a_member(self, admin_client, client, wiki, guest):
        invite(admin_client, wiki)
        client.force_login(guest)

        response = client.post(link_in(mail.outbox[0]))

        assert response.status_code == 302
        assert response["Location"] == "/wiki/team/"
        assert WikiMember.objects.get(user=guest).role == "editor"
        assert client.get("/wiki/team/").status_code in (200, 302)

    def test_works_once(self, admin_client, client, wiki, guest):
        invite(admin_client, wiki)
        link = link_in(mail.outbox[0])
        client.force_login(guest)
        client.post(link)
        WikiMember.objects.all().delete()

        response = client.post(link)

        assert response.status_code == 200
        assert "already accepted" in response.content.decode()
        assert not WikiMember.objects.exists()

    def test_only_with_the_address_invited(self, admin_client, client, wiki):
        invite(admin_client, wiki)
        client.force_login(UserFactory(email="someone@else.org"))

        response = client.post(link_in(mail.outbox[0]))

        assert "guest@example.com" in response.content.decode()
        assert not WikiMember.objects.exists()

    def test_not_once_expired(self, admin_client, client, wiki, guest):
        invite(admin_client, wiki)
        WikiInvitation.objects.update(
            created_at=timezone.now() - timedelta(days=15)
        )
        client.force_login(guest)

        response = client.post(link_in(mail.outbox[0]))

        assert "expired" in response.content.decode()
        assert not WikiMember.objects.exists()
        assert admin_client.get(f"{WIKIS}{wiki.pk}/invitations/").json() == []

    def test_never_lowers_a_role(self, admin_client, client, wiki, guest):
        WikiMember.objects.create(wiki=wiki, user=guest, role="manager")
        invite(admin_client, wiki, role="reader")
        client.force_login(guest)

        client.post(link_in(mail.outbox[0]))

        assert WikiMember.objects.get(user=guest).role == "manager"

    def test_signed_out_is_asked_to_sign_in(self, admin_client, client, wiki):
        invite(admin_client, wiki)

        response = client.get(link_in(mail.outbox[0]))

        assert response.status_code == 302
        assert "invitations" in response["Location"]

    def test_an_unknown_link(self, client, guest):
        client.force_login(guest)

        response = client.get("/wiki/invitations/nothing/")

        assert "does not exist" in response.content.decode()
