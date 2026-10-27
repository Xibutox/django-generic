"""Personal data (generic.privacy): declared once, then found, exported,
anonymized - in the history too - and kept only as long as declared."""

from __future__ import annotations

import datetime
import io
import json

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from example.models import Agent, Team, Ticket, TicketComment
from generic import privacy
from generic.access.models import AccessEntry
from generic.audit.models import SecurityEvent
from generic.events.models import Notification
from generic.history import acting_as, history_of
from generic.history.models import HistoryEntry
from generic.privacy import PersonalData, Retention, Subject
from generic.privacy.inventory import inventory
from generic.retention import apply
from generic.sites import site
from tests.testapp.models import Author, Contract

pytestmark = pytest.mark.django_db


@pytest.fixture
def team():
    return Team.objects.create(name="Desk", code="DSK")


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        username="alice",
        email="alice@example.test",
        password="secret-pass-123",
        first_name="Alice",
        last_name="Martin",
    )


@pytest.fixture
def agent(team):
    """An agent whose address is alice's: the same person."""
    # Two units of work, so the history holds the name in two versions
    # whatever an earlier test left acting.
    with acting_as(None, source="Seed"):
        agent = Agent.objects.create(
            name="Alice Martin", email="Alice@Example.test", team=team
        )

    with acting_as(None, source="Seed"):
        agent.name = "Alice M. Martin"
        agent.save()

    return agent


@pytest.fixture
def registered():
    """Declarations given through ``register``, taken back after."""
    models = []

    def declare(model, declaration):
        privacy.register(model, declaration)
        models.append(model)

    yield declare

    for model in models:
        privacy.unregister(model)


# -- declaring -----------------------------------------------------------


@pytest.mark.parametrize(
    "declaration, message",
    [
        (PersonalData(fields={"nope": "blank"}), "no field 'nope'"),
        (PersonalData(fields={"name": "shred"}), "unknown way"),
        (PersonalData(fields={"name": "null"}), "not nullable"),
        (PersonalData(fields={"is_active": "blank"}), "neither empty"),
        (PersonalData(fields={"hired_on": "pseudonym"}), "not text"),
        (PersonalData(subject="team"), "must lead to the user model"),
        (PersonalData(subject="team__nope"), "leads nowhere"),
        (PersonalData(email="email"), "tuples of field names"),
        (PersonalData(marker="hired_on"), "nullable DateTimeField"),
        (
            PersonalData(retention=Retention(days=30, after="name")),
            "DateField or a DateTimeField",
        ),
        (
            PersonalData(retention=Retention(days=0, after="hired_on")),
            "1 or more",
        ),
        (
            PersonalData(
                retention=Retention(days=30, after="hired_on", action="burn")
            ),
            "action is one of",
        ),
        (
            PersonalData(
                retention=Retention(
                    days=30, after="hired_on", filter={"colour": "red"}
                )
            ),
            "filter does not apply",
        ),
    ],
)
def test_a_declaration_that_does_not_fit_raises(declaration, message):
    with pytest.raises(ImproperlyConfigured, match=message):
        declaration.check(Agent, "AgentResource.personal_data")


def test_a_resource_checks_its_declaration_when_registered():
    from generic.sites import GenericSite, ModelResource

    class Broken(ModelResource):
        personal_data = PersonalData(fields={"nope": "blank"})

    with pytest.raises(ImproperlyConfigured, match="Broken.personal_data"):
        GenericSite(name="privacy-test").register(Agent, Broken)


def test_the_user_model_is_declared_without_a_line(django_user_model):
    declaration = privacy.declarations()[django_user_model]

    assert dict(declaration.fields) == {
        "username": "pseudonym",
        "email": "blank",
        "first_name": "blank",
        "last_name": "blank",
    }
    assert declaration.email == ("email",)


# -- finding and exporting -----------------------------------------------


def test_a_user_finds_their_account_and_rows_sharing_their_address(
    alice, agent
):
    found = [obj for _d, obj in privacy.find(Subject(user=alice))]

    assert alice in found
    assert agent in found  # by address, whatever its case


def test_an_address_alone_finds_rows_without_an_account(agent):
    found = [
        obj for _d, obj in privacy.find(Subject(email="alice@example.test"))
    ]

    assert found == [agent]


def test_the_export_holds_the_declared_fields_and_the_references(alice, agent):
    Notification.objects.create(user=alice, title="Hello")
    data = privacy.export(Subject(user=alice))
    records = {record["model"]: record for record in data["records"]}

    assert data["subject"] == {"user": "alice"}
    assert records["example.agent"]["fields"] == {
        "name": "Alice M. Martin",
        "email": "Alice@Example.test",
        "hired_on": None,
        "team": agent.team_id,
    }
    # The account, whole - its password never.
    assert records["auth.user"]["fields"]["first_name"] == "Alice"
    assert "password" not in records["auth.user"]["fields"]
    assert any(
        ref["model"] == "generic.notification"
        and ref["field"] == "user"
        and ref["count"] == 1
        for ref in data["references"]
    )


