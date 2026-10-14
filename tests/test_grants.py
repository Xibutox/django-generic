"""Rights given on request: exporting tables, downloading files.

Off by default - everyone who reads a list exports it. With
``ACCESS_ON_REQUEST`` each is a permission every export and download
checks; people without it ask, superusers and holders of
``generic.validate_accessrequest`` grant or refuse, and asking again
reminds them no more than once an ``ACCESS_REQUEST_INTERVAL``.
"""

from __future__ import annotations

import datetime

import pytest
from django.contrib.auth.models import Group, Permission
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from generic import grants
from generic.events.models import Notification
from generic.grants.models import AccessRequest
from generic.grants.resources import AccessRequestResource, register_screens
from generic.sites import site
from tests.factories import UserFactory
from tests.testapp.models import Document

pytestmark = pytest.mark.django_db

ASK = "/api/generic/access-requests/"
API = "/api/testapp/document/"
PDF = b"%PDF-1.4\n% a small document\n"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def gated(settings):
    settings.GENERIC = {
        **settings.GENERIC,
        "ACCESS_ON_REQUEST": ("export", "download"),
    }


@pytest.fixture(scope="module")
def registered():
    """The Access requests screen, as a project giving a right on
    request has it from start-up: registered, and the site's pages
    built again around it."""
    import importlib

    from django.urls import clear_url_caches

    from tests import grants_urls

    already = site.is_registered(AccessRequest)

    if not already:
        site.register(AccessRequest, AccessRequestResource)

    importlib.reload(grants_urls)
    clear_url_caches()

    yield site.get_resource(AccessRequest)

    if not already:
        site.unregister(AccessRequest)

    clear_url_caches()


@pytest.fixture
def screen(registered, gated, settings):
    settings.ROOT_URLCONF = "tests.grants_urls"

    return registered


def permissions(*names: str) -> list[Permission]:
    found = []

    for name in names:
        app_label, codename = name.split(".")
        found.append(
            Permission.objects.get(
                content_type__app_label=app_label, codename=codename
            )
        )

    return found


def person(*names: str, **values):
    user = UserFactory(**values)
    user.user_permissions.add(*permissions("testapp.view_document", *names))

    return user


def signed_in(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)

    return client


def document() -> Document:
    record = Document(title="Report")
    record.file.save("report.pdf", ContentFile(PDF), save=False)
    record.save()

    return record


def ago(**delta) -> datetime.datetime:
    return timezone.now() - datetime.timedelta(**delta)


class TestOffByDefault:
    def test_everyone_who_reads_exports_and_downloads(self):
        client = signed_in(person())
        record = document()

        assert client.get(f"{API}export-csv/").status_code == 200
        assert client.get(f"{API}{record.pk}/files/file/").status_code == 200

    def test_pages_are_told_nothing(self):
        client = Client()
        client.force_login(person())

        response = client.get("/account/")

        assert response.context["chrome"]["client"]["access"] is None
        assert response.context["access_rights"] is False

    def test_asking_is_refused(self):
        response = signed_in(person()).post(ASK, {"kind": "export"})

        assert response.status_code == 400

    def test_the_screen_is_not_on_the_site(self):
        register_screens()

        assert not site.is_registered(AccessRequest)


