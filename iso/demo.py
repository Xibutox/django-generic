"""Demo data for the ISO apps: a small company's ISMS, a year in.

``seed()`` fills every installed ISO app with records that make the
lists, charts and summary pages worth clicking through: assets with
holders, a risk register spread over the matrix, the Statement of
Applicability partly implemented, incidents at every step, an audit
with its findings. It is idempotent - each record is found by its
natural key before being created - so running it again tops up what is
missing and leaves the rest alone.

The ``seed_iso`` command calls it after creating the demo accounts; the
test suite calls it to have a record of every model.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files import File
from django.utils import timezone, translation

from iso.common import is_installed

ISO_APPS = (
    "isms",
    "assets",
    "compliance",
    "risks",
    "suppliers",
    "incidents",
    "vulnerabilities",
    "changes",
    "continuity",
    "audits",
    "people",
    "access_reviews",
)

#: username, first name, last name, job, department, group.
STAFF = (
    ("ciso", "Claire", "Morel", "CISO", "Security", "Security officers"),
    ("it", "Hugo", "Garnier", "IT manager", "IT", "Security officers"),
    ("auditor", "Ines", "Fabre", "Internal auditor", "Quality", "Auditors"),
    ("dev", "Lucas", "Perrin", "Developer", "Engineering", ""),
    ("sales", "Emma", "Roux", "Account manager", "Sales", ""),
)


#: The policies and procedures shipped with the apps, one Markdown file
#: per language in ``iso/documents/<language>/`` (README.md there).
DOCUMENTS = Path(__file__).resolve().parent / "documents"


def installed(app: str) -> bool:
    return is_installed(f"iso.{app}")


def create_users(password: str | None = None) -> dict[str, Any]:
    """The demo staff and the two ISO groups.

    *Security officers* may do everything in the ISO apps; *Auditors*
    read everything and record audits and findings. Accounts are only
    given a password when one is passed (``seed_iso`` does).
    """
    user_model = get_user_model()
    groups = {
        "Security officers": Group.objects.get_or_create(
            name="Security officers"
        )[0],
        "Auditors": Group.objects.get_or_create(name="Auditors")[0],
    }
    labels = [app for app in ISO_APPS if installed(app)]
    iso_permissions = Permission.objects.filter(
        content_type__app_label__in=labels
    )
    groups["Security officers"].permissions.set(iso_permissions)
    groups["Auditors"].permissions.set(
        iso_permissions.filter(codename__startswith="view_")
        | iso_permissions.filter(content_type__app_label="audits")
    )

    users = {}
    for username, first, last, _job, _department, group in STAFF:
        user, created = user_model.objects.get_or_create(
            username=username,
            defaults={
                "first_name": first,
                "last_name": last,
                "email": f"{username}@example.test",
            },
        )
        if password and created:
            user.set_password(password)
            user.save()
        if group:
            user.groups.add(groups[group])
        users[username] = user
    return users


def seed(users: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fill the installed ISO apps; returns one record per model,
    keyed ``"app_label.model"``."""
    users = users or create_users()
    records: dict[str, Any] = {}
    today = timezone.localdate()
    builders = (
        ("isms", seed_isms),
        ("assets", seed_assets),
        ("compliance", seed_compliance),
        ("risks", seed_risks),
        ("suppliers", seed_suppliers),
        ("incidents", seed_incidents),
        ("vulnerabilities", seed_vulnerabilities),
        ("changes", seed_changes),
        ("continuity", seed_continuity),
        ("audits", seed_audits),
        ("people", seed_people),
        ("access_reviews", seed_access_reviews),
    )
    for app, build in builders:
        if installed(app):
            build(users, records, today)
    records.pop("_assets", None)
    seed_custom_fields()
    return records


def document_language() -> str:
    """The language of the documents to attach: the active one when
    they exist in it (``seed_iso --language fr``), English otherwise."""
    language = (translation.get_language() or "en").split("-")[0]
    return language if (DOCUMENTS / language).is_dir() else "en"


def document_title(path: Path) -> str:
    """A document's first heading, without its code."""
    heading = path.read_text(encoding="utf-8").splitlines()[0]
    return heading.lstrip("# ").split(" ", 1)[1].strip()[:200]