def test_the_export_command_writes_json(alice, agent, tmp_path):
    target = tmp_path / "alice.json"
    out = io.StringIO()

    call_command(
        "personal_data",
        "export",
        "--user",
        "alice",
        "--output",
        target,
        stdout=out,
    )

    data = json.loads(target.read_text(encoding="utf-8"))
    assert {r["model"] for r in data["records"]} == {
        "auth.user",
        "example.agent",
    }
    assert "2 record(s)" in out.getvalue()


def test_a_command_without_a_person_or_with_a_stranger_refuses():
    with pytest.raises(CommandError, match="Name the person"):
        call_command("personal_data", "export")

    with pytest.raises(CommandError, match="No account 'nobody'"):
        call_command("personal_data", "export", "--user", "nobody")


# -- anonymizing ---------------------------------------------------------


def test_anonymizing_a_record_rewrites_its_history_too(agent):
    assert privacy.anonymize(agent) is True

    agent.refresh_from_db()
    assert agent.name == f"anonymous-{agent.pk}"
    assert agent.email == f"anonymous-{agent.pk}@anonymized.invalid"

    entries = list(history_of(agent))
    # What was done stays: one more version, saying so.
    assert [entry.source for entry in entries] == [
        privacy.SOURCE,
        "Seed",
        "Seed",
    ]

    for entry in entries:
        assert entry.values["name"] == f"anonymous-{agent.pk}"
        assert "Alice" not in json.dumps(entry.values)
        assert entry.label == f"anonymous-{agent.pk}"


def test_anonymizing_twice_changes_nothing_the_second_time(agent):
    privacy.anonymize(agent)
    versions = history_of(agent).count()

    assert privacy.anonymize(agent) is False
    assert history_of(agent).count() == versions


def test_the_access_log_forgets_what_the_record_was_called(agent):
    entry = AccessEntry.objects.create(
        content_type_id=HistoryEntry.objects.filter(object_id=agent.pk)
        .first()
        .content_type_id,
        object_id=str(agent.pk),
        record_key=f"example.agent:{agent.pk}",
        label="Alice M. Martin",
    )

    privacy.anonymize(agent)

    entry.refresh_from_db()
    assert entry.label == f"anonymous-{agent.pk}"


def test_an_anonymized_account_is_closed_and_forgotten(alice, agent):
    with acting_as(alice):
        Ticket.objects.create(title="Printer", team=agent.team)

    AccessEntry.objects.create(
        content_type_id=1,
        object_id="1",
        record_key="x:1",
        user=alice,
        user_label="Alice Martin",
        address="192.0.2.1",
    )
    SecurityEvent.objects.create(
        kind="login",
        user=alice,
        username="alice",
        address="192.0.2.1",
        user_agent="Firefox",
    )
    Notification.objects.create(user=alice, title="Hi")

    rows = privacy.anonymize_subject(Subject(user=alice))

    assert {obj._meta.label_lower for _d, obj in rows} == {
        "auth.user",
        "example.agent",
    }
    alice.refresh_from_db()
    assert alice.username == f"anonymous-{alice.pk}"
    assert (alice.email, alice.first_name, alice.last_name) == ("", "", "")
    assert not alice.is_active
    assert not alice.has_usable_password()

    # Their name, wherever it was copied, is the pseudonym now.
    assert set(
        HistoryEntry.objects.filter(user=alice).values_list(
            "user_label", flat=True
        )
    ) == {f"anonymous-{alice.pk}"}
    access = AccessEntry.objects.get(user=alice)
    assert (access.user_label, access.address) == (
        f"anonymous-{alice.pk}",
        None,
    )
    event = SecurityEvent.objects.get(user=alice)
    assert (event.username, event.address, event.user_agent) == (
        f"anonymous-{alice.pk}",
        None,
        "",
    )
    assert not Notification.objects.filter(user=alice).exists()
    # What they did stays theirs - an anonymous account's.
    assert Ticket.objects.get(title="Printer")


def test_the_anonymize_command_dry_runs_and_confirms(alice, agent):
    out = io.StringIO()
    call_command(
        "personal_data",
        "anonymize",
        "--user",
        "alice",
        "--dry-run",
        stdout=out,
    )

    assert "2 record(s) would be anonymized" in out.getvalue()
    alice.refresh_from_db()
    assert alice.username == "alice"

    call_command(
        "personal_data",
        "anonymize",
        "--email",
        "alice@example.test",
        "--no-input",
        stdout=out,
    )

    alice.refresh_from_db()
    assert alice.username == f"anonymous-{alice.pk}"


def test_a_blanked_file_is_deleted_from_the_storage(
    registered, django_capture_on_commit_callbacks
):
    registered(Contract, PersonalData(fields={"file": "blank"}))
    contract = Contract.objects.create(title="NDA")
    contract.file.save("nda.txt", ContentFile(b"signed by Alice"))
    storage, name = contract.file.storage, contract.file.name
    assert storage.exists(name)

    with django_capture_on_commit_callbacks(execute=True):
        privacy.anonymize(contract)

    contract.refresh_from_db()
    assert contract.file.name == ""
    assert not storage.exists(name)


