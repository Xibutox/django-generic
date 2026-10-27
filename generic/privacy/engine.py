"""The work behind ``generic.privacy``: finding a person's rows,
anonymizing them, exporting them, and applying the retentions.

Anonymizing a record is more than writing over its fields: the history
keeps every earlier version, whole, and the access log keeps what the
record was called. Both are rewritten here - the fields declared
personal take their anonymized value in every version - so the person
is gone from the history too, while what was done, when and by whom
stays.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
from typing import Any, Iterable, Iterator

from django.db import models, router, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.encoding import force_str

from generic.privacy.declarations import (
    ANONYMOUS,
    ANONYMOUS_DOMAIN,
    PersonalData,
    is_text,
)

logger = logging.getLogger("generic.privacy")

#: What the history says made the change.
SOURCE = "Anonymization"

#: Rows of one model read at once, by key.
CHUNK = 500

#: The most rows of one model an export lists among the references.
REFERENCE_LIMIT = 1000

#: A person's own rows in the framework, deleted with their account:
#: what they set up for themselves, worth nothing to anybody else.
ACCOUNT_DATA = (
    "generic.notification",
    "generic.watch",
    "generic.savedview",
    "generic.userpreferences",
    "generic_tokens.apitoken",
)

#: Never read as a user's: the account's own secret.
SECRET_FIELDS = ("password",)

_registered: dict[Any, PersonalData] = {}


# -- declarations --------------------------------------------------------


def register(model: Any, declaration: PersonalData) -> None:
    """Declare the personal data of a model no resource describes - or
    override what its resource says."""
    if not isinstance(declaration, PersonalData):
        raise TypeError("generic.privacy.register() takes a PersonalData.")

    declaration.check(model, f"generic.privacy.register({model._meta.label})")
    _registered[model] = declaration


def unregister(model: Any) -> None:
    _registered.pop(model, None)


def account_declaration() -> PersonalData:
    """What the user model holds about its person, worked out from it:
    the name signed in with becomes a pseudonym, the names and the
    address are emptied. A project says otherwise by registering its
    own (``register(User, PersonalData(...))``)."""
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    opts = user_model._meta
    fields: dict[str, Any] = {}

    def field(name: str) -> Any:
        try:
            return opts.get_field(name)
        except Exception:
            return None

    login = field(user_model.USERNAME_FIELD)

    if isinstance(login, models.EmailField):
        fields[login.name] = "email"
    elif isinstance(login, (models.CharField, models.TextField)):
        fields[login.name] = "pseudonym"

    email_name = user_model.get_email_field_name()
    email = field(email_name)

    if email is not None and email.name not in fields:
        fields[email.name] = (
            "blank" if email.blank and not email.unique else "email"
        )

    for name in ("first_name", "last_name"):
        found = field(name)

        if found is not None and is_text(found):
            fields[name] = "blank"

    return PersonalData(
        fields=fields,
        email=(email.name,) if email is not None else (),
        action=False,
    )


def declarations(site: Any = None) -> dict[Any, PersonalData]:
    """Every model's declaration: the user model's own, then the
    resources', then what ``register`` was given - each later one
    replacing an earlier one for its model."""
    from django.contrib.auth import get_user_model

    if site is None:
        from generic.sites import site as default_site

        site = default_site

    found: dict[Any, PersonalData] = {get_user_model(): account_declaration()}

    for resource in site.get_resources():
        declaration = getattr(resource, "personal_data", None)

        if declaration is not None:
            found[resource.model] = declaration

    found.update(_registered)

    return found


def declaration_for(model: Any, site: Any = None) -> PersonalData | None:
    return declarations(site).get(model)


# -- a person ------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Subject:
    """The person a request is about: their account, an address, both."""

    user: Any = None
    email: str = ""

    def emails(self) -> list[str]:
        found = [self.email.strip()] if self.email else []

        if self.user is not None:
            from django.contrib.auth import get_user_model

            own = getattr(
                self.user, get_user_model().get_email_field_name(), ""
            )

            if own:
                found.append(str(own).strip())

        return [email for email in dict.fromkeys(found) if email]

    def describe(self) -> dict[str, str]:
        described = {}

        if self.user is not None:
            described["user"] = self.user.get_username()

        if self.email:
            described["email"] = self.email

        return described


def rows_of(
    model: Any,
    declaration: PersonalData,
    subject: Subject,
) -> models.QuerySet:
    """The rows of ``model`` about ``subject`` - trashed ones too, they
    hold the same data."""
    from django.contrib.auth import get_user_model

    manager = model._base_manager
    condition = Q()
    found = False

    if subject.user is not None:
        if model is get_user_model():
            condition |= Q(pk=subject.user.pk)
            found = True
        elif declaration.subject:
            condition |= Q(**{declaration.subject: subject.user})
            found = True

    for name in declaration.email:
        for email in subject.emails():
            condition |= Q(**{f"{name}__iexact": email})
            found = True

    if not found:
        return manager.none()

    return manager.filter(condition).distinct()


def find(subject: Subject, site: Any = None) -> Iterator[tuple[Any, Any]]:
    """Each ``(declaration, row)`` about ``subject``, model by model."""
    for model, declaration in declarations(site).items():
        for obj in rows_of(model, declaration, subject).order_by("pk"):
            yield declaration, obj


# -- anonymizing ---------------------------------------------------------


def anonymous_value(obj: Any, name: str, strategy: Any) -> Any:
    """What field ``name`` of ``obj`` becomes."""
    field = obj._meta.get_field(name)

    if callable(strategy):
        return strategy(obj, name)

    if strategy == "null":
        return None

    if strategy == "blank":
        return "" if is_text(field) else None

    if strategy == "pseudonym":
        value = f"{ANONYMOUS}-{obj.pk}"
    else:
        value = f"{ANONYMOUS}-{obj.pk}@{ANONYMOUS_DOMAIN}"

    limit = getattr(field, "max_length", None)

    return value[:limit] if limit else value


def replacements(obj: Any, declaration: PersonalData) -> dict[str, Any]:
    """Every declared field of ``obj``, by name, as anonymized."""
    return {
        name: anonymous_value(obj, name, strategy)
        for name, strategy in declaration.fields.items()
    }


def _current(obj: Any, name: str) -> Any:
    return getattr(obj, obj._meta.get_field(name).attname)


def _is_account(obj: Any) -> bool:
    from django.contrib.auth import get_user_model

    return isinstance(obj, get_user_model())


def _account_open(obj: Any) -> bool:
    return bool(getattr(obj, "is_active", False) or obj.has_usable_password())


def needs_anonymizing(obj: Any, declaration: PersonalData) -> bool:
    """Whether anonymizing ``obj`` would change anything."""
    if declaration.marker and getattr(obj, declaration.marker) is not None:
        return False

    changed = any(
        _current(obj, name) != value
        for name, value in replacements(obj, declaration).items()
    )

    return changed or (_is_account(obj) and _account_open(obj))


def label_of(obj: Any, site: Any = None) -> str:
    """What the screens call ``obj`` - its resource's label."""
    if site is None:
        from generic.sites import site as default_site

        site = default_site

    resource = site.get_resource(type(obj))

    if resource is not None:
        return force_str(resource.get_object_label(obj))

    return force_str(obj)


