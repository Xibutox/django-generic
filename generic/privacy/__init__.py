"""Personal data (GDPR): declared once, then found, exported, anonymized
and kept only as long as declared.

A resource says what its model holds about people::

    from generic.privacy import PersonalData, Retention

    @register(Agent)
    class AgentResource(ModelResource):
        personal_data = PersonalData(
            fields={"name": "pseudonym", "email": "email", "phone": "blank"},
            email=("email",),            # how to find a person's rows
            subject="account",           # ... or the user they are about
            retention=Retention(days=3 * 365, after="left_on"),
        )

``generic.privacy.register(Model, PersonalData(...))`` does the same for
a model no resource describes. The user model needs nothing: its
login becomes a pseudonym, its names and address are emptied.

Then, from ``manage.py personal_data``:

* ``inventory`` - where personal data lives: the fields declared, the
  fields that look personal and are not, the rows pointing at an
  account, the framework's own stores;
* ``export --user alice`` / ``--email a@example.com`` - everything kept
  about one person, as JSON (right of access and to portability, GDPR
  Art. 15 and 20);
* ``anonymize --user alice`` - every row about them anonymized, their
  account closed, their name and addresses gone from the history, the
  access log and the security log (right to erasure, Art. 17);
* ``retention`` - the rows past their declared retention anonymized or
  deleted (storage limitation, Art. 5(1)(e)). ``apply_retention``, and
  the managed task ``generic.apply_retention``, run it every night with
  the other retentions.

The list of a resource declaring personal data offers the bulk action
*Anonymize* to whoever may delete its records. See docs/privacy.md.
"""

from __future__ import annotations

from typing import Any

from generic.privacy.declarations import (
    ACTIONS,
    ANONYMOUS,
    ANONYMOUS_DOMAIN,
    STRATEGIES,
    PersonalData,
    Retention,
)
from generic.privacy.engine import (
    SOURCE,
    Subject,
    account_declaration,
    anonymize,
    anonymize_subject,
    apply_retention,
    declaration_for,
    declarations,
    delete,
    export,
    find,
    forget_account,
    references,
    register,
    replacements,
    unregister,
)

#: The bulk action a declaring resource's list offers.
ACTION_NAME = "anonymize_personal_data"


def anonymize_action(resource: Any) -> Any:
    """The bulk action: the selection anonymized, in one transaction."""

    def anonymize_personal_data(request: Any, queryset: Any) -> dict:
        from django.db import transaction
        from django.utils.translation import ngettext

        count = 0

        with transaction.atomic():
            for obj in queryset:
                count += anonymize(
                    obj,
                    resource.personal_data,
                    user=request.user,
                    site=resource.site,
                )

        return {
            "level": "success",
            "message": ngettext(
                "%(count)s record anonymized.",
                "%(count)s records anonymized.",
                count,
            )
            % {"count": count},
        }

    return anonymize_personal_data


__all__ = [
    "ACTIONS",
    "ACTION_NAME",
    "ANONYMOUS",
    "ANONYMOUS_DOMAIN",
    "PersonalData",
    "Retention",
    "SOURCE",
    "STRATEGIES",
    "Subject",
    "account_declaration",
    "anonymize",
    "anonymize_action",
    "anonymize_subject",
    "apply_retention",
    "declaration_for",
    "declarations",
    "delete",
    "export",
    "find",
    "forget_account",
    "references",
    "register",
    "replacements",
    "unregister",
]