def test_a_callable_anonymizes_as_it_says(registered):
    registered(
        Author,
        PersonalData(
            fields={"birth_date": lambda obj, name: datetime.date(1900, 1, 1)}
        ),
    )
    author = Author.objects.create(
        name="Ann", birth_date=datetime.date(1980, 5, 4)
    )

    privacy.anonymize(author)

    author.refresh_from_db()
    assert author.birth_date == datetime.date(1900, 1, 1)


def test_a_model_declaring_nothing_cannot_be_anonymized(team):
    with pytest.raises(ValueError, match="declares no personal data"):
        privacy.anonymize(team)


# -- the bulk action -----------------------------------------------------


def run_action(client, ids):
    resource = site.get_resource(Agent)

    return client.post(
        resource.get_actions_url(),
        {"action": privacy.ACTION_NAME, "ids": ids},
        content_type="application/json",
    )


def test_the_list_offers_anonymize_to_whoever_may_delete(admin_client, agent):
    response = run_action(admin_client, [agent.pk])

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["level"] == "success"
    # Never undone: the history it would restore from is rewritten.
    assert "undo" not in body
    agent.refresh_from_db()
    assert agent.name == f"anonymous-{agent.pk}"


def test_the_action_is_refused_without_the_delete_permission(
    client, django_user_model, agent
):
    from django.contrib.auth.models import Permission

    reader = django_user_model.objects.create_user(username="reader")
    reader.user_permissions.add(
        *Permission.objects.filter(codename__in=("view_agent", "change_agent"))
    )
    client.force_login(reader)
    resource = site.get_resource(Agent)

    class Request:
        user = reader

    assert privacy.ACTION_NAME not in resource.get_actions(Request())
    assert run_action(client, [agent.pk]).status_code in (400, 403)
    agent.refresh_from_db()
    assert agent.name == "Alice M. Martin"


# -- retention -----------------------------------------------------------


def comment(team, days_ago):
    ticket = Ticket.objects.create(
        reference=f"T-{days_ago}", title="Call back", team=team
    )

    return TicketComment.objects.create(
        ticket=ticket,
        author="Alice Martin",
        body="Done.",
        created_at=timezone.now() - datetime.timedelta(days=days_ago),
    )


def test_the_retention_anonymizes_what_is_past_it(team):
    old, recent = comment(team, 4 * 365), comment(team, 10)

    assert privacy.apply_retention(dry_run=True) == {
        "example.ticketcomment": 1
    }
    assert privacy.apply_retention() == {"example.ticketcomment": 1}

    old.refresh_from_db()
    recent.refresh_from_db()
    assert old.author == f"anonymous-{old.pk}"
    assert recent.author == "Alice Martin"
    # Done once: the next night finds nothing left to do.
    assert privacy.apply_retention() == {}


def test_apply_retention_runs_the_personal_data_retention(team):
    comment(team, 4 * 365)

    assert apply()["personal_data"] == 1


def test_a_retention_may_delete_and_leaves_no_name_in_the_history(
    registered,
):
    registered(
        Author,
        PersonalData(
            fields={"name": "pseudonym", "email": "blank"},
            retention=Retention(
                days=30,
                after="created_at",
                action="delete",
                filter={"is_active": False},
            ),
        ),
    )
    gone = Author.objects.create(name="Old", email="old@example.test")
    kept = Author.objects.create(
        name="Active", email="a@example.test", is_active=True
    )
    Author.objects.filter(pk__in=(gone.pk, kept.pk)).update(
        created_at=timezone.now() - datetime.timedelta(days=60)
    )
    Author.objects.filter(pk=gone.pk).update(is_active=False)
    out = io.StringIO()

    call_command("personal_data", "retention", stdout=out)

    assert "testapp.author: 1" in out.getvalue()
    assert not Author.objects.filter(pk=gone.pk).exists()
    assert Author.objects.filter(pk=kept.pk).exists()

    for entry in HistoryEntry.objects.filter(object_id=str(gone.pk)):
        if entry.content_type.model == "author":
            assert "Old" not in json.dumps(entry.values)
            assert entry.label == f"anonymous-{gone.pk}"


# -- inventory -----------------------------------------------------------


def test_the_inventory_names_declared_suspected_and_account_fields():
    findings = {(f.model, f.field): f.kind for f in inventory()}

    assert findings[("example.agent", "email")] == "declared"
    assert findings[("example.ticketcomment", "created_at")] == "retention"
    assert findings[("example.supplier", "phone")] == "suspected"
    assert findings[("generic.historyentry", "")] == "framework"
    # A relation to a person who is not an account is not one.
    assert ("example.ticket", "assignee") not in findings


def test_the_inventory_command_prints_text_or_json():
    out = io.StringIO()
    call_command("personal_data", "inventory", "--json", stdout=out)
    data = json.loads(out.getvalue())

    assert {"model", "field", "kind", "detail"} == set(data[0])

    out = io.StringIO()
    call_command("personal_data", "inventory", stdout=out)
    assert "look personal and are not declared" in out.getvalue()
