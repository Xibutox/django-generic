"""The 93 controls of ISO/IEC 27001:2022 Annex A (ISO/IEC 27002:2022).

Their short titles only - the standard's text is the standard's. Marked
for translation, so the catalogue is loaded in the project's language.
"""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

ORGANISATIONAL = "organisational"
PEOPLE = "people"
PHYSICAL = "physical"
TECHNOLOGICAL = "technological"

ANNEX_A = [
    ("5.1", _("Policies for information security")),
    ("5.2", _("Information security roles and responsibilities")),
    ("5.3", _("Segregation of duties")),
    ("5.4", _("Management responsibilities")),
    ("5.5", _("Contact with authorities")),
    ("5.6", _("Contact with special interest groups")),
    ("5.7", _("Threat intelligence")),
    ("5.8", _("Information security in project management")),
    ("5.9", _("Inventory of information and other associated assets")),
    ("5.10", _("Acceptable use of information and other associated assets")),
    ("5.11", _("Return of assets")),
    ("5.12", _("Classification of information")),
    ("5.13", _("Labelling of information")),
    ("5.14", _("Information transfer")),
    ("5.15", _("Access control")),
    ("5.16", _("Identity management")),
    ("5.17", _("Authentication information")),
    ("5.18", _("Access rights")),
    ("5.19", _("Information security in supplier relationships")),
    (
        "5.20",
        _("Addressing information security within supplier agreements"),
    ),
    ("5.21", _("Managing information security in the ICT supply chain")),
    (
        "5.22",
        _("Monitoring, review and change management of supplier services"),
    ),
    ("5.23", _("Information security for use of cloud services")),
    (
        "5.24",
        _(
            "Information security incident management planning and "
            "preparation"
        ),
    ),
    ("5.25", _("Assessment and decision on information security events")),
    ("5.26", _("Response to information security incidents")),
    ("5.27", _("Learning from information security incidents")),
    ("5.28", _("Collection of evidence")),
    ("5.29", _("Information security during disruption")),
    ("5.30", _("ICT readiness for business continuity")),
    (
        "5.31",
        _("Legal, statutory, regulatory and contractual requirements"),
    ),
    ("5.32", _("Intellectual property rights")),
    ("5.33", _("Protection of records")),
    ("5.34", _("Privacy and protection of PII")),
    ("5.35", _("Independent review of information security")),
    (
        "5.36",
        _(
            "Compliance with policies, rules and standards for information "
            "security"
        ),
    ),
    ("5.37", _("Documented operating procedures")),
    ("6.1", _("Screening")),
    ("6.2", _("Terms and conditions of employment")),
    ("6.3", _("Information security awareness, education and training")),
    ("6.4", _("Disciplinary process")),
    (
        "6.5",
        _("Responsibilities after termination or change of employment"),
    ),
    ("6.6", _("Confidentiality or non-disclosure agreements")),
    ("6.7", _("Remote working")),
    ("6.8", _("Information security event reporting")),
    ("7.1", _("Physical security perimeters")),
    ("7.2", _("Physical entry")),
    ("7.3", _("Securing offices, rooms and facilities")),
    ("7.4", _("Physical security monitoring")),
    ("7.5", _("Protecting against physical and environmental threats")),
    ("7.6", _("Working in secure areas")),
    ("7.7", _("Clear desk and clear screen")),
    ("7.8", _("Equipment siting and protection")),
    ("7.9", _("Security of assets off-premises")),
    ("7.10", _("Storage media")),
    ("7.11", _("Supporting utilities")),
    ("7.12", _("Cabling security")),
    ("7.13", _("Equipment maintenance")),
    ("7.14", _("Secure disposal or re-use of equipment")),
    ("8.1", _("User endpoint devices")),
    ("8.2", _("Privileged access rights")),
    ("8.3", _("Information access restriction")),
    ("8.4", _("Access to source code")),
    ("8.5", _("Secure authentication")),
    ("8.6", _("Capacity management")),
    ("8.7", _("Protection against malware")),
    ("8.8", _("Management of technical vulnerabilities")),
    ("8.9", _("Configuration management")),
    ("8.10", _("Information deletion")),
    ("8.11", _("Data masking")),
    ("8.12", _("Data leakage prevention")),
    ("8.13", _("Information backup")),
    ("8.14", _("Redundancy of information processing facilities")),
    ("8.15", _("Logging")),
    ("8.16", _("Monitoring activities")),
    ("8.17", _("Clock synchronization")),
    ("8.18", _("Use of privileged utility programs")),
    ("8.19", _("Installation of software on operational systems")),
    ("8.20", _("Networks security")),
    ("8.21", _("Security of network services")),
    ("8.22", _("Segregation of networks")),
    ("8.23", _("Web filtering")),
    ("8.24", _("Use of cryptography")),
    ("8.25", _("Secure development life cycle")),
    ("8.26", _("Application security requirements")),
    ("8.27", _("Secure system architecture and engineering principles")),
    ("8.28", _("Secure coding")),
    ("8.29", _("Security testing in development and acceptance")),
    ("8.30", _("Outsourced development")),
    (
        "8.31",
        _("Separation of development, test and production environments"),
    ),
    ("8.32", _("Change management")),
    ("8.33", _("Test information")),
    ("8.34", _("Protection of information systems during audit testing")),
]

THEMES = {
    "5": ORGANISATIONAL,
    "6": PEOPLE,
    "7": PHYSICAL,
    "8": TECHNOLOGICAL,
}


def theme_of(code: str) -> str:
    return THEMES[code.split(".")[0]]


def sort_key(code: str) -> int:
    """5.10 after 5.9: the clause times a hundred plus the number."""
    clause, item = code.split(".")
    return int(clause) * 100 + int(item)


def load(control_model, language: str | None = None) -> int:
    """Create the controls missing from ``control_model``; never change
    one already there - its title may have been edited. Returns how many
    were created."""
    from django.conf import settings
    from django.utils import translation

    created = 0
    with translation.override(language or settings.LANGUAGE_CODE):
        for code, title in ANNEX_A:
            _control, made = control_model.objects.get_or_create(
                code=code,
                defaults={
                    "title": str(title),
                    "theme": theme_of(code),
                    "position": sort_key(code),
                },
            )
            created += made
    return created