def anonymize(
    obj: Any,
    declaration: PersonalData | None = None,
    user: Any = None,
    site: Any = None,
) -> bool:
    """Anonymize one record: its declared fields, the same fields in
    every version its history kept, what the access log calls it - and,
    for an account, the account itself (no password, inactive) and what
    the framework keeps of its person (``forget_account``).

    ``user`` is who does it, for the history. Returns whether anything
    changed: a record already anonymized is left as it is.
    """
    if declaration is None:
        declaration = declaration_for(type(obj), site)

    if declaration is None:
        raise ValueError(
            f"{obj._meta.label} declares no personal data "
            f"(generic.privacy.PersonalData)."
        )

    if not needs_anonymizing(obj, declaration):
        return False

    from generic.history import acting_as

    values = replacements(obj, declaration)
    files = _files_to_delete(obj, declaration, values)
    changed = []

    for name, value in values.items():
        if _current(obj, name) != value:
            setattr(obj, obj._meta.get_field(name).attname, value)
            changed.append(name)

    if declaration.marker:
        setattr(obj, declaration.marker, timezone.now())
        changed.append(declaration.marker)

    account = _is_account(obj)

    if account:
        obj.set_unusable_password()
        changed.append("password")

        if hasattr(obj, "is_active"):
            obj.is_active = False
            changed.append("is_active")

    using = router.db_for_write(type(obj), instance=obj)

    with transaction.atomic(using=using):
        with acting_as(user, source=SOURCE):
            obj.save(update_fields=list(dict.fromkeys(changed)))

        scrub(type(obj), obj.pk, values, label_of(obj, site))

        if account:
            forget_account(obj)

        transaction.on_commit(lambda: _delete_files(files), using=using)

    logger.info("Anonymized %s %s.", obj._meta.label_lower, obj.pk)

    return True


