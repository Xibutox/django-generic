# ISO 27001 apps

Twelve Django apps, built on django-generic, that hold the records an
ISO/IEC 27001:2022 information security management system (ISMS) needs
and an auditor asks to see: the asset inventory, the risk register,
the Statement of Applicability, incidents, audits, training, access
reviews and the rest.

Each app is independent: a project installs the ones it needs. They
are not a whole project - they plug into any django-generic project,
and the example project of this repository installs all twelve so they
can be tried.

```bash
python manage.py migrate
python manage.py seed_iso        # demo data; accounts ciso, it, auditor, dev, sales (password demo)
python manage.py seed_iso --language fr   # the same, the policies' documents in French
python manage.py runserver
```

## The apps

| App | What it holds | ISO 27001 clauses | Annex A controls |
| --- | --- | --- | --- |
| `iso.isms` | Scope, context issues, interested parties, objectives and their measurements, policies and who acknowledged them, contacts with authorities, management reviews and their actions | 4.1, 4.2, 4.3, 5.2, 6.2, 7.3, 9.1, 9.3 | 5.1, 5.4, 5.5, 5.6, 5.10 |
| `iso.assets` | Asset inventory (owner, classification, C/I/A ratings, personal data), assignments to people and their return, maintenance, secure disposal | 8.1 | 5.9, 5.10, 5.11, 5.12, 5.13, 7.9, 7.10, 7.13, 7.14, 8.10 |
| `iso.compliance` | The 93 Annex A controls, preloaded: applicability, justification, status, implementation, evidence - the Statement of Applicability; legal, regulatory and contractual obligations mapped to controls | 6.1.3 d), 7.5 | 5.31, 5.32, 5.34, 5.36 |
| `iso.risks` | Risk register: threat, vulnerability, likelihood x impact, level, treatment, residual risk, acceptance by the owner; treatment plan | 6.1.2, 6.1.3, 8.2, 8.3 | (every control is linked to the risks it treats) |
| `iso.suppliers` | Suppliers, the data they reach, cloud services, agreements and their security clauses, assessments | 8.1 | 5.19, 5.20, 5.21, 5.22, 5.23 |
| `iso.incidents` | Events and incidents, timeline of updates, evidence with SHA-256 and chain of custody, GDPR 72-hour breach deadline, lessons learned | 10.2 | 5.24, 5.25, 5.26, 5.27, 5.28, 6.8 |
| `iso.vulnerabilities` | Technical vulnerabilities, CVSS, severity, fix-by date from the severity (configurable), overdue view | 8.1 | 8.8 |
| `iso.changes` | Change requests: risk, test and rollback plans, approval by someone other than the requester, implementation, review; change calendar | 6.3, 8.1 | 5.3, 8.32 |
| `iso.continuity` | Business impact analysis (RTO, RPO, MTPD), continuity plans, exercises and backup restore tests against the targets | 8.1 | 5.29, 5.30, 8.13, 8.14 |
| `iso.audits` | Audit programme, nonconformities, corrective actions verified by someone other than their owner | 9.2, 10.1, 10.2 | 5.35, 5.36 |
| `iso.people` | Courses, training records and their expiry, personnel files (screening, signatures, NDA, departure steps) | 7.2, 7.3 | 6.1, 6.2, 6.3, 6.4, 6.5, 6.6 |
| `iso.access_reviews` | Access review campaigns: accounts collected as they are, decided one by one, revoked accounts deactivated | 9.1 | 5.15, 5.18, 8.2 |

`iso` itself holds what they share - navigation groups, colours, the
severity and classification scales, numbering - the French
translations, and the `seed_iso` command.

Every list, form, filter, export, chart, board and calendar is
django-generic's: each app is a `models.py` and a `resources.py`. The
framework adds what every app gets for free and an auditor also asks
for: history of every change (who, when, before, after), model
permissions enforced by the API, exports, access logs on evidence.

## Installing them in a project

Copy the `iso/` folder next to your project's apps (it is not part of
the `django-generic` wheel), then add `iso` and the apps you want:

```python
INSTALLED_APPS = [
    # ... django-generic and your apps ...
    "iso",              # shared helpers, translations, seed_iso
    "iso.isms",
    "iso.assets",       # needed by risks, incidents, vulnerabilities,
                        # changes, continuity
    "iso.compliance",   # needed by risks and audits
    "iso.risks",
    "iso.suppliers",
    "iso.incidents",
    "iso.vulnerabilities",
    "iso.changes",
    "iso.continuity",
    "iso.audits",
    "iso.people",
    "iso.access_reviews",
]
```

```bash
python manage.py migrate      # loads the 93 Annex A controls too
```

Dependencies between apps are the foreign keys: risks point at assets
and controls, audits at controls, incidents, vulnerabilities, changes
and continuity at assets. `isms`, `suppliers`, `people` and
`access_reviews` stand alone. `iso.people` shows a person's assets when
`iso.assets` is installed, and the controls show their risks when
`iso.risks` is.