def document_summary(path: Path) -> str:
    """The first paragraph of a document's purpose (section 1)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## 1"))
    paragraph: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip():
            paragraph.append(line.strip())
        elif paragraph:
            break
    return " ".join(paragraph)


def attach_document(policy: Any, path: Path, language: str) -> None:
    """Store the shipped document as the policy's file, and its purpose
    as the summary when there is none."""
    with path.open("rb") as handle:
        policy.document.save(
            f"{policy.code}-{path.stem}.{language}.md",
            File(handle),
            save=False,
        )
    if not policy.summary:
        policy.summary = document_summary(path)
    policy.save()


def days(count: int) -> datetime.timedelta:
    return datetime.timedelta(days=count)


def first(records: dict[str, Any], key: str) -> Any:
    return records.get(key)


# -- ISMS ----------------------------------------------------------------


def seed_isms(users: dict, records: dict, today: datetime.date) -> None:
    from iso.isms.models import (
        Acknowledgement,
        Contact,
        ContextIssue,
        InterestedParty,
        ManagementReview,
        Measurement,
        Objective,
        Policy,
        ReviewAction,
        Scope,
    )

    ciso = users["ciso"]
    records["isms.scope"] = Scope.objects.get_or_create(
        title="ISMS scope",
        defaults={
            "version": "2.0",
            "status": "approved",
            "statement": (
                "The design, development, hosting and support of the "
                "company's SaaS platform, from the Lyon and Paris "
                "offices, and the people, systems and suppliers that "
                "serve them."
            ),
            "exclusions": "The sales subsidiary in Madrid (own ISMS).",
            "interfaces": "Cloud hosting provider, payment provider.",
            "approved_by": ciso,
            "approved_on": today - days(200),
        },
    )[0]

    issues = (
        (
            "Growing ransomware threat on SMEs",
            "external",
            "technological",
            "threat",
            False,
        ),
        ("NIS 2 transposition", "external", "legal", "threat", False),
        (
            "Heatwaves straining the server room cooling",
            "external",
            "environmental",
            "threat",
            True,
        ),
        (
            "Remote work generalised",
            "internal",
            "organisational",
            "both",
            False,
        ),
        (
            "Customers asking for an ISO 27001 certificate",
            "external",
            "economic",
            "opportunity",
            False,
        ),
    )
    for title, kind, category, effect, climate in issues:
        issue = ContextIssue.objects.get_or_create(
            title=title,
            defaults={
                "kind": kind,
                "category": category,
                "effect": effect,
                "climate_related": climate,
                "reviewed_on": today - days(60),
            },
        )[0]
        records.setdefault("isms.contextissue", issue)

    parties = (
        (
            "Customers",
            "customer",
            "Confidentiality of their data, availability above 99.9%, "
            "certificate.",
            True,
        ),
        ("Employees", "employee", "Clear rules, training, privacy.", True),
        ("CNIL", "regulator", "GDPR compliance, breach notification.", True),
        (
            "Cloud hosting provider",
            "supplier",
            "Shared responsibility model respected.",
            False,
        ),
    )
    for name, kind, requirements, addressed in parties:
        party = InterestedParty.objects.get_or_create(
            name=name,
            defaults={
                "kind": kind,
                "requirements": requirements,
                "addressed": addressed,
                "reviewed_on": today - days(60),
            },
        )[0]
        records.setdefault("isms.interestedparty", party)

    objectives = (
        (
            "Staff trained in security awareness",
            "%",
            "higher",
            95,
            (78, 84, 90, 93),
        ),
        (
            "Critical vulnerabilities fixed within 7 days",
            "%",
            "higher",
            100,
            (70, 85, 92, 96),
        ),
        ("Phishing simulation click rate", "%", "lower", 5, (18, 12, 9, 7)),
    )
    for title, unit, direction, target, readings in objectives:
        objective, created = Objective.objects.get_or_create(
            title=title,
            defaults={
                "owner": ciso,
                "unit": unit,
                "direction": direction,
                "target": target,
                "due_on": today + days(120),
                "status": "on_track",
                "method": "Measured each quarter from the tools' reports.",
            },
        )
        records.setdefault("isms.objective", objective)
        if created:
            for index, value in enumerate(readings):
                Measurement.objects.create(
                    objective=objective,
                    measured_on=today - days(90 * (len(readings) - index)),
                    value=value,
                    measured_by=ciso,
                )
    records["isms.measurement"] = Measurement.objects.first()

    # code, title, acknowledged by everyone, document shipped with it.
    policies = (
        ("POL-01", "Information security policy", True, ""),
        ("POL-02", "Acceptable use policy", True, ""),
        ("POL-03", "Access control policy", False, "access-control"),
        ("POL-04", "Backup policy", False, "backup"),
        ("POL-05", "Supplier security policy", False, ""),
        (
            "POL-06",
            "Logging and monitoring policy",
            False,
            "logging-and-monitoring",
        ),
        ("POL-07", "Change management procedure", False, "change-management"),
        (
            "POL-08",
            "Incident management procedure",
            False,
            "incident-management",
        ),
        (
            "POL-09",
            "Vulnerability management procedure",
            False,
            "vulnerability-management",
        ),
    )
    language = document_language()
    for code, title, acknowledge, name in policies:
        path = DOCUMENTS / language / f"{name}.md" if name else None
        policy = Policy.objects.get_or_create(
            code=code,
            defaults={
                "title": document_title(path) if path else title,
                "version": "1.0" if path else "1.2",
                "status": "approved",
                "owner": ciso,
                "approved_by": ciso,
                "approved_on": today - days(300),
                "next_review_on": today + days(65 if acknowledge else -5),
                "requires_acknowledgement": acknowledge,
            },
        )[0]
        if path and not policy.document:
            attach_document(policy, path, language)
        records.setdefault("isms.policy", policy)
    policy = records["isms.policy"]
    for user in users.values():
        if user.username == "sales":
            continue  # someone has not read it yet
        records.setdefault(
            "isms.acknowledgement",
            Acknowledgement.objects.get_or_create(
                policy=policy, version=policy.version, user=user
            )[0],
        )

    contacts = (
        (
            "CNIL",
            "authority",
            "Personal data breach notification.",
            "https://notifications.cnil.fr",
        ),
        (
            "CERT-FR",
            "cert",
            "Incident reporting and advisories.",
            "https://www.cert.ssi.gouv.fr",
        ),
        ("Police - cybercrime unit", "police", "Filing a complaint.", ""),
    )
    for name, kind, purpose, url in contacts:
        records.setdefault(
            "isms.contact",
            Contact.objects.get_or_create(
                name=name,
                defaults={"kind": kind, "purpose": purpose, "url": url},
            )[0],
        )

    review, created = ManagementReview.objects.get_or_create(
        title=f"Management review {today.year - 1}",
        defaults={
            "held_on": today - days(150),
            "status": "held",
            "chair": ciso,
            "inputs": (
                "Audit results, objectives, incidents, risks, "
                "improvement opportunities."
            ),
            "decisions": "Budget for an EDR; second phishing campaign.",
        },
    )
    if created:
        review.attendees.set([ciso, users["it"], users["auditor"]])
    records["isms.managementreview"] = review
    for title, done in (
        ("Deploy an EDR on laptops", False),
        ("Run a second phishing campaign", True),
    ):
        records.setdefault(
            "isms.reviewaction",
            ReviewAction.objects.get_or_create(
                review=review,
                title=title,
                defaults={
                    "owner": users["it"],
                    "due_on": today + days(30),
                    "status": "done" if done else "open",
                },
            )[0],
        )


# -- Assets --------------------------------------------------------------


def seed_assets(users: dict, records: dict, today: datetime.date) -> None:
    from iso.assets.models import Asset, Assignment, Disposal, Maintenance

    it = users["it"]
    rows = (
        (
            "Customer database",
            "information",
            "restricted",
            3,
            3,
            3,
            True,
            "in_use",
            "",
        ),
        (
            "Production cluster",
            "service",
            "confidential",
            3,
            3,
            3,
            False,
            "in_use",
            "Cloud provider",
        ),
        (
            "Source code repository",
            "software",
            "confidential",
            3,
            3,
            2,
            False,
            "in_use",
            "GitHub",
        ),
        ("HR files", "information", "restricted", 3, 2, 1, True, "in_use", ""),
        (
            "Laptop LT-014",
            "hardware",
            "internal",
            2,
            2,
            2,
            False,
            "in_use",
            "Lenovo",
        ),
        (
            "Laptop LT-015",
            "hardware",
            "internal",
            2,
            2,
            2,
            False,
            "in_use",
            "Lenovo",
        ),
        (
            "Laptop LT-003",
            "hardware",
            "internal",
            2,
            2,
            1,
            False,
            "disposed",
            "Dell",
        ),
        (
            "Backup NAS",
            "hardware",
            "confidential",
            3,
            3,
            2,
            True,
            "maintenance",
            "Synology",
        ),
        ("Lyon office", "site", "internal", 1, 1, 2, False, "in_use", ""),
        (
            "Accounting software",
            "software",
            "confidential",
            2,
            3,
            2,
            True,
            "in_use",
            "Sage",
        ),
    )
    assets = {}
    for name, kind, classification, c, i, a, personal, status, vendor in rows:
        asset = Asset.objects.get_or_create(
            name=name,
            defaults={
                "kind": kind,
                "classification": classification,
                "confidentiality": c,
                "integrity": i,
                "availability": a,
                "personal_data": personal,
                "status": status,
                "vendor": vendor,
                "owner": it,
                "location": "Lyon" if kind == "hardware" else "",
                "acquired_on": today - days(700),
                "review_on": today + days(90),
            },
        )[0]
        assets[name] = asset
    records["assets.asset"] = assets["Customer database"]
    records["_assets"] = assets

    for asset_name, holder in (
        ("Laptop LT-014", "dev"),
        ("Laptop LT-015", "sales"),
    ):
        records.setdefault(
            "assets.assignment",
            Assignment.objects.get_or_create(
                asset=assets[asset_name],
                holder=users[holder],
                defaults={
                    "assigned_on": today - days(200),
                    "accepted_rules": True,
                    "condition": "New",
                },
            )[0],
        )
    records["assets.maintenance"] = Maintenance.objects.get_or_create(
        asset=assets["Backup NAS"],
        kind="corrective",
        defaults={
            "performed_by": "Hugo Garnier",
            "description": "Disk 3 replaced, array rebuilt.",
            "next_due_on": today + days(180),
        },
    )[0]
    records["assets.disposal"] = Disposal.objects.get_or_create(
        asset=assets["Laptop LT-003"],
        defaults={
            "method": "wipe",
            "standard": "NIST SP 800-88 Purge",
            "performed_by": "Recycling partner",
            "verified_by": it,
            "disposed_on": today - days(40),
        },
    )[0]


# -- Controls ------------------------------------------------------------


def seed_compliance(users: dict, records: dict, today: datetime.date) -> None:
    from iso.compliance.catalogue import load
    from iso.compliance.models import Control, ControlEvidence, Obligation

    load(Control)
    implemented = (
        "5.1",
        "5.2",
        "5.9",
        "5.10",
        "5.12",
        "5.15",
        "5.17",
        "5.24",
        "6.3",
        "8.5",
        "8.7",
        "8.8",
        "8.13",
        "8.15",
        "8.24",
        "8.32",
    )
    partial = ("5.7", "5.19", "5.30", "6.7", "8.9", "8.16")
    not_applicable = {
        "7.5": "No premises of our own beyond offices; hosting is "
        "outsourced.",
        "8.30": "No outsourced development.",
    }
    for control in Control.objects.filter(owner__isnull=True):
        if control.code in implemented:
            control.status = "implemented"
            control.implementation = "In place; see the evidence."
            control.reviewed_on = today - days(30)
        elif control.code in partial:
            control.status = "partial"
        elif control.code in not_applicable:
            control.applicable = False
            control.justification = not_applicable[control.code]
        else:
            control.status = "planned"
        control.owner = users["ciso"]
        control.save()
    control = Control.objects.get(code="8.13")
    records["compliance.control"] = control
    records["compliance.controlevidence"] = (
        ControlEvidence.objects.get_or_create(
            control=control,
            title="Restore test report",
            defaults={
                "url": "https://wiki.example.test/restore-test",
                "collected_by": users["it"],
            },
        )[0]
    )
    obligations = (
        ("GDPR", "regulation", "EU", "compliant", ("5.34", "5.24")),
        ("NIS 2 Directive", "law", "EU", "partial", ("5.24", "5.30")),
        (
            "Customer contract - security annex",
            "contract",
            "",
            "compliant",
            ("5.20",),
        ),
    )
    for title, kind, jurisdiction, status, codes in obligations:
        obligation, created = Obligation.objects.get_or_create(
            title=title,
            defaults={
                "kind": kind,
                "jurisdiction": jurisdiction,
                "requirement": "See the text; mapped to the controls.",
                "owner": users["ciso"],
                "status": status,
                "assessed_on": today - days(100),
                "next_review_on": today + days(265),
            },
        )
        if created:
            obligation.controls.set(Control.objects.filter(code__in=codes))
        records.setdefault("compliance.obligation", obligation)


# -- Risks ---------------------------------------------------------------


def seed_risks(users: dict, records: dict, today: datetime.date) -> None:
    from iso.risks.models import Risk, TreatmentAction

    assets = records.get("_assets", {})
    rows = (
        (
            "Ransomware encrypts the production data",
            "availability",
            "Ransomware",
            "Unpatched servers",
            3,
            5,
            "mitigate",
            2,
            4,
            "treating",
            ("Production cluster", "Backup NAS"),
            ("8.7", "8.13"),
        ),
        (
            "Customer data leaked by a misconfigured bucket",
            "confidentiality",
            "Misconfiguration",
            "No configuration review",
            3,
            4,
            "mitigate",
            1,
            4,
            "treating",
            ("Customer database",),
            ("8.9",),
        ),
        (
            "Laptop stolen with unencrypted data",
            "confidentiality",
            "Theft",
            "Disk encryption not enforced",
            4,
            2,
            "mitigate",
            2,
            1,
            "assessed",
            ("Laptop LT-014",),
            ("8.1",),
        ),
        (
            "Cloud provider outage",
            "availability",
            "Provider failure",
            "Single region",
            2,
            4,
            "accept",
            None,
            None,
            "accepted",
            ("Production cluster",),
            (),
        ),
        (
            "Phishing steals an administrator password",
            "integrity",
            "Phishing",
            "No MFA on every admin console",
            4,
            4,
            "mitigate",
            2,
            3,
            "treating",
            (),
            ("5.17", "6.3"),
        ),
        (
            "GDPR fine after a late breach notification",
            "compliance",
            "Regulator",
            "No documented breach procedure",
            2,
            3,
            "mitigate",
            1,
            3,
            "closed",
            (),
            ("5.24",),
        ),
    )
    for (
        title,
        category,
        threat,
        vulnerability,
        likelihood,
        impact,
        treatment,
        res_l,
        res_i,
        status,
        asset_names,
        codes,
    ) in rows:
        risk, created = Risk.objects.get_or_create(
            title=title,
            defaults={
                "category": category,
                "threat": threat,
                "vulnerability": vulnerability,
                "owner": users["ciso"],
                "likelihood": likelihood,
                "impact": impact,
                "treatment": treatment,
                "residual_likelihood": res_l,
                "residual_impact": res_i,
                "status": status,
                "accepted_by": users["ciso"] if status == "accepted" else None,
                "accepted_on": (
                    today - days(20) if status == "accepted" else None
                ),
                "next_review_on": today + days(90),
            },
        )
        records.setdefault("risks.risk", risk)
        if created:
            risk.assets.set([assets[n] for n in asset_names if n in assets])
            if installed("compliance"):
                from iso.compliance.models import Control

                risk.controls.set(Control.objects.filter(code__in=codes))
    risk = records["risks.risk"]
    records["risks.treatmentaction"] = TreatmentAction.objects.get_or_create(
        risk=risk,
        title="Immutable offsite backups",
        defaults={
            "owner": users["it"],
            "due_on": today + days(30),
            "status": "in_progress",
        },
    )[0]


# -- Suppliers -----------------------------------------------------------


def seed_suppliers(users: dict, records: dict, today: datetime.date) -> None:
    from iso.suppliers.models import Agreement, Assessment, Supplier

    rows = (
        (
            "Nimbus Cloud",
            "IaaS hosting",
            "critical",
            "personal",
            True,
            "ISO 27001, SOC 2",
        ),
        ("PayFlow", "Payment processing", "high", "personal", True, "PCI DSS"),
        ("CleanDesk", "Office cleaning", "low", "none", False, ""),
        (
            "MailRelay",
            "Transactional e-mail",
            "medium",
            "personal",
            True,
            "ISO 27001",
        ),
    )
    for name, services, criticality, data, cloud, certs in rows:
        supplier, created = Supplier.objects.get_or_create(
            name=name,
            defaults={
                "services": services,
                "criticality": criticality,
                "status": "active",
                "data_access": data,
                "cloud_service": cloud,
                "certifications": certs,
                "certification_expires_on": (
                    today + days(200) if certs else None
                ),
                "owner": users["it"],
            },
        )
        records.setdefault("suppliers.supplier", supplier)
        if created and criticality != "low":
            Agreement.objects.create(
                supplier=supplier,
                title=f"{name} - master agreement",
                kind="contract",
                starts_on=today - days(400),
                ends_on=today + days(330),
                security_clauses=True,
                confidentiality=True,
                incident_notification=criticality == "critical",
                right_to_audit=criticality == "critical",
            )
            Assessment.objects.create(
                supplier=supplier,
                assessed_on=today - days(120),
                method="certificate" if certs else "questionnaire",
                assessor=users["ciso"],
                score=85 if criticality == "critical" else 70,
                result=(
                    "approved" if criticality == "critical" else "conditions"
                ),
                next_assessment_on=today + days(245),
            )
    records["suppliers.agreement"] = Agreement.objects.first()
    records["suppliers.assessment"] = Assessment.objects.first()


# -- Incidents -----------------------------------------------------------


def seed_incidents(users: dict, records: dict, today: datetime.date) -> None:
    from iso.incidents.models import Evidence, Incident, IncidentUpdate

    now = timezone.now()
    assets = records.get("_assets", {})
    rows = (
        (
            "Phishing e-mail reported by the sales team",
            "phishing",
            "low",
            "closed",
            80,
            False,
            "sales",
        ),
        (
            "Laptop left on a train",
            "loss",
            "medium",
            "resolved",
            45,
            False,
            "dev",
        ),
        (
            "Customer export sent to the wrong recipient",
            "leak",
            "high",
            "contained",
            1,
            True,
            "sales",
        ),
        (
            "Brute force on the VPN",
            "access",
            "medium",
            "triage",
            0,
            False,
            "it",
        ),
        (
            "Unusual traffic from a build server",
            "malware",
            "critical",
            "reported",
            0,
            False,
            "dev",
        ),
    )
    for title, category, severity, status, ago, breach, reporter in rows:
        incident, created = Incident.objects.get_or_create(
            title=title,
            defaults={
                "description": title + ".",
                "category": category,
                "severity": severity,
                "status": status,
                "reported_by": users[reporter],
                "detected_at": now - days(ago),
                "handler": users["ciso"],
                "personal_data_breach": breach,
                "lessons_learned": (
                    "Awareness reminder sent." if status == "closed" else ""
                ),
            },
        )
        if created:
            Incident.objects.filter(pk=incident.pk).update(
                reported_at=now - days(ago)
            )
            if category == "loss" and "Laptop LT-014" in assets:
                incident.assets.set([assets["Laptop LT-014"]])
            IncidentUpdate.objects.create(
                incident=incident,
                kind="action",
                text="Assessed by the security officer.",
                author=users["ciso"],
            )
        records.setdefault("incidents.incident", incident)
    incident = Incident.objects.get(
        title="Customer export sent to the wrong recipient"
    )
    records["incidents.incident"] = incident
    records["incidents.incidentupdate"] = incident.updates.first()
    records["incidents.evidence"] = Evidence.objects.get_or_create(
        incident=incident,
        title="Sent e-mail, with headers",
        defaults={
            "collected_by": users["ciso"],
            "stored_at": "Evidence vault, case folder",
            "custody": "Collected by C. Morel; kept in the vault.",
        },
    )[0]


# -- Vulnerabilities -----------------------------------------------------


def seed_vulnerabilities(
    users: dict, records: dict, today: datetime.date
) -> None:
    from iso.vulnerabilities.models import Vulnerability

    assets = records.get("_assets", {})
    rows = (
        (
            "OpenSSH remote code execution",
            "CVE-2024-6387",
            "advisory",
            "8.1",
            40,
            "fixed",
        ),
        ("Outdated TLS configuration", "", "scanner", "5.3", 100, "open"),
        (
            "SQL injection in the search API",
            "",
            "pentest",
            "9.1",
            3,
            "in_progress",
        ),
        (
            "Jinja2 sandbox escape",
            "CVE-2024-56201",
            "scanner",
            "8.8",
            45,
            "open",
        ),
        ("Verbose error pages", "", "pentest", "3.1", 20, "accepted"),
    )
    for title, identifier, source, cvss, ago, status in rows:
        vulnerability, created = Vulnerability.objects.get_or_create(
            title=title,
            defaults={
                "identifier": identifier,
                "source": source,
                "cvss": Decimal(cvss),
                "discovered_on": today - days(ago),
                "owner": users["it"],
                "status": status,
            },
        )
        if created and "Production cluster" in assets:
            vulnerability.assets.set([assets["Production cluster"]])
        records.setdefault("vulnerabilities.vulnerability", vulnerability)


# -- Changes -------------------------------------------------------------


def seed_changes(users: dict, records: dict, today: datetime.date) -> None:
    from iso.changes.models import ChangeRequest

    now = timezone.now()
    rows = (
        (
            "Upgrade PostgreSQL to 17",
            "infrastructure",
            "medium",
            "closed",
            -30,
        ),
        ("Enable MFA on the VPN", "security", "low", "implemented", -7),
        ("New firewall rules for the API", "network", "medium", "approved", 3),
        (
            "Rotate the TLS certificates",
            "configuration",
            "low",
            "submitted",
            10,
        ),
        (
            "Move the backups to a second region",
            "infrastructure",
            "high",
            "draft",
            25,
        ),
    )
    for title, category, risk, status, offset in rows:
        start = now + days(offset)
        change = ChangeRequest.objects.get_or_create(
            title=title,
            defaults={
                "description": title + ".",
                "category": category,
                "risk": risk,
                "status": status,
                "requested_by": users["dev"],
                "implementer": users["it"],
                "approved_by": (
                    users["ciso"]
                    if status in ("approved", "implemented", "closed")
                    else None
                ),
                "approved_at": (
                    start - days(2)
                    if status in ("approved", "implemented", "closed")
                    else None
                ),
                "planned_start": start,
                "planned_end": start + datetime.timedelta(hours=2),
                "test_plan": "Rehearsed on staging.",
                "rollback_plan": "Restore the previous version.",
            },
        )[0]
        records.setdefault("changes.changerequest", change)


# -- Continuity ----------------------------------------------------------


def seed_continuity(users: dict, records: dict, today: datetime.date) -> None:
    from iso.continuity.models import ContinuityPlan, Exercise, Service

    assets = records.get("_assets", {})
    rows = (
        (
            "SaaS platform",
            "critical",
            4,
            1,
            24,
            ("Production cluster", "Customer database"),
        ),
        ("Customer support", "high", 8, 4, 48, ()),
        ("Payroll", "medium", 72, 24, 240, ("HR files",)),
    )
    for name, criticality, rto, rpo, mtpd, asset_names in rows:
        service, created = Service.objects.get_or_create(
            name=name,
            defaults={
                "owner": users["it"],
                "criticality": criticality,
                "rto_hours": rto,
                "rpo_hours": rpo,
                "mtpd_hours": mtpd,
                "analysed_on": today - days(90),
            },
        )
        if created:
            service.assets.set([assets[n] for n in asset_names if n in assets])
        records.setdefault("continuity.service", service)
    platform = Service.objects.get(name="SaaS platform")
    plan, created = ContinuityPlan.objects.get_or_create(
        title="Platform disaster recovery plan",
        defaults={
            "owner": users["it"],
            "status": "approved",
            "activation": "The CISO or the IT manager, after one hour of "
            "outage.",
            "procedure": "Restore in the second region from the latest "
            "backup; switch DNS.",
            "security_measures": "Same access controls; restored "
            "secrets rotated.",
            "next_test_on": today + days(60),
        },
    )
    if created:
        plan.services.set([platform])
    records["continuity.continuityplan"] = plan
    for title, kind, ago, result, rto, rpo in (
        ("Database restore test", "restore", 100, "passed", "2.5", "0.5"),
        ("Region failover exercise", "failover", 30, "partial", "6.0", "1.0"),
    ):
        exercise = Exercise.objects.get_or_create(
            title=title,
            defaults={
                "kind": kind,
                "plan": plan,
                "service": platform,
                "held_on": today - days(ago),
                "result": result,
                "achieved_rto_hours": Decimal(rto),
                "achieved_rpo_hours": Decimal(rpo),
                "findings": (
                    "DNS change took longer than planned."
                    if result == "partial"
                    else ""
                ),
            },
        )[0]
        records.setdefault("continuity.exercise", exercise)


# -- Audits --------------------------------------------------------------


def seed_audits(users: dict, records: dict, today: datetime.date) -> None:
    from iso.audits.models import Audit, CorrectiveAction, Nonconformity

    auditor = users["auditor"]
    audit, created = Audit.objects.get_or_create(
        title="Internal audit - access control and operations",
        defaults={
            "kind": "internal",
            "scope": "Clauses 9 and 10; Annex A 5.15-5.18, 8.2-8.16.",
            "criteria": "ISO/IEC 27001:2022, internal policies.",
            "lead_auditor": auditor,
            "planned_on": today - days(60),
            "performed_on": today - days(55),
            "status": "reported",
            "conclusion": "The ISMS is effective; two findings.",
        },
    )
    if created and installed("compliance"):
        from iso.compliance.models import Control

        audit.controls.set(
            Control.objects.filter(code__in=("5.15", "5.18", "8.2", "8.15"))
        )
    Audit.objects.get_or_create(
        title="Certification audit - stage 2",
        defaults={
            "kind": "certification",
            "scope": "The whole ISMS.",
            "planned_on": today + days(45),
        },
    )
    records["audits.audit"] = audit
    findings = (
        (
            "Access reviews not documented for the support tool",
            "minor",
            "planned",
            "5.18",
        ),
        (
            "Log retention shorter than the policy",
            "minor",
            "verifying",
            "8.15",
        ),
        (
            "Consider automating leaver account removal",
            "opportunity",
            "open",
            "5.18",
        ),
    )
    for title, grade, status, code in findings:
        control = None
        if installed("compliance"):
            from iso.compliance.models import Control

            control = Control.objects.filter(code=code).first()
        finding = Nonconformity.objects.get_or_create(
            title=title,
            defaults={
                "description": title + ".",
                "source": "audit",
                "audit": audit,
                "grade": grade,
                "control": control,
                "owner": users["it"],
                "status": status,
                "raised_on": today - days(55),
            },
        )[0]
        records.setdefault("audits.nonconformity", finding)
    finding = records["audits.nonconformity"]
    records["audits.correctiveaction"] = (
        CorrectiveAction.objects.get_or_create(
            nonconformity=finding,
            title="Quarterly access review of the support tool",
            defaults={
                "kind": "corrective",
                "owner": users["it"],
                "due_on": today + days(20),
                "status": "in_progress",
            },
        )[0]
    )


# -- People --------------------------------------------------------------


def seed_people(users: dict, records: dict, today: datetime.date) -> None:
    from iso.people.models import Course, PersonnelFile, TrainingRecord

    courses = (
        ("Security awareness", "awareness", True, 12),
        ("GDPR basics", "privacy", True, 24),
        ("Secure coding", "technical", False, 24),
    )
    created_courses = []
    for title, topic, mandatory, validity in courses:
        course = Course.objects.get_or_create(
            title=title,
            defaults={
                "topic": topic,
                "mandatory": mandatory,
                "validity_months": validity,
            },
        )[0]
        created_courses.append(course)
    records["people.course"] = created_courses[0]
    for index, (
        username,
        first_name,
        last,
        job,
        department,
        _group,
    ) in enumerate(STAFF):
        user = users[username]
        status = "active"
        values = {
            "full_name": f"{first_name} {last}",
            "job_title": job,
            "department": department,
            "status": status,
            "starts_on": today - days(400 + 100 * index),
            "screened_on": today - days(420 + 100 * index),
            "terms_signed_on": today - days(410 + 100 * index),
            "nda_signed_on": today - days(410 + 100 * index),
        }
        if username == "sales":
            values["nda_signed_on"] = None  # a step missing
        personnel = PersonnelFile.objects.get_or_create(
            user=user, defaults=values
        )[0]
        records.setdefault("people.personnelfile", personnel)
        for course in created_courses[: 2 if username != "dev" else 3]:
            # The awareness course of the sales account has expired.
            ago = 400 if username == "sales" else 100
            records.setdefault(
                "people.trainingrecord",
                TrainingRecord.objects.get_or_create(
                    course=course,
                    person=user,
                    defaults={"completed_on": today - days(ago)},
                )[0],
            )
    PersonnelFile.objects.get_or_create(
        full_name="Paul Lemaire",
        defaults={
            "job_title": "Support engineer",
            "department": "Support",
            "employment": "contractor",
            "status": "leaving",
            "starts_on": today - days(300),
            "ends_on": today + days(5),
        },
    )


# -- Access reviews ------------------------------------------------------


def seed_access_reviews(
    users: dict, records: dict, today: datetime.date
) -> None:
    from iso.access_reviews.models import AccessReview

    review, created = AccessReview.objects.get_or_create(
        title=f"All accounts - Q{(today.month - 1) // 3 + 1} " f"{today.year}",
        defaults={
            "scope": "all",
            "reviewer": users["ciso"],
            "due_on": today + days(14),
        },
    )
    if created:
        review.collect()
        items = list(review.items.exclude(account=users["ciso"]))
        for item in items[: len(items) // 2]:
            item.decision = "keep"
            item.decided_by = users["ciso"]
            item.decided_at = timezone.now()
            item.save()
    records["access_reviews.accessreview"] = review
    records["access_reviews.accessreviewitem"] = review.items.first()


# -- Custom fields -------------------------------------------------------

#: model, key, definition; what a security officer adds from a list's
#: *Customize fields* (docs/custom-fields.md).
CUSTOM_FIELDS = (
    (
        "assets.asset",
        "warranty_ends",
        {
            "type": "date",
            "labels": {"en": "Warranty ends", "fr": "Fin de garantie"},
            "help_texts": {
                "en": "The last day the vendor repairs it for free.",
                "fr": "Le dernier jour où le fournisseur le répare "
                "gratuitement.",
            },
            "position": 10,
        },
    ),
    (
        "suppliers.supplier",
        "data_location",
        {
            "type": "choice",
            "labels": {
                "en": "Where the data is kept",
                "fr": "Lieu des données",
            },
            "choices": (
                "eu | European Union | fr: Union européenne | #2563eb\n"
                "us | United States | fr: États-Unis | #d97706\n"
                "other | Elsewhere | fr: Ailleurs | #6b7280"
            ),
            "position": 10,
        },
    ),
)


def seed_custom_fields() -> None:
    """Two custom fields and their values: an asset's warranty end and
    where a supplier keeps the data.

    Only on the models whose resource is open to custom fields and
    installed; found again by key, so a second run changes nothing.
    """
    from django.apps import apps
    from django.contrib.contenttypes.models import ContentType

    from generic.customfields.definitions import is_enabled
    from generic.customfields.models import CustomField
    from generic.customfields.values import load, write
    from generic.sites import site

    for label, key, defaults in CUSTOM_FIELDS:
        app_label, model_name = label.split(".")

        if not installed(app_label):
            continue

        model = apps.get_model(app_label, model_name)
        resource = site.get_resource(model)

        if resource is None or not is_enabled(resource):
            continue

        CustomField.objects.get_or_create(
            content_type=ContentType.objects.get_for_model(model),
            key=key,
            defaults=defaults,
        )

        for index, obj in enumerate(model.objects.order_by("pk")):
            if load(resource, obj).get(key) is not None:
                continue

            if key == "warranty_ends":
                if not obj.acquired_on:
                    continue
                value: Any = obj.acquired_on.replace(
                    year=obj.acquired_on.year + 3, day=1
                )
            else:
                value = ("eu", "us", "eu", "other")[index % 4]

            write(resource, obj, {key: value})