def delete(
    obj: Any,
    declaration: PersonalData,
    user: Any = None,
) -> bool:
    """Delete one record, its declared files with it, and leave its
    history saying what was done - not what it held. Returns False
    when another record protects it."""
    from django.db.models import ProtectedError, RestrictedError

    from generic.history import acting_as

    model = type(obj)
    pk = obj.pk
    values = replacements(obj, declaration)
    files = _files_to_delete(obj, declaration, values)
    using = router.db_for_write(model, instance=obj)

    try:
        with transaction.atomic(using=using):
            with acting_as(user, source=SOURCE):
                obj.delete()

            scrub(model, pk, values, f"{ANONYMOUS}-{pk}")
            transaction.on_commit(lambda: _delete_files(files), using=using)
    except (ProtectedError, RestrictedError):
        logger.warning(
            "Kept %s %s past its retention: other records depend on it.",
            model._meta.label_lower,
            pk,
        )

        return False

    logger.info("Deleted %s %s (retention).", model._meta.label_lower, pk)

    return True


def _files_to_delete(
    obj: Any,
    declaration: PersonalData,
    values: dict[str, Any],
) -> list[tuple[Any, str]]:
    """The stored files a blanked file field leaves behind."""
    files = []

    for name in values:
        field = obj._meta.get_field(name)

        if isinstance(field, models.FileField) and values[name] in ("", None):
            stored = getattr(obj, field.attname)

            if stored and stored.name:
                files.append((stored.storage, stored.name))

    return files


def _delete_files(files: Iterable[tuple[Any, str]]) -> None:
    for storage, name in files:
        try:
            storage.delete(name)
        except Exception:  # pragma: no cover - a storage's own trouble
            logger.exception("Could not delete the file %s.", name)


def scrub(model: Any, pk: Any, values: dict[str, Any], label: str) -> int:
    """Write ``values`` over the same fields in every version the
    history kept of one record, and ``label`` over what the history and
    the access log call it. Returns how many versions changed."""
    from django.contrib.contenttypes.models import ContentType

    from generic.access.models import AccessEntry
    from generic.history.models import HistoryEntry
    from generic.history.recording import LABEL_LENGTH, json_safe

    label = label[:LABEL_LENGTH]
    safe = {name: json_safe(value) for name, value in values.items()}
    entries = HistoryEntry.objects.filter(
        content_type=ContentType.objects.get_for_model(model),
        object_id=force_str(pk),
    ).only("pk", "values", "label")
    rewritten = 0

    for entry in entries:
        kept = dict(entry.values or {})
        kept.update({key: value for key, value in safe.items() if key in kept})

        if kept != (entry.values or {}) or entry.label != label:
            HistoryEntry.objects.filter(pk=entry.pk).update(
                values=kept, label=label
            )
            rewritten += 1

    AccessEntry.objects.filter(
        record_key=f"{model._meta.label_lower}:{pk}"
    ).exclude(label=label).update(label=label[:200])

    return rewritten


def forget_account(user: Any) -> None:
    """What the framework keeps of an account's person, once it is
    anonymized: their name rewritten where it was copied (history,
    access log, security log), the addresses and browsers they came
    from dropped, what they set up for themselves deleted."""
    from django.apps import apps

    from generic.access.models import AccessEntry
    from generic.audit.models import SecurityEvent
    from generic.grants.models import AccessRequest
    from generic.history.models import HistoryEntry

    name = force_str(user)[:200]

    HistoryEntry.objects.filter(user=user).update(user_label=name)
    AccessEntry.objects.filter(user=user).update(user_label=name, address=None)
    SecurityEvent.objects.filter(user=user).update(
        username=user.get_username()[:150], address=None, user_agent=""
    )
    AccessRequest.objects.filter(user=user).update(message="", page="")

    for label in ACCOUNT_DATA:
        try:
            model = apps.get_model(label)
        except LookupError:
            continue

        model._base_manager.filter(user=user).delete()


def anonymize_subject(
    subject: Subject,
    user: Any = None,
    site: Any = None,
    dry_run: bool = False,
) -> list[tuple[Any, Any]]:
    """Anonymize every row about ``subject``, in one transaction.
    Returns the ``(declaration, row)`` changed - or, with ``dry_run``,
    that would be."""
    rows = [
        (declaration, obj)
        for declaration, obj in find(subject, site)
        if needs_anonymizing(obj, declaration)
    ]

    if dry_run:
        return rows

    with transaction.atomic():
        # The account last: the rows found through it are found first.
        for declaration, obj in sorted(rows, key=lambda r: _is_account(r[1])):
            anonymize(obj, declaration, user=user, site=site)

    return rows