class TestGated:
    def test_an_unknown_right_is_a_configuration_error(self, settings):
        settings.GENERIC = {"ACCESS_ON_REQUEST": ("print",)}

        with pytest.raises(ImproperlyConfigured, match="print"):
            grants.gated()

    def test_an_export_needs_the_permission(self, gated):
        response = signed_in(person()).get(f"{API}export-csv/")

        assert response.status_code == 403
        assert "ask for it" in response.json()["detail"]
        assert signed_in(person()).get(f"{API}export/").status_code == 403

    def test_the_permission_or_a_superuser_exports(self, gated, admin_user):
        allowed = person("generic.export_rows")

        assert signed_in(allowed).get(f"{API}export-csv/").status_code == 200
        assert signed_in(admin_user).get(f"{API}export/").status_code == 200

    def test_a_group_gives_it_too(self, gated):
        group = Group.objects.create(name="Exporters")
        group.permissions.add(*permissions("generic.export_rows"))
        user = person()
        user.groups.add(group)

        assert signed_in(user).get(f"{API}export-csv/").status_code == 200

    def test_a_download_needs_the_permission(self, gated):
        record = document()
        url = f"{API}{record.pk}/files/file/"

        assert signed_in(person()).get(url).status_code == 403
        allowed = person("generic.download_files")
        assert signed_in(allowed).get(url).status_code == 200

    def test_the_summary_shows_no_link_without_it(self, gated):
        record = document()

        def link(user):
            summary = signed_in(user).get(f"{API}{record.pk}/summary/").json()
            entries = {
                entry["name"]: entry
                for section in summary["sections"]
                for entry in section["fields"]
            }

            return entries["file"]["url"]

        assert not link(person())
        assert link(person("generic.download_files")) == (
            f"{API}{record.pk}/files/file/"
        )

    def test_one_right_alone(self, settings):
        settings.GENERIC = {"ACCESS_ON_REQUEST": ("download",)}
        record = document()
        client = signed_in(person())

        assert client.get(f"{API}export-csv/").status_code == 200
        assert client.get(f"{API}{record.pk}/files/file/").status_code == 403

    def test_pages_know_what_is_missing(self, gated):
        client = Client()
        client.force_login(person("generic.download_files"))

        response = client.get("/account/")
        access = response.context["chrome"]["client"]["access"]

        assert access == {"url": ASK, "missing": ["export"], "disclaimers": {}}
        assert response.context["access_rights"] is True

    def test_a_mailing_needs_the_export(self, gated):
        from generic.mailings.sending import MailingProblem, check

        mailing = type("Mailing", (), {"table": "site.testapp.document"})

        with pytest.raises(MailingProblem, match="export"):
            check(mailing, person())


class TestAsking:
    def test_the_people_who_decide_are_told(
        self, gated, admin_user, django_capture_on_commit_callbacks
    ):
        validator = person(grants.VALIDATE, email="val@example.test")
        bystander = person()
        user = person(first_name="Rita", last_name="Reader")

        with django_capture_on_commit_callbacks(execute=True):
            response = signed_in(user).post(
                ASK,
                {"kind": "export", "message": "For the audit", "page": "/x/"},
                format="json",
            )

        assert response.status_code == 201
        assert response.json()["created"] is True
        request = AccessRequest.objects.get()
        assert (request.user, request.kind, request.status) == (
            user,
            "export",
            AccessRequest.Status.PENDING,
        )
        assert request.message == "For the audit"
        assert request.page == "/x/"
        assert request.notified_at is not None

        told = set(Notification.objects.values_list("user", flat=True))
        assert told == {admin_user.pk, validator.pk}
        assert bystander.pk not in told
        notification = Notification.objects.get(user=validator)
        assert notification.title == "Rita Reader asks: Export tables"
        assert notification.body == "For the audit"
        assert {message.to[0] for message in mail.outbox} >= {
            "val@example.test"
        }

    def test_asking_again_too_soon_is_refused_kindly(
        self, gated, django_capture_on_commit_callbacks
    ):
        client = signed_in(person())

        with django_capture_on_commit_callbacks(execute=True):
            client.post(ASK, {"kind": "export"})
            response = client.post(ASK, {"kind": "export"})

        assert response.status_code == 429
        assert "you can remind the administrators" in response.json()["detail"]
        assert response.json()["retryAt"]
        assert AccessRequest.objects.get().times_asked == 1

    def test_the_wait_is_per_right(self, gated):
        client = signed_in(person())

        assert client.post(ASK, {"kind": "export"}).status_code == 201
        assert client.post(ASK, {"kind": "download"}).status_code == 201

    def test_asking_again_later_reminds(
        self, gated, admin_user, django_capture_on_commit_callbacks
    ):
        user = person()
        AccessRequest.objects.create(
            user=user,
            kind="export",
            asked_at=ago(hours=3),
            last_asked_at=ago(hours=2),
        )

        with django_capture_on_commit_callbacks(execute=True):
            response = signed_in(user).post(ASK, {"kind": "export"})

        assert response.status_code == 200
        assert response.json()["created"] is False
        request = AccessRequest.objects.get()
        assert request.times_asked == 2
        assert request.last_asked_at > ago(minutes=1)
        assert Notification.objects.get(user=admin_user).title.endswith(
            "asks again: Export tables"
        )

    def test_the_interval_is_a_setting(self, settings):
        settings.GENERIC = {
            "ACCESS_ON_REQUEST": ("export",),
            "ACCESS_REQUEST_INTERVAL": 60,
        }
        user = person()
        AccessRequest.objects.create(
            user=user, kind="export", last_asked_at=ago(minutes=2)
        )

        assert signed_in(user).post(ASK, {"kind": "export"}).status_code == 200

    def test_nothing_to_ask_when_held(self, gated):
        client = signed_in(person("generic.export_rows"))

        response = client.post(ASK, {"kind": "export"})

        assert response.status_code == 400
        assert not AccessRequest.objects.exists()

    def test_an_unknown_right_is_refused(self, gated):
        response = signed_in(person()).post(ASK, {"kind": "delete"})

        assert response.status_code == 400

    def test_signed_in_only(self, gated):
        assert APIClient().post(ASK, {"kind": "export"}).status_code in (
            401,
            403,
        )

    def test_where_one_stands(self, gated):
        user = person("generic.download_files")
        AccessRequest.objects.create(user=user, kind="export")

        rights = {
            row["kind"]: row
            for row in signed_in(user).get(ASK).json()["rights"]
        }

        assert rights["download"]["held"] is True
        assert rights["export"]["held"] is False
        assert rights["export"]["status"] == "pending"
        assert rights["export"]["retryAt"]

    def test_a_page_outside_the_site_is_not_kept(self, gated):
        signed_in(person()).post(
            ASK, {"kind": "export", "page": "https://evil.example/"}
        )

        assert AccessRequest.objects.get().page == ""