Permissions are Django's model permissions; two more are declared:

- `risks.accept_risk` - accept a residual risk (the risk owner's);
- `changes.approve_changerequest` - approve or reject a change.

`seed_iso` creates two groups as a starting point: *Security officers*
(every permission of the installed ISO apps) and *Auditors* (read
everything, record audits and findings).

### Settings

```python
# One OpenAPI name per choice set, so `check --deploy` stays quiet.
from iso.openapi import ENUM_NAME_OVERRIDES as ISO_ENUMS

SPECTACULAR_SETTINGS = {
    # ...
    "ENUM_NAME_OVERRIDES": {**ISO_ENUMS},
}


# Days to fix a vulnerability, by severity (default 7, 30, 90, 180).
ISO_VULNERABILITY_DAYS = {"critical": 3, "high": 15}
```

## The rules the apps enforce

What an auditor checks was kept, not only written down:

- **Risk score** = likelihood x impact on a 5 x 5 matrix; the level
  (low 1-4, medium 5-9, high 10-16, critical 17-25) is stored, so lists
  filter and sort on it. The residual risk is rated the same way;
  accepting it needs `risks.accept_risk` and a residual rating unless
  the treatment is *accept*, and keeps who accepted it and when.
- **Segregation of duties** (A.5.3): nobody approves their own change
  request, nobody verifies their own corrective action, nobody decides
  on their own account in an access review.
- **Access reviews**: *Collect the accounts* snapshots each account in
  scope (groups, permission count, last sign-in); *Apply the decisions*
  deactivates the accounts decided as revoked - never the reviewer's
  own, and a superuser only by a superuser.
- **Breach deadline**: a personal data breach is due to the authority
  72 hours after its detection; the incident list shows the deadline
  and whether it was missed.
- **Evidence integrity**: an incident's evidence keeps the SHA-256 of
  its file, computed on upload, and every opening is logged.
- **Vulnerability deadlines**: the fix-by date follows the severity,
  itself worked out from the CVSS score; the *Overdue* preset lists what
  missed it.
- **Policies**: each user acknowledges the current version with one
  button; a new version needs a new acknowledgement; the list shows
  the coverage.
- **Training**: a record expires after the course's validity; personnel
  files list the joining and leaving steps still missing.
- **Corrective actions**: a nonconformity closes when all its actions
  are verified effective.
- **Continuity**: an exercise compares the recovery time and data loss
  achieved with the service's RTO and RPO.

## Custom fields

The main record of each app is open to
[custom fields](../docs/custom-fields.md) (`custom_fields = True`):
policies, assets, controls, risks, suppliers, incidents,
vulnerabilities, change requests, services, nonconformities and
personnel files. Whoever holds `<app>.customize_<model>` - the
*Security officers* do - adds fields from the list's *Customize
fields*, without a migration: a ticket number on a change request, an
insurance value on an asset, a contract owner on a supplier. Their
values are versioned with the record, so the audit trail covers them
too. `seed_iso` adds two: *Warranty ends* on the assets and *Where the
data is kept* (a choice) on the suppliers. A project turns them off
with `CUSTOM_FIELDS = False`.

## Policies and procedures

ISO 27001 asks for documented policies and procedures, and the ones
that touch the software must say what the software does.
[`documents/`](documents/README.md) holds six, in English and French,
written from the code of django-generic and of these apps - templates
whose bracketed parts the organisation fills in:

| Code | Document | Annex A |
| --- | --- | --- |
| POL-03 | Access control policy and user access management procedure: accounts, groups, permissions, the rule that nobody grants what they do not hold, tokens, sign-in, joiners, movers, leavers, access reviews | 5.15 - 5.18, 8.2, 8.3, 8.5 |
| POL-04 | Backup and restore policy | 8.13, 8.14 |
| POL-06 | Logging and monitoring policy: history, security events, access log, retention, and what a superuser can still delete | 8.15 - 8.17, 8.10 |
| POL-07 | Change management procedure | 8.32, 5.3 |
| POL-08 | Incident management procedure, with what the logs tell an investigator | 5.24 - 5.28, 6.8 |
| POL-09 | Technical vulnerability management procedure | 8.8 |

`seed_iso` attaches each to its policy in *Policies* (in English;
`seed_iso --language fr` in French), so the demo shows a policy with
its document, ready to acknowledge and review.

## What the apps do not do

They hold records and enforce the rules above; the ISMS stays the
organisation's. Writing the policies, deciding the risk criteria,
running the audits, training people and securing premises are not
software. The analysis of every clause and control - what
django-generic itself covers, what these apps cover, what is left to
the organisation - is in the project's ISO 27001 and 27002 review
documents.

## Tests

`tests/test_iso.py` checks the rules above; `tests/test_pages.py` opens
every page of every app with the demo data.
