"""Messages: what an administrator says to some people, or to everyone.

Each recipient hears it the way everything else reaches them - a
notification, an e-mail or both - so these tests count notifications and
mails. A message leaves on commit, so the ones sent through the screen
commit first.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission

from generic.accounts.models import UserPreferences
from generic.events.messages import recipients, send
from generic.events.models import Message, Notification, NotificationLevel
from generic.events.resources import is_link
from generic.sites import site

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(django_user_model):
    """Three active accounts, one retired, and a group of two."""
    make = django_user_model.objects.create_user
    ann = make(username="ann", email="ann@example.test", password="x")
    bob = make(username="bob", email="bob@example.test", password="x")
    cat = make(username="cat", email="cat@example.test", password="x")
    old = make(
        username="old",
        email="old@example.test",
        password="x",
        is_active=False,
    )
    desk = Group.objects.create(name="Desk")
    desk.user_set.add(ann, bob, old)

    return {"ann": ann, "bob": bob, "cat": cat, "old": old, "desk": desk}


@pytest.fixture
def resource():
    return site.get_resource(Message)


@pytest.fixture
def sender(django_user_model):
    """Someone who may write messages and read them back, nothing more."""
    user = django_user_model.objects.create_user(
        username="sender",
        email="sender@example.test",
        password="x",
    )
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="generic",
            codename__in=("add_message", "view_message", "delete_message"),
        )
    )

    return user


@pytest.fixture
def sender_client(client, sender):
    client.force_login(sender)

    return client


def usernames(queryset):
    return sorted(user.username for user in queryset)


def told(user):
    return list(
        Notification.objects.filter(user=user).values_list("title", flat=True)
    )


class TestWhoItReaches:
    def test_the_people_chosen(self, people):
        chosen = recipients(users=[people["ann"], people["cat"]])

        assert usernames(chosen) == ["ann", "cat"]

    def test_the_active_members_of_a_group(self, people):
        assert usernames(recipients(groups=[people["desk"]])) == [
            "ann",
            "bob",
        ]

    def test_someone_chosen_twice_is_counted_once(self, people):
        chosen = recipients(users=[people["ann"]], groups=[people["desk"]])

        assert usernames(chosen) == ["ann", "bob"]

    def test_everyone_is_every_active_account(self, people, admin_user):
        chosen = recipients(everyone=True, users=[people["ann"]])

        assert usernames(chosen) == ["admin", "ann", "bob", "cat"]

    def test_nobody_chosen_is_nobody(self, people):
        assert list(recipients()) == []

    def test_a_retired_account_is_never_one(self, people):
        assert list(recipients(users=[people["old"]])) == []


class TestSending:
    def test_each_recipient_finds_a_notification(self, people):
        message = Message.objects.create(
            title="Lunch is on us",
            body="Friday, noon.",
            level=NotificationLevel.SUCCESS,
            url="/wiki/",
        )
        message.groups.add(people["desk"])

        assert send(message) == 2

        notification = Notification.objects.get(user=people["ann"])
        assert notification.title == "Lunch is on us"
        assert notification.body == "Friday, noon."
        assert notification.level == NotificationLevel.SUCCESS
        assert notification.url == "/wiki/"
        assert notification.content_object == message
        assert told(people["cat"]) == []

    def test_it_counts_whom_it_reached(self, people):
        message = Message.objects.create(title="Hello", everyone=True)
        send(message)
        message.refresh_from_db()

        assert message.recipient_count == 3

    def test_each_hears_as_they_chose(self, people, mailoutbox):
        UserPreferences.objects.create(
            user=people["bob"],
            notification_channel=UserPreferences.NotificationChannel.EMAIL,
        )
        message = Message.objects.create(title="Hello")
        message.groups.add(people["desk"])

        send(message)

        assert told(people["ann"]) == ["Hello"]
        assert told(people["bob"]) == []
        assert [mail.to for mail in mailoutbox] == [["bob@example.test"]]

    def test_the_message_may_override_their_choice(self, people, mailoutbox):
        UserPreferences.objects.create(
            user=people["bob"],
            notification_channel=UserPreferences.NotificationChannel.EMAIL,
        )
        message = Message.objects.create(
            title="Hello",
            delivery=Message.Delivery.BOTH,
        )
        message.users.add(people["ann"], people["bob"])

        send(message)

        assert Notification.objects.count() == 2
        # One each: a single mail to both would show each their address.
        assert sorted(mail.to for mail in mailoutbox) == [
            ["ann@example.test"],
            ["bob@example.test"],
        ]

    def test_in_the_application_only_sends_no_mail(self, people, mailoutbox):
        UserPreferences.objects.create(
            user=people["bob"],
            notification_channel=UserPreferences.NotificationChannel.EMAIL,
        )
        message = Message.objects.create(
            title="Hello",
            delivery=Message.Delivery.IN_APP,
        )
        message.users.add(people["bob"])

        send(message)

        assert told(people["bob"]) == ["Hello"]
        assert mailoutbox == []

    def test_everyone_s_preferences_are_read_at_once(
        self,
        people,
        django_assert_max_num_queries,
    ):
        for name in ("ann", "bob", "cat"):
            UserPreferences.objects.create(user=people[name], language="fr")

        message = Message.objects.create(title="Hello", everyone=True)

        # The recipients with their preferences, one insert, the count -
        # however many people there are.
        with django_assert_max_num_queries(6):
            send(message)

    def test_deleting_it_withdraws_what_it_left(self, people):
        message = Message.objects.create(title="Oops", everyone=True)
        send(message)

        message.delete()

        assert Notification.objects.count() == 0


class TestTheScreen:
    def payload(self, **values):
        return {"title": "Hello", "body": "", "level": 1, **values}

    def test_sending_one(
        self,
        sender_client,
        sender,
        people,
        resource,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = sender_client.post(
                resource.get_api_url(),
                self.payload(groups=[people["desk"].pk]),
                content_type="application/json",
            )

        assert response.status_code == 201, response.content
        message = Message.objects.get()
        assert message.sender == sender
        assert message.recipient_count == 2
        assert told(people["ann"]) == ["Hello"]

    def test_nothing_leaves_before_the_commit(
        self,
        sender_client,
        people,
        resource,
    ):
        response = sender_client.post(
            resource.get_api_url(),
            self.payload(users=[people["ann"].pk]),
            content_type="application/json",
        )

        assert response.status_code == 201
        assert Notification.objects.count() == 0

    def test_a_message_to_nobody_is_refused(
        self,
        sender_client,
        people,
        resource,
    ):
        response = sender_client.post(
            resource.get_api_url(),
            self.payload(users=[people["old"].pk]),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "users" in response.json()
        assert Message.objects.count() == 0

    @pytest.mark.parametrize(
        "url", ["javascript:alert(1)", "//elsewhere.test/", "ftp://files"]
    )
    def test_a_link_off_the_web_is_refused(
        self,
        sender_client,
        people,
        resource,
        url,
    ):
        response = sender_client.post(
            resource.get_api_url(),
            self.payload(everyone=True, url=url),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "url" in response.json()

    def test_it_takes_the_permission_to_send(
        self,
        client,
        people,
        resource,
    ):
        client.force_login(people["ann"])

        response = client.post(
            resource.get_api_url(),
            self.payload(everyone=True),
            content_type="application/json",
        )

        assert response.status_code == 403

    def test_a_sent_message_is_not_changed(
        self,
        admin_client,
        people,
        resource,
    ):
        message = Message.objects.create(title="Hello", everyone=True)

        response = admin_client.patch(
            resource.get_object_api_url(message.pk),
            {"title": "Goodbye"},
            content_type="application/json",
        )

        assert response.status_code == 403
        message.refresh_from_db()
        assert message.title == "Hello"

    def test_its_form_offers_nothing_to_continue_with(
        self,
        admin_client,
        resource,
    ):
        response = admin_client.get(resource.get_add_url())

        assert response.context["form_config"]["changeUrlTemplate"] == ""

    def test_the_list_counts_what_was_read(
        self, admin_client, people, resource
    ):
        message = Message.objects.create(title="Hello", everyone=True)
        send(message)
        Notification.objects.filter(user=people["ann"]).update(
            read_at="2026-09-26T10:00:00Z"
        )

        rows = admin_client.get(
            resource.get_api_url(), {"format": "datatables", "draw": 1}
        ).json()["data"]

        assert rows[0]["recipient_count"] == 4
        assert rows[0]["read"] == 1
        assert rows[0]["audience"] == "Everyone"


class TestFindingIt:
    def test_the_notifications_page_offers_to_write_one(
        self,
        sender_client,
        resource,
    ):
        response = sender_client.get("/notifications/")

        assert response.context["write_url"] == resource.get_add_url()

    def test_not_to_whoever_may_not(self, client, people):
        client.force_login(people["ann"])

        response = client.get("/notifications/")

        assert response.context["write_url"] == ""


class TestLinks:
    @pytest.mark.parametrize(
        "value", ["", "/tickets/", "https://example.test/", "http://intra/"]
    )
    def test_accepted(self, value):
        assert is_link(value)

    @pytest.mark.parametrize(
        "value", ["//elsewhere/", "javascript:x", "tickets/", "mailto:a@b"]
    )
    def test_refused(self, value):
        assert not is_link(value)