# -- exporting -----------------------------------------------------------


def export(subject: Subject, site: Any = None) -> dict[str, Any]:
    """Everything kept about ``subject``, as JSON-safe data: the rows
    declared about them with their personal fields (the right of access
    and to portability, GDPR Art. 15 and 20), then every row anywhere
    pointing at their account - where else they appear."""
    from django.contrib.auth import get_user_model

    from generic.history.recording import json_safe

    user_model = get_user_model()
    declared = declarations(site)
    records = []

    for declaration, obj in find(subject, site):
        names = list(dict.fromkeys([*declaration.fields, *declaration.export]))

        if isinstance(obj, user_model):
            names = [
                field.name
                for field in obj._meta.concrete_fields
                if field.name not in SECRET_FIELDS
            ]

        records.append(
            {
                "model": obj._meta.label_lower,
                "name": force_str(obj._meta.verbose_name),
                "pk": json_safe(obj.pk),
                "label": label_of(obj, site),
                "fields": {
                    name: json_safe(
                        obj._meta.get_field(name).value_from_object(obj)
                    )
                    for name in names
                },
            }
        )

    return {
        "subject": subject.describe(),
        "exported_at": timezone.now().isoformat(),
        "records": records,
        "references": (
            references(subject.user, skip=declared)
            if subject.user is not None
            else []
        ),
    }


def references(user: Any, skip: Iterable[Any] = ()) -> list[dict[str, Any]]:
    """Every row pointing at ``user``'s account, model by model and
    field by field: who they are in the rest of the database."""
    from django.contrib.auth import get_user_model

    from generic.history.recording import json_safe

    skipped = set(skip)
    found = []

    for relation in get_user_model()._meta.related_objects:
        model = relation.related_model

        if model in skipped or not relation.field.concrete:
            continue

        rows = model._base_manager.filter(**{relation.field.name: user})
        count = rows.count()

        if not count:
            continue

        found.append(
            {
                "model": model._meta.label_lower,
                "name": force_str(model._meta.verbose_name_plural),
                "field": relation.field.name,
                "count": count,
                "rows": [
                    {"pk": json_safe(obj.pk), "label": force_str(obj)}
                    for obj in rows.order_by("pk")[:REFERENCE_LIMIT]
                ],
            }
        )

    return found


# -- retention -----------------------------------------------------------


def expired(model: Any, declaration: PersonalData) -> models.QuerySet:
    """The rows of ``model`` past their retention."""
    retention = declaration.retention

    if retention is None:
        return model._base_manager.none()

    field: Any = model

    for part in retention.after.split("__"):
        field = field._meta.get_field(part)

        if field.is_relation:
            field = field.related_model

    delta = datetime.timedelta(days=retention.days)
    cutoff: Any = (
        timezone.now() - delta
        if isinstance(field, models.DateTimeField)
        else timezone.localdate() - delta
    )
    rows = model._base_manager.filter(
        **{f"{retention.after}__lt": cutoff}, **dict(retention.filter)
    )

    if declaration.marker and retention.action == "anonymize":
        rows = rows.filter(**{f"{declaration.marker}__isnull": True})

    return rows.order_by("pk")


def apply_retention(
    site: Any = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Anonymize or delete, model by model, the rows past their
    retention. Returns how many, by model label (``app.model``) -
    with ``dry_run``, how many would be."""
    done: dict[str, int] = {}

    for model, declaration in declarations(site).items():
        retention = declaration.retention

        if retention is None:
            continue

        keys = list(expired(model, declaration).values_list("pk", flat=True))
        count = 0

        for start in range(0, len(keys), CHUNK):
            chunk = model._base_manager.filter(
                pk__in=keys[start : start + CHUNK]
            ).order_by("pk")

            for obj in chunk:
                if retention.action == "delete":
                    count += 1 if dry_run else delete(obj, declaration)
                elif needs_anonymizing(obj, declaration):
                    if not dry_run:
                        anonymize(obj, declaration, site=site)

                    count += 1

        if count:
            done[model._meta.label_lower] = count

    return done


__all__ = [
    "ACCOUNT_DATA",
    "SOURCE",
    "Subject",
    "account_declaration",
    "anonymize",
    "anonymize_subject",
    "apply_retention",
    "declaration_for",
    "declarations",
    "delete",
    "expired",
    "export",
    "find",
    "forget_account",
    "needs_anonymizing",
    "references",
    "register",
    "replacements",
    "rows_of",
    "scrub",
    "unregister",
]
