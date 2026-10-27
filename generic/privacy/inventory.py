"""Where personal data lives: every model, read for it.

The findings, model by model:

* ``declared`` - a field a ``PersonalData`` names, and what it becomes;
* ``suspected`` - a field nothing declares that looks personal by its
  type (an e-mail, an IP address) or its name (``phone``,
  ``birth_date``, ``last_name``...): to declare, or to say why not;
* ``account`` - a relation to the user model: rows by or about a
  person, which an export lists and which an anonymized account leaves
  pointing at nobody in particular;
* ``framework`` - the framework's own stores, each with the setting
  that keeps it in check;
* ``retention`` - how long a declaration keeps its rows.

The register of processing (GDPR Art. 30) starts from this list; it is
not the register.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from django.apps import apps
from django.db import models
from django.utils.encoding import force_str

from generic.privacy.engine import declarations

#: Names that say "a person" when a field nothing declares bears one.
SUSPECT_NAMES = re.compile(
    r"(^|_)(e?mail|phone|mobile|fax|first_?name|last_?name|full_?name|"
    r"surname|maiden|birth(day|_?date|_?place)?|address|street|postcode|"
    r"post_code|zip(_?code)?|ssn|social_security|national_id|iban|"
    r"passport|ip|ip_address|gender|nationality|salary|health)($|_)",
    re.IGNORECASE,
)

#: Apps whose models hold nothing a project answers for.
SKIPPED_APPS = ("contenttypes", "sessions", "admin", "migrations")

#: The framework's own stores of personal data, and what keeps them.
FRAMEWORK = {
    "generic.historyentry": (
        "HISTORY_RETENTION_DAYS; the declared fields are rewritten in "
        "every version when a record is anonymized, the name when an "
        "account is."
    ),
    "generic.accessentry": (
        "ACCESS_LOG_RETENTION_DAYS; name and address dropped when an "
        "account is anonymized."
    ),
    "generic.securityevent": (
        "SECURITY_LOG_RETENTION_DAYS; address and browser dropped when "
        "an account is anonymized."
    ),
    "generic.notification": (
        "EVENTS_RETENTION_DAYS; deleted with an anonymized account."
    ),
    "generic.accessrequest": "Message emptied when an account is anonymized.",
    "generic.userpreferences": "Deleted with an anonymized account.",
    "generic.savedview": "Deleted with an anonymized account.",
    "generic.watch": "Deleted with an anonymized account.",
    "generic_tokens.apitoken": "Deleted with an anonymized account.",
}


@dataclasses.dataclass(frozen=True)
class Finding:
    model: str
    field: str
    kind: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)


def _strategy(strategy: Any) -> str:
    if callable(strategy):
        return getattr(strategy, "__name__", "callable")

    return str(strategy)


def _suspect(field: Any) -> bool:
    return isinstance(
        field, (models.EmailField, models.GenericIPAddressField)
    ) or bool(SUSPECT_NAMES.search(field.name))


def inventory(site: Any = None) -> list[Finding]:
    """Every finding, model by model, in ``INSTALLED_APPS`` order."""
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    declared = declarations(site)
    found: list[Finding] = []

    for model in apps.get_models():
        opts = model._meta

        if opts.app_label in SKIPPED_APPS:
            continue

        label = opts.label_lower
        declaration = declared.get(model)
        names = set(declaration.fields) if declaration is not None else set()

        if label in FRAMEWORK:
            found.append(Finding(label, "", "framework", FRAMEWORK[label]))

        if declaration is not None:
            for name, strategy in declaration.fields.items():
                found.append(
                    Finding(label, name, "declared", _strategy(strategy))
                )

            if declaration.retention is not None:
                retention = declaration.retention
                found.append(
                    Finding(
                        label,
                        retention.after,
                        "retention",
                        f"{retention.action} after {retention.days} days",
                    )
                )

        if label in FRAMEWORK:
            continue

        for field in opts.concrete_fields:
            if field.name in names or field.name in ("password",):
                continue

            if field.is_relation and field.related_model is user_model:
                found.append(
                    Finding(
                        label,
                        field.name,
                        "account",
                        "points at a person's account",
                    )
                )
            elif not field.is_relation and _suspect(field):
                found.append(
                    Finding(
                        label,
                        field.name,
                        "suspected",
                        force_str(field.verbose_name),
                    )
                )

    return found


__all__ = ["FRAMEWORK", "Finding", "SUSPECT_NAMES", "inventory"]
