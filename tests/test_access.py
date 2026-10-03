"""The access log: who opened a record, who downloaded its files - and
``may_download``, a resource's word on each file.

``ContractResource`` declares ``access_log = True``, and lets only a
superuser download a signed contract's file.
"""

from __future__ import annotations

import datetime

import pytest
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework.test import APIClient

from generic.access import accesses_of, prune, record
from generic.access.models import AccessEntry
from generic.sites import site
from tests.factories import UserFactory
from tests.testapp.models import Contract, Document

pytestmark = pytest.mark.django_db

API = "/api/testapp/contract/"
PDF = b"%PDF-1.4\n% a contract\n"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


def signed_in(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)

    return client


def reader_user():
    user = UserFactory(first_name="Rita", last_name="Reader")
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="testapp", codename="view_contract"
        )
    )

    return user


def contract(title: str = "Lease", **values) -> Contract:
    record = Contract(title=title, **values)
    record.file.save("lease.pdf", ContentFile(PDF), save=False)
    record.save()

    return record


class TestRecording:
    def test_opening_a_record_is_recorded_once(self):
        user = reader_user()
        client = signed_in(user)
        lease = contract()

        client.get(f"{API}{lease.pk}/summary/")
        client.get(f"{API}{lease.pk}/summary/")

        entries = list(accesses_of(lease))
        assert len(entries) == 1
        assert entries[0].action == AccessEntry.Action.VIEWED
        assert entries[0].user == user
        assert entries[0].user_label == "Rita Reader"
        assert entries[0].label == "Lease"
        assert entries[0].record_key == f"testapp.contract:{lease.pk}"

    def test_a_download_is_recorded_each_time(self):
        client = signed_in(reader_user())
        lease = contract()

        client.get(f"{API}{lease.pk}/files/file/")
        client.get(f"{API}{lease.pk}/files/file/")

        downloads = accesses_of(lease).filter(
            action=AccessEntry.Action.DOWNLOADED
        )
        assert downloads.count() == 2
        assert downloads.first().detail.endswith(".pdf")

    def test_a_resource_without_it_records_nothing(self, admin_user):
        document = Document(title="Report")
        document.file.save("report.pdf", ContentFile(PDF), save=False)
        document.save()

        signed_in(admin_user).get(
            f"/api/testapp/document/{document.pk}/summary/"
        )

        assert not AccessEntry.objects.exists()

    def test_nobody_signed_in_is_nobody_recorded(self, rf):
        request = rf.get("/")
        request.user = type("Anonymous", (), {"is_authenticated": False})()

        assert record(request, contract()) is None

    def test_the_address_is_the_servers(self, rf, admin_user):
        request = rf.get(
            "/", REMOTE_ADDR="10.0.0.7", HTTP_X_FORWARDED_FOR="1.2.3.4"
        )
        request.user = admin_user

        entry = record(request, contract(), action="downloaded", detail="x")

        assert entry.address == "10.0.0.7"


class TestScreen:
    def test_the_screen_is_registered(self):
        assert site.is_registered(AccessEntry)

    def test_the_record_page_links_to_its_accesses(self, client, admin_user):
        client.force_login(admin_user)
        lease = contract()

        page = client.get(f"/testapp/contract/{lease.pk}/").content.decode()

        assert "/generic/accessentry/?filters=" in page
        assert f"testapp.contract%3A{lease.pk}" in page

    def test_a_reader_without_the_permission_gets_no_link(self, client):
        user = reader_user()
        client.force_login(user)
        lease = contract()

        page = client.get(f"/testapp/contract/{lease.pk}/").content.decode()

        assert "/generic/accessentry/" not in page

    def test_the_list_filters_on_the_record(self, admin_user):
        client = signed_in(admin_user)
        lease, loan = contract(), contract("Loan")
        client.get(f"{API}{lease.pk}/summary/")
        client.get(f"{API}{loan.pk}/summary/")

        body = client.get(
            "/api/generic/accessentry/",
            {
                "draw": 1,
                "filters": (
                    '{"match":"all","conditions":[{"column":"record_key",'
                    f'"operator":"equals","value":"testapp.contract:{lease.pk}"'
                    "}]}"
                ),
            },
        ).json()

        assert [row["label"] for row in body["data"]] == ["Lease"]

    def test_nobody_writes_in_it(self, admin_user):
        resource = site.get_resource(AccessEntry)
        request = type("Request", (), {"user": admin_user})()

        assert not resource.has_add_permission(request)
        assert not resource.has_change_permission(request)
        assert not resource.has_delete_permission(request)


class TestPrune:
    def test_it_deletes_what_is_older(self, admin_user, rf):
        request = rf.get("/")
        request.user = admin_user
        old = record(request, contract(), action="downloaded", detail="a")
        record(request, contract("Loan"), action="downloaded", detail="b")
        AccessEntry.objects.filter(pk=old.pk).update(
            at=timezone.now() - datetime.timedelta(days=100)
        )

        assert prune(30) == 1
        assert AccessEntry.objects.count() == 1

    def test_by_default_it_keeps_everything(self):
        assert prune() == 0


class TestMayDownload:
    def test_a_refused_file_is_a_404(self):
        client = signed_in(reader_user())
        signed = contract(signed=True)

        response = client.get(f"{API}{signed.pk}/files/file/")

        assert response.status_code == 404
        assert not AccessEntry.objects.filter(action="downloaded").exists()

    def test_whoever_it_allows_downloads(self, admin_user):
        signed = contract(signed=True)

        response = signed_in(admin_user).get(f"{API}{signed.pk}/files/file/")

        assert response.status_code == 200

    def test_the_summary_leaves_the_link_out(self):
        client = signed_in(reader_user())
        signed, draft = contract(signed=True), contract("Draft")

        def file_entry(pk):
            body = client.get(f"{API}{pk}/summary/").json()

            return next(
                entry
                for section in body["sections"]
                for entry in section["fields"]
                if entry["name"] == "file"
            )

        assert file_entry(signed.pk)["url"] == ""
        assert file_entry(draft.pk)["url"].endswith("/files/file/")

    def test_the_form_leaves_the_link_out(self):
        client = signed_in(reader_user())
        signed = contract(signed=True)

        body = client.get(f"{API}{signed.pk}/").json()

        assert body["file"]["url"] is None
