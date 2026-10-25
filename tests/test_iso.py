"""The ISO 27001 apps (iso/): their rules, their buttons, their seed.

Each test is one rule an auditor relies on: the score of a risk, the
deadline of a breach notification, nobody approving their own change,
the checksum of a piece of evidence, an access review deactivating the
accounts decided as revoked.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.test import Client
from django.utils import timezone

pytestmark = pytest.mark.django_db


def person(username: str, *apps: str, superuser: bool = False):
    user = get_user_model().objects.create_user(
        username=username, password="x", is_superuser=superuser
    )
    if apps:
        user.user_permissions.set(
            Permission.objects.filter(content_type__app_label__in=apps)
        )
    return user


def client_for(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


def run(client: Client, model: str, name: str, ids: list[int]) -> Any:
    response = client.post(
        f"/api/{model}/actions/",
        json.dumps({"action": name, "ids": ids}),
        content_type="application/json",
    )
    response.ok = response.status_code == 200
    return response


def test_the_annex_a_catalogue_is_loaded_once():
    from iso.compliance.catalogue import ANNEX_A, load
    from iso.compliance.models import Control

    assert len(ANNEX_A) == 93
    assert Control.objects.count() == 93
    load(Control)
    assert Control.objects.count() == 93
    assert Control.objects.filter(theme="technological").count() == 34
    first = list(Control.objects.values_list("code", flat=True)[:3])
    assert first == ["5.1", "5.2", "5.3"]


def test_a_risk_is_scored_on_the_matrix():
    from iso.risks.models import Risk, level_of

    risk = Risk.objects.create(
        title="Ransomware",
        category="availability",
        threat="Ransomware",
        vulnerability="No patching",
        likelihood=4,
        impact=5,
        residual_likelihood=2,
        residual_impact=2,
    )

    assert (risk.score, risk.level) == (20, "critical")
    assert (risk.residual_score, risk.residual_level) == (4, "low")
    assert risk.reference == "RISK-0001"
    assert [level_of(s) for s in (4, 5, 10, 17)] == [
        "low",
        "medium",
        "high",
        "critical",
    ]


def test_accepting_a_risk_needs_the_permission():
    from iso.risks.models import Risk

    risk = Risk.objects.create(
        title="Provider outage",
        category="availability",
        threat="Outage",
        vulnerability="Single region",
        treatment="accept",
    )
    editor = person("editor", "risks")
    editor.user_permissions.remove(
        Permission.objects.get(codename="accept_risk")
    )

    refused = run(client_for(editor), "risks/risk", "accept", [risk.pk])
    assert refused.status_code in (400, 403)

    owner = person("owner", "risks")
    assert run(client_for(owner), "risks/risk", "accept", [risk.pk]).ok
    risk.refresh_from_db()
    assert risk.status == "accepted" and risk.accepted_by == owner


def test_a_breach_must_be_notified_within_72_hours():
    from iso.incidents.models import Incident

    incident = Incident.objects.create(
        title="Export sent to the wrong person",
        description="...",
        category="leak",
        personal_data_breach=True,
    )

    assert incident.reference.startswith(f"INC-{timezone.now().year}-")
    expected = incident.detected_at + datetime.timedelta(hours=72)
    assert incident.notification_due == expected
    assert not incident.notification_late

    Incident.objects.filter(pk=incident.pk).update(
        detected_at=timezone.now() - datetime.timedelta(hours=80)
    )
    incident.refresh_from_db()
    assert incident.notification_late


def test_evidence_keeps_the_checksum_of_its_file(settings, tmp_path):
    from iso.incidents.models import Evidence, Incident

    settings.MEDIA_ROOT = str(tmp_path)
    incident = Incident.objects.create(
        title="Malware", description="...", category="malware"
    )
    evidence = Evidence(incident=incident, title="Memory dump")
    evidence.file.save("dump.bin", ContentFile(b"evidence"), save=False)
    evidence.save()

    assert evidence.sha256 == hashlib.sha256(b"evidence").hexdigest()


def test_nobody_approves_their_own_change():
    from iso.changes.models import ChangeRequest

    requester = person("requester", "changes")
    approver = person("approver", "changes")
    client = client_for(requester)
    created = client.post(
        "/api/changes/changerequest/",
        json.dumps(
            {
                "title": "Upgrade the database",
                "description": "PostgreSQL 17",
                "category": "infrastructure",
            }
        ),
        content_type="application/json",
    )
    assert created.status_code == 201, created.content
    change = ChangeRequest.objects.get()
    assert change.requested_by == requester
    assert change.reference == "CHG-0001"

    assert run(client, "changes/changerequest", "submit", [change.pk]).ok
    run(client, "changes/changerequest", "approve", [change.pk])
    change.refresh_from_db()
    assert change.status == "submitted"

    answer = run(
        client_for(approver), "changes/changerequest", "approve", [change.pk]
    )
    assert answer.ok
    change.refresh_from_db()
    assert change.status == "approved" and change.approved_by == approver


def test_a_vulnerability_gets_its_deadline_from_its_severity(settings):
    from iso.vulnerabilities.models import Vulnerability

    today = timezone.localdate()
    critical = Vulnerability.objects.create(
        title="RCE", source="advisory", cvss=Decimal("9.8")
    )
    assert critical.severity == "critical"
    assert critical.due_on == today + datetime.timedelta(days=7)

    settings.ISO_VULNERABILITY_DAYS = {"low": 10}
    low = Vulnerability.objects.create(
        title="Banner", source="scanner", cvss=Decimal("2.0")
    )
    assert low.due_on == today + datetime.timedelta(days=10)

    late = Vulnerability.objects.create(
        title="Old",
        source="scanner",
        cvss=Decimal("7.5"),
        discovered_on=today - datetime.timedelta(days=60),
    )
    assert late.is_overdue
    late.status = "fixed"
    late.save()
    assert late.fixed_on == today and not late.is_overdue


def test_an_access_review_deactivates_the_revoked_accounts():
    from iso.access_reviews.models import AccessReview

    reviewer = person("reviewer", "access_reviews", "auth")
    leaver = person("leaver")
    admin = person("root", superuser=True)
    review = AccessReview.objects.create(title="Q1", reviewer=reviewer)
    client = client_for(reviewer)

    assert run(client, "access_reviews/accessreview", "collect", [review.pk])
    review.refresh_from_db()
    assert review.status == "in_progress"
    items = {item.account_label: item for item in review.items.all()}
    assert set(items) >= {"reviewer", "leaver", "root"}

    ids = [items[name].pk for name in ("reviewer", "leaver", "root")]
    model = "access_reviews/accessreviewitem"
    run(client, model, "revoke", ids)
    for item in items.values():
        item.refresh_from_db()
    # Nobody decides on their own account.
    assert items["reviewer"].decision == "pending"
    assert items["leaver"].decision == "revoke"
    assert items["leaver"].decided_by == reviewer

    run(client, model, "apply", ids)
    leaver.refresh_from_db()
    admin.refresh_from_db()
    assert not leaver.is_active
    # Only a superuser deactivates a superuser.
    assert admin.is_active


def test_a_policy_is_acknowledged_by_whoever_reads_it():
    from iso.isms.models import Acknowledgement, Policy

    policy = Policy.objects.create(
        code="POL-01",
        title="Security policy",
        version="2.0",
        status="approved",
    )
    reader = person("reader")
    reader.user_permissions.add(Permission.objects.get(codename="view_policy"))

    client = client_for(reader)
    assert run(client, "isms/policy", "acknowledge", [policy.pk]).ok
    run(client, "isms/policy", "acknowledge", [policy.pk])

    assert (
        Acknowledgement.objects.filter(
            policy=policy, user=reader, version="2.0"
        ).count()
        == 1
    )


def test_only_someone_else_verifies_a_corrective_action():
    from iso.audits.models import CorrectiveAction, Nonconformity

    owner = person("owner", "audits")
    auditor = person("auditor", "audits")
    finding = Nonconformity.objects.create(
        title="Logs kept too briefly", description="...", grade="minor"
    )
    action = CorrectiveAction.objects.create(
        nonconformity=finding,
        title="Longer retention",
        owner=owner,
        status="done",
    )
    model = "audits/correctiveaction"

    run(client_for(owner), model, "verify_effective", [action.pk])
    action.refresh_from_db()
    assert action.status == "done"

    assert run(client_for(auditor), model, "verify_effective", [action.pk]).ok
    action.refresh_from_db()
    finding.refresh_from_db()
    assert action.status == "effective" and action.verified_by == auditor
    assert finding.status == "closed" and finding.closed_on


def test_training_expires_and_a_leaver_has_steps_left():
    from iso.people.models import Course, PersonnelFile, TrainingRecord

    course = Course.objects.create(
        title="Awareness", topic="awareness", validity_months=12
    )
    user = person("newcomer")
    record = TrainingRecord.objects.create(
        course=course,
        person=user,
        completed_on=datetime.date(2025, 1, 31),
    )
    assert record.expires_on == datetime.date(2026, 1, 31)

    leaver = PersonnelFile.objects.create(full_name="Paul", status="leaving")
    assert leaver.missing_steps


def test_the_demo_data_is_seeded_once():
    from django.apps import apps

    from iso import demo
    from iso.assets.models import Asset
    from iso.risks.models import Risk

    records = demo.seed()
    counts = (Asset.objects.count(), Risk.objects.count())
    again = demo.seed()

    assert (Asset.objects.count(), Risk.objects.count()) == counts
    assert set(records) == set(again)
    # A record of every model of every ISO app.
    labels = [f"iso.{app}" for app in demo.ISO_APPS]
    models = [
        f"{model._meta.app_label}.{model._meta.model_name}"
        for model in apps.get_models()
        if model._meta.app_config.name in labels
    ]
    assert sorted(records) == sorted(models)


# -- Custom fields -------------------------------------------------------

#: The ISO resources open to custom fields (docs/custom-fields.md).
CUSTOMIZABLE = (
    "isms.policy",
    "assets.asset",
    "compliance.control",
    "risks.risk",
    "suppliers.supplier",
    "incidents.incident",
    "vulnerabilities.vulnerability",
    "changes.changerequest",
    "continuity.service",
    "audits.nonconformity",
    "people.personnelfile",
)


def custom_field(model, key: str, kind: str = "text", **options):
    from django.contrib.contenttypes.models import ContentType

    from generic.customfields.models import CustomField

    options.setdefault("labels", {"en": key.replace("_", " ").title()})
    return CustomField.objects.create(
        content_type=ContentType.objects.get_for_model(model),
        key=key,
        type=kind,
        **options,
    )


@pytest.mark.parametrize("label", CUSTOMIZABLE)
def test_the_main_records_are_open_to_custom_fields(label):
    from django.apps import apps

    from generic.customfields.definitions import (
        is_enabled,
        permission_codename,
    )
    from generic.sites import site
    from iso import demo

    model = apps.get_model(label)
    resource = site.get_resource(model)

    assert is_enabled(resource)
    assert resource.history, "custom values are versioned (generic.W013)"
    codename = permission_codename(model)
    assert Permission.objects.filter(
        content_type__app_label=model._meta.app_label, codename=codename
    ).exists()
    # The security officers manage the fields, the auditors do not.
    demo.create_users()
    app_label = model._meta.app_label
    assert (
        get_user_model()
        .objects.get(username="ciso")
        .has_perm(f"{app_label}.{codename}")
    )
    assert (
        not get_user_model()
        .objects.get(username="auditor")
        .has_perm(f"{app_label}.{codename}")
    ) or app_label == "audits"


def test_a_custom_value_goes_through_save_model():
    """A resource whose ``save_model`` adds its own values (the
    requester of a change) still writes the custom ones."""
    from generic.history.models import HistoryEntry
    from iso.changes.models import ChangeRequest

    custom_field(ChangeRequest, "ticket", labels={"en": "Ticket"})
    requester = person("requester", "changes")
    client = client_for(requester)
    created = client.post(
        "/api/changes/changerequest/",
        json.dumps(
            {
                "title": "Upgrade the database",
                "description": "PostgreSQL 17",
                "category": "infrastructure",
                "cf_ticket": "OPS-42",
            }
        ),
        content_type="application/json",
    )
    assert created.status_code == 201, created.content
    change = ChangeRequest.objects.get()
    assert change.requested_by == requester
    assert created.json()["cf_ticket"] == "OPS-42"

    changed = client.patch(
        f"/api/changes/changerequest/{change.pk}/",
        json.dumps({"cf_ticket": "OPS-43"}),
        content_type="application/json",
    )
    assert changed.status_code == 200, changed.content
    entry = HistoryEntry.objects.of(change).order_by("-version").first()
    assert entry.values["cf:ticket"] == "OPS-43"


def test_a_risk_list_filters_on_a_custom_field():
    from generic.customfields.values import write
    from generic.sites import site
    from iso.risks.models import Risk

    custom_field(Risk, "exposure", "decimal", decimal_places=2, unit="k€")
    common = {
        "category": "availability",
        "threat": "Ransomware",
        "vulnerability": "No patching",
        "likelihood": 3,
        "impact": 3,
    }
    high = Risk.objects.create(title="High", **common)
    low = Risk.objects.create(title="Low", **common)
    resource = site.get_resource(Risk)
    write(resource, high, {"exposure": Decimal("250")})
    write(resource, low, {"exposure": Decimal("5")})

    client = client_for(person("officer", "risks"))
    response = client.get(
        "/api/risks/risk/",
        {
            "draw": 1,
            "length": 100,
            "advanced_filters": json.dumps(
                {"cf_exposure": {"operator": "greater_than", "value": 100}}
            ),
        },
    )
    assert response.status_code == 200, response.content
    titles = [row["title"] for row in response.json()["data"]]
    assert titles == ["High"]


def test_the_demo_seeds_custom_fields_once():
    from generic.customfields.models import CustomField, CustomValue
    from iso import demo

    demo.seed()
    counts = (CustomField.objects.count(), CustomValue.objects.count())
    demo.seed()

    assert (
        CustomField.objects.count(),
        CustomValue.objects.count(),
    ) == counts
    keys = set(CustomField.objects.values_list("key", flat=True))
    assert {"warranty_ends", "data_location"} <= keys
    assert counts[1] > 0


def test_the_apps_speak_french():
    from django.utils import translation

    from iso.compliance.models import Control
    from iso.risks.models import Risk

    with translation.override("fr"):
        assert str(Risk._meta.verbose_name_plural) == "risques"
        assert Control.objects.get(code="8.17").get_theme_display() == (
            "Technologique"
        )
        assert str(translation.gettext("Statement of Applicability")) == (
            "Déclaration d'applicabilité"
        )