class TestDeciding:
    def run(self, resource, user, name, *requests):
        return signed_in(user).post(
            resource.get_actions_url(),
            {"action": name, "ids": [request.pk for request in requests]},
            format="json",
        )

    def test_granting_gives_the_permission_and_tells(
        self, screen, admin_user, django_capture_on_commit_callbacks
    ):
        user = person()
        request = AccessRequest.objects.create(
            user=user, kind="export", page="/testapp/document/"
        )

        with django_capture_on_commit_callbacks(execute=True):
            response = self.run(screen, admin_user, "grant_selected", request)

        assert response.status_code == 200
        request.refresh_from_db()
        assert request.status == AccessRequest.Status.GRANTED
        assert request.decided_by == admin_user
        assert request.decided_at is not None
        assert signed_in(user).get(f"{API}export-csv/").status_code == 200
        told = Notification.objects.get(user=user)
        assert told.title == "Granted: Export tables"
        assert told.url == "/testapp/document/"

    def test_refusing_tells_and_gives_nothing(
        self, screen, django_capture_on_commit_callbacks
    ):
        validator = person(grants.VALIDATE)
        user = person()
        request = AccessRequest.objects.create(user=user, kind="download")

        with django_capture_on_commit_callbacks(execute=True):
            self.run(screen, validator, "refuse_selected", request)

        request.refresh_from_db()
        assert request.status == AccessRequest.Status.REFUSED
        assert not grants.may(user, "download")
        assert Notification.objects.get(user=user).title == (
            "Refused: Download files"
        )

    def test_after_a_refusal_one_asks_anew_once_the_wait_is_over(self, gated):
        user = person()
        AccessRequest.objects.create(
            user=user,
            kind="export",
            status=AccessRequest.Status.REFUSED,
            last_asked_at=ago(minutes=10),
        )
        client = signed_in(user)

        assert client.post(ASK, {"kind": "export"}).status_code == 429

        AccessRequest.objects.update(last_asked_at=ago(hours=2))

        assert client.post(ASK, {"kind": "export"}).status_code == 201
        assert AccessRequest.objects.count() == 2

    def test_nobody_decides_on_their_own_request(self, screen):
        validator = person(grants.VALIDATE)
        request = AccessRequest.objects.create(user=validator, kind="export")

        response = self.run(screen, validator, "grant_selected", request)

        assert response.json()["level"] == "warning"
        request.refresh_from_db()
        assert request.is_pending
        assert not validator.has_perm("generic.export_rows")

    def test_a_decided_request_stays_decided(self, screen, admin_user):
        request = AccessRequest.objects.create(
            user=person(),
            kind="export",
            status=AccessRequest.Status.REFUSED,
        )

        self.run(screen, admin_user, "grant_selected", request)

        request.refresh_from_db()
        assert request.status == AccessRequest.Status.REFUSED

    def test_a_validator_reads_the_screen(self, screen):
        AccessRequest.objects.create(user=person(), kind="export")
        validator = signed_in(person(grants.VALIDATE))

        response = validator.get(
            screen.get_api_url(), {"format": "datatables"}
        )

        assert response.status_code == 200
        assert response.json()["recordsTotal"] == 1

    def test_others_do_not(self, screen):
        response = signed_in(person()).get(screen.get_api_url())

        assert response.status_code == 403

    def test_nobody_without_the_right_decides(self, screen):
        reader = person("generic.view_accessrequest")
        request = AccessRequest.objects.create(user=person(), kind="export")

        response = self.run(screen, reader, "grant_selected", request)

        assert response.status_code in (400, 403, 404)
        request.refresh_from_db()
        assert request.is_pending

    def test_the_screen_is_registered_when_gated(self, gated):
        before = site.get_resource(AccessRequest)

        if before is not None:
            site.unregister(AccessRequest)

        try:
            register_screens()

            assert site.is_registered(AccessRequest)
        finally:
            site.unregister(AccessRequest)

            if before is not None:
                site.register(AccessRequest, type(before))


