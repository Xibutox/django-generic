"""Records split between teams (``generic.teams``), and two form
additions the document manager needed: questions a form asks that are
not the model's (``form_extra_fields``) and the name a file is
downloaded under (``get_download_name``).

``tests.testapp``: a ``Binder`` is its team's (``team_field = "team"``),
a ``BinderSheet`` its binder's team's (``"binder__team"``), a
``SharedNote`` belongs to several teams (``"teams"``).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import serializers
from rest_framework.test import APIClient

from generic.sites import site
from generic.sites.serializers import build_form_serializer, without_fields
from generic.teams import (
    in_teams_of,
    leaders_of,
    scope_to_teams,
    sees_every_team,
    teams_of,
)
from generic.teams.models import Team
from tests.factories import UserFactory
from tests.testapp.models import Binder, BinderSheet, Manuscript, SharedNote

pytestmark = pytest.mark.django_db

BINDERS = "/api/testapp/binder/"
SHEETS = "/api/testapp/bindersheet/"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


def allowed(*codenames: str, teams=()):
    user = UserFactory()
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label__in=("testapp", "generic_teams"),
            codename__in=codenames,
        )
    )

    for team in teams:
        team.members.add(user)

    return user


def signed_in(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)

    return client


@pytest.fixture
def office(db) -> SimpleNamespace:
    """Two teams, a binder and a sheet each, a note shared by both."""
    legal = Team.objects.create(name="Legal")
    lab = Team.objects.create(name="Lab")
    contracts = Binder.objects.create(team=legal, title="Contracts")
    protocols = Binder.objects.create(team=lab, title="Protocols")
    shared = SharedNote.objects.create(title="Both")
    shared.teams.set([legal, lab])
    SharedNote.objects.create(title="Nobody's")

    return SimpleNamespace(
        legal=legal,
        lab=lab,
        contracts=contracts,
        protocols=protocols,
        nda=BinderSheet.objects.create(binder=contracts, title="NDA"),
        assay=BinderSheet.objects.create(binder=protocols, title="Assay"),
        shared=shared,
    )


def titles(queryset) -> list[str]:
    return sorted(queryset.values_list("title", flat=True))


# -- the scope, as a function -------------------------------------------------


def test_a_member_reaches_their_teams_records_only(office):
    user = allowed(teams=[office.legal])

    assert titles(scope_to_teams(Binder.objects.all(), user, "team")) == [
        "Contracts"
    ]
    assert titles(
        scope_to_teams(BinderSheet.objects.all(), user, "binder__team")
    ) == ["NDA"]


def test_a_record_of_two_teams_is_listed_once(office):
    user = allowed(teams=[office.legal, office.lab])
    scoped = scope_to_teams(SharedNote.objects.all(), user, "teams")

    assert titles(scoped) == ["Both"]


def test_the_teams_themselves_are_scoped_by_their_key(office):
    user = allowed(teams=[office.lab])

    assert list(scope_to_teams(Team.objects.all(), user, "pk")) == [office.lab]
    assert list(teams_of(user)) == [office.lab]


def test_the_permission_lifts_the_restriction(office):
    manager = allowed("see_every_team")

    assert sees_every_team(manager)
    assert titles(scope_to_teams(Binder.objects.all(), manager, "team")) == [
        "Contracts",
        "Protocols",
    ]
    assert teams_of(manager).count() == 2


def test_a_superuser_sees_every_team(office, admin_user):
    assert sees_every_team(admin_user)
    assert scope_to_teams(Binder.objects.all(), admin_user, "team").count()


def test_nobody_signed_in_reaches_nothing(office):
    assert not scope_to_teams(Binder.objects.all(), AnonymousUser(), "team")
    assert not teams_of(None).exists()


def test_a_member_of_no_team_reaches_nothing(office):
    assert not scope_to_teams(Binder.objects.all(), allowed(), "team")


def test_a_leader_reaches_their_teams_records_without_being_a_member(
    office,
):
    leader = allowed()
    office.lab.leaders.add(leader)

    assert titles(scope_to_teams(Binder.objects.all(), leader, "team")) == [
        "Protocols"
    ]
    assert list(teams_of(leader)) == [office.lab]


def test_a_leader_and_member_is_counted_once(office):
    user = allowed(teams=[office.lab])
    office.lab.leaders.add(user)

    assert list(teams_of(user)) == [office.lab]
    assert titles(scope_to_teams(SharedNote.objects.all(), user, "teams")) == [
        "Both"
    ]


def test_leaders_of_names_the_active_leaders_once(office):
    first, second, gone = allowed(), allowed(), allowed()
    gone.is_active = False
    gone.save()
    office.legal.leaders.add(first, gone)
    office.lab.leaders.add(first, second)

    assert set(leaders_of(office.legal)) == {first}
    assert sorted(
        user.pk for user in leaders_of(Team.objects.all())
    ) == sorted([first.pk, second.pk])
    assert not leaders_of([]).exists()


def test_in_teams_of_answers_for_one_record(office):
    user = allowed(teams=[office.legal])

    assert in_teams_of(user, office.contracts, "team")
    assert not in_teams_of(user, office.protocols, "team")


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("tem", "has no field 'tem'"),
        ("title", "is not a relation"),
        ("pk", "only a team is its own team"),
        ("sheets", None),
    ],
)
def test_a_wrong_path_is_a_declaration_error(path, message):
    if message is None:
        # A path through a many-valued relation is fine - to a team.
        with pytest.raises(ImproperlyConfigured, match="BinderSheet"):
            scope_to_teams(Binder.objects.all(), None, path)
        return

    with pytest.raises(ImproperlyConfigured, match=message):
        scope_to_teams(Binder.objects.all(), None, path)


# -- the resources ------------------------------------------------------------


def test_the_list_shows_the_readers_teams_rows(office):
    client = signed_in(allowed("view_binder", teams=[office.lab]))
    rows = client.get(BINDERS, {"draw": 1}).json()["data"]

    assert [row["title"] for row in rows] == ["Protocols"]


def test_another_teams_record_is_not_found(office):
    client = signed_in(allowed("view_binder", teams=[office.lab]))

    assert client.get(f"{BINDERS}{office.contracts.pk}/").status_code == 404
    assert (
        client.get(f"{BINDERS}{office.contracts.pk}/summary/").status_code
        == 404
    )


def test_the_teams_screen_shows_a_member_their_teams(office):
    client = signed_in(allowed("view_team", teams=[office.legal]))
    rows = client.get("/api/generic_teams/team/", {"draw": 1}).json()["data"]

    assert [row["name"] for row in rows] == ["Legal"]


def test_a_form_offers_only_the_readers_teams(office):
    client = signed_in(allowed("add_binder", "view_team", teams=[office.lab]))
    schema = client.get(f"{BINDERS}form-schema/").json()
    team = next(f for f in schema["fields"] if f["name"] == "team")
    found = client.get(
        "/api/generic_teams/team/autocomplete/", {"q": ""}
    ).json()

    assert "autocompleteUrl" in team
    assert [item["text"] for item in found["results"]] == ["Lab"]


def test_a_form_refuses_another_teams_key_sent_by_hand(office):
    client = signed_in(allowed("add_binder", teams=[office.lab]))

    response = client.post(
        BINDERS, {"title": "Mine", "team": office.legal.pk}, format="json"
    )

    assert response.status_code == 400
    assert "team" in response.json()
    assert not Binder.objects.filter(title="Mine").exists()

    response = client.post(
        BINDERS, {"title": "Mine", "team": office.lab.pk}, format="json"
    )
    assert response.status_code == 201, response.content


def test_a_relation_to_a_scoped_model_is_scoped_too(office):
    client = signed_in(allowed("add_bindersheet", teams=[office.lab]))

    refused = client.post(
        SHEETS,
        {"title": "Leak", "binder": office.contracts.pk},
        format="json",
    )
    taken = client.post(
        SHEETS,
        {"title": "Fine", "binder": office.protocols.pk},
        format="json",
    )

    assert refused.status_code == 400
    assert taken.status_code == 201


def test_a_relation_to_an_unscoped_model_is_left_alone(db):
    """Nothing changes for a resource that never asked."""
    resource = site.get_resource(Manuscript)

    assert (
        resource.get_relation_queryset(SimpleNamespace(user=AnonymousUser()))
        is None
    )


def test_scope_relations_turns_it_on_for_any_resource(db, rf):
    resource = site.get_resource(Manuscript)
    request = rf.get("/")
    request.user = AnonymousUser()
    resource.scope_relations = True

    try:
        assert resource.get_relation_queryset(request) is not None
    finally:
        del resource.scope_relations


def test_an_add_form_opens_on_the_readers_only_team(office, client):
    client.force_login(allowed("add_binder", teams=[office.lab]))
    initial = client.get("/testapp/binder/add/").context["form_config"][
        "initial"
    ]

    assert initial == {"team": str(office.lab.pk)}


def test_the_query_string_wins_over_the_team(office, client):
    client.force_login(allowed("add_binder", teams=[office.lab]))
    response = client.get("/testapp/binder/add/", {"title": "Given"})

    assert response.context["form_config"]["initial"]["title"] == "Given"


def test_a_reader_of_two_teams_chooses(office, client):
    client.force_login(allowed("add_binder", teams=[office.lab, office.legal]))
    initial = client.get("/testapp/binder/add/").context["form_config"][
        "initial"
    ]

    assert "team" not in initial


def test_a_watch_tells_only_the_records_teams(office):
    resource = site.get_resource(Binder)
    member = allowed("view_binder", teams=[office.legal])

    assert resource.may_watch(member, office.contracts)
    assert not resource.may_watch(member, office.protocols)


# -- questions a form asks that are not the model's -----------------------


def test_an_extra_field_is_write_only_and_reaches_save_model(office):
    client = signed_in(
        allowed("add_binder", "view_binder", teams=[office.lab])
    )
    schema = client.get(f"{BINDERS}form-schema/").json()
    reason = next(f for f in schema["fields"] if f["name"] == "reason")

    response = client.post(
        BINDERS,
        {"title": "Why", "team": office.lab.pk, "reason": "Asked for"},
        format="json",
    )

    assert reason["writeOnly"] is True
    assert response.status_code == 201, response.content
    assert "reason" not in response.json()
    assert Binder.objects.get(title="Why").note == "Asked for"


def test_an_extra_field_is_not_on_the_summary_page():
    fieldsets = ((None, {"fields": (("title", "reason"), "team")}),)

    assert without_fields(fieldsets, {"reason"}) == (
        (None, {"fields": ("title", "team")}),
    )
    assert without_fields(((None, {"fields": ("reason",)}),), {"reason"}) == ()


def test_an_extra_field_without_a_layout_comes_last():
    serializer = build_form_serializer(
        Binder,
        fields=["title"],
        extra_fields={"why": serializers.CharField(required=False)},
    )

    assert list(serializer().fields) == ["id", "title", "why"]


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"title": serializers.CharField()}, "a field of the model"),
        ({"why": "text"}, "must be a DRF serializer field"),
    ],
)
def test_a_wrong_extra_field_is_a_declaration_error(extra, message):
    with pytest.raises(ImproperlyConfigured, match=message):
        build_form_serializer(Binder, fields=["title"], extra_fields=extra)


# -- the name a file is downloaded under ------------------------------------


def test_a_file_is_downloaded_under_the_name_it_was_sent_with(office):
    client = signed_in(
        allowed("add_binder", "view_binder", teams=[office.legal])
    )
    payload = {"title": "Sent", "team": office.legal.pk}
    created = client.post(
        BINDERS,
        {
            "_payload": json.dumps(payload),
            "attachment": SimpleUploadedFile("Rapport final.pdf", b"%PDF"),
        },
        format="multipart",
    )
    pk = created.json()["id"]

    response = client.get(f"{BINDERS}{pk}/files/attachment/")

    assert response.status_code == 200
    assert 'filename="Rapport final.pdf"' in response["Content-Disposition"]
    assert response["Content-Type"] == "application/pdf"


def test_another_teams_file_is_not_found(office):
    office.contracts.attachment = SimpleUploadedFile("a.pdf", b"%PDF")
    office.contracts.save()
    client = signed_in(allowed("view_binder", teams=[office.lab]))

    response = client.get(f"{BINDERS}{office.contracts.pk}/files/attachment/")

    assert response.status_code == 404