class TestDisclaimers:
    """A reminder ticked before an export or a download: the page is
    told what to show; nothing is gated by it."""

    def config(self, user=None):
        client = Client()
        client.force_login(user or person())

        return client.get("/account/").context["chrome"]["client"]["access"]

    def test_none_by_default(self, gated):
        assert self.config()["disclaimers"] == {}

    def test_a_text_alone_gets_a_title_and_a_box(self, settings):
        settings.GENERIC = {"DOWNLOAD_DISCLAIMER": "Personal data inside."}

        access = self.config()

        assert access["url"] == ""
        assert access["missing"] == []
        assert access["disclaimers"] == {
            "download": {
                "title": "Before you download",
                "text": "Personal data inside.",
                "checkbox": (
                    "I have read this reminder and will handle the data "
                    "accordingly."
                ),
            }
        }

    def test_every_part_can_be_written(self, settings):
        settings.GENERIC = {
            "EXPORT_DISCLAIMER": {
                "title": "Privacy",
                "text": "Handle with care.",
                "checkbox": "I agree",
            }
        }

        assert self.config()["disclaimers"]["export"] == {
            "title": "Privacy",
            "text": "Handle with care.",
            "checkbox": "I agree",
        }

    def test_it_is_read_in_the_readers_language(self, settings):
        from django.utils import translation
        from django.utils.translation import gettext_lazy

        settings.GENERIC = {"EXPORT_DISCLAIMER": gettext_lazy("Cancel")}

        with translation.override("fr"):
            shown = grants.disclaimer("export")

        assert shown["text"] == "Annuler"
        assert shown["title"] == "Avant d'exporter"

    def test_a_typo_is_a_configuration_error(self, settings):
        settings.GENERIC = {"EXPORT_DISCLAIMER": {"txt": "Careful"}}

        with pytest.raises(ImproperlyConfigured, match="EXPORT_DISCLAIMER"):
            grants.disclaimer("export")

    def test_exports_still_work_without_ticking_on_the_server(self, settings):
        settings.GENERIC = {"EXPORT_DISCLAIMER": "Careful"}

        response = signed_in(person()).get(f"{API}export-csv/")

        assert response.status_code == 200
