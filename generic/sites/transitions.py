"""State machines: a model's ``@transition`` methods as buttons.

The model declares its states and what moves between them, with
django-fsm-2; the resource names the state field::

    # models.py
    from django_fsm import FSMField, transition

    class Ticket(models.Model):
        status = FSMField(choices=Status.choices, default=Status.OPEN)

        @transition(field=status, source=[Status.OPEN], target=Status.RESOLVED,
                    permission="example.resolve_ticket",
                    custom={"label": _("Resolve"), "icon": "task_alt",
                            "fields": ("resolution",)})
        def resolve(self): ...

    # resources.py
    class TicketResource(ModelResource):
        transitions = ("status",)

Each transition then becomes a button on the record's page - only from
the states it leaves, only for a reader allowed to take it - and a bulk
action on the list. The state field is read only everywhere else: a
state changes through its transitions or not at all.

The metadata is the ``custom`` dict django-fsm-2 already carries:
``label``, ``icon``, ``confirm``, ``variant`` (``default`` or
``danger``), and ``fields`` - form fields asked before the transition
runs, validated by the resource's own form serializer.

Who may take one: the resource's ``has_change_permission(request,
obj)``, the transition's own ``permission`` and its ``conditions``. The
endpoint checks all three again under a row lock, and answers 409 when
the record has left the state the page saw.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Sequence

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import connections, router, transaction
from django.utils.encoding import force_str
from django.utils.text import capfirst


@dataclasses.dataclass(frozen=True)
class TransitionInfo:
    """One transition, read from the model: the same for every reader."""

    name: str
    field: str
    label: Any
    icon: str
    variant: str
    confirm: Any
    fields: tuple[str, ...]
    method: Any

    def meta(self) -> Any:
        return self.method._django_fsm

    def describe(self, resource: Any, obj: Any = None) -> dict[str, Any]:
        """As the page reads it."""
        target = None

        if obj is not None:
            transition = self.meta().get_transition(state_of(obj, self.field))
            target = getattr(transition, "target", None)

        return {
            "name": self.name,
            "label": force_str(self.label),
            "icon": self.icon,
            "variant": self.variant,
            "confirm": force_str(self.confirm) if self.confirm else "",
            "fields": [describe_field(resource, name) for name in self.fields],
            "target": force_str(target) if target is not None else None,
        }


class TransitionRefused(Exception):
    """A transition that may not run: ``status`` says why, as HTTP."""

    def __init__(self, status: int, message: Any) -> None:
        super().__init__(force_str(message))
        self.status = status
        self.message = force_str(message)


def fsm() -> Any:
    try:
        import django_fsm
    except ImportError:
        return None

    return django_fsm


def state_of(obj: Any, field: str) -> Any:
    return getattr(obj, field)


def describe_field(resource: Any, name: str) -> dict[str, Any]:
    """A field a transition asks for, as the dialog draws it."""
    from django.db import models

    field = resource.model._meta.get_field(name)
    overrides = (resource.form_overrides or {}).get(name, {})

    return {
        "name": name,
        "label": force_str(
            overrides.get("label") or capfirst(field.verbose_name)
        ),
        "required": not field.blank,
        "multiline": isinstance(field, models.TextField),
        "maxLength": getattr(field, "max_length", None),
    }


def read_transitions(resource: Any) -> dict[str, TransitionInfo]:
    """Every transition of the fields the resource names, checked.

    Raises ``ImproperlyConfigured`` naming the resource and what is
    wrong: django-fsm-2 missing, a name that is no state field, a field
    with no transition, a transition asking for a field the model does
    not have, or two fields with a transition of the same name.
    """
    names = tuple(getattr(resource, "transitions", ()) or ())

    if not names:
        return {}

    owner = type(resource).__name__
    library = fsm()

    if library is None:
        raise ImproperlyConfigured(
            f"{owner}.transitions needs django-fsm-2: pip install "
            f"'django-generic[fsm]'."
        )

    model = resource.model
    found: dict[str, TransitionInfo] = {}

    for field_name in names:
        try:
            field = model._meta.get_field(field_name)
        except FieldDoesNotExist:
            field = None

        if not isinstance(field, library.FSMFieldMixin):
            raise ImproperlyConfigured(
                f"{owner}.transitions: {field_name!r} is not a state "
                f"field (FSMField) of {model.__name__}."
            )

        methods = field.transitions.get(model, {})

        if not methods:
            raise ImproperlyConfigured(
                f"{owner}.transitions: {model.__name__}.{field_name} has no "
                f"@transition method."
            )

        for name, method in methods.items():
            if name in found:
                raise ImproperlyConfigured(
                    f"{owner}.transitions: two state fields have a "
                    f"transition named {name!r}."
                )

            found[name] = info_of(resource, field_name, name, method)

    return found


def info_of(
    resource: Any, field: str, name: str, method: Any
) -> TransitionInfo:
    # One @transition may carry several sources; they share their
    # custom dict, which the first one's describes.
    first = next(iter(method._django_fsm.transitions.values()))
    custom = dict(first.custom or {})
    fields = tuple(custom.get("fields", ()) or ())

    for extra in fields:
        try:
            resource.model._meta.get_field(extra)
        except FieldDoesNotExist:
            raise ImproperlyConfigured(
                f"{type(resource).__name__}.transitions: {name} asks for "
                f"{extra!r}, which is not a field of "
                f"{resource.model.__name__}."
            )

    variant = custom.get("variant", "default")

    if variant not in ("default", "danger"):
        raise ImproperlyConfigured(
            f"{type(resource).__name__}.transitions: {name}'s variant must "
            f"be 'default' or 'danger', not {variant!r}."
        )

    return TransitionInfo(
        name=name,
        field=field,
        label=custom.get("label") or capfirst(name.replace("_", " ")),
        icon=str(custom.get("icon", "")),
        variant=variant,
        confirm=custom.get("confirm", ""),
        fields=fields,
        method=method,
    )


def state_fields(resource: Any) -> tuple[str, ...]:
    """The fields no form or grid may write: their transitions do."""
    return tuple(getattr(resource, "transitions", ()) or ())


# ---------------------------------------------------------------------
# Who may, on which record
# ---------------------------------------------------------------------


def may_take(
    resource: Any,
    request: Any,
    info: TransitionInfo,
    obj: Any,
) -> bool:
    """From this record's state, for this reader, now."""
    meta = info.meta()
    state = state_of(obj, info.field)

    if not meta.has_transition(state) or not meta.conditions_met(obj, state):
        return False

    if not resource.has_change_permission(request, obj):
        return False

    return bool(meta.has_transition_perm(obj, state, request.user))


def may_offer(resource: Any, request: Any, info: TransitionInfo) -> bool:
    """Whether a reader could take it on some record: the list's test."""
    if not resource.has_change_permission(request):
        return False

    permissions = {
        transition.permission
        for transition in info.meta().transitions.values()
    }

    for permission in permissions:
        if not permission or callable(permission):
            # A callable decides per record: offered, decided then.
            return True

        if request.user.has_perm(permission):
            return True

    return False


def available(resource: Any, request: Any, obj: Any) -> list[TransitionInfo]:
    return [
        info
        for info in resource.get_transitions().values()
        if may_take(resource, request, info, obj)
    ]


# ---------------------------------------------------------------------
# Taking one
# ---------------------------------------------------------------------


def locked(resource: Any, request: Any, pk: Any) -> Any:
    """The record, read again under a row lock, through the resource."""
    queryset = resource.get_queryset(request)
    database = router.db_for_write(resource.model)
    features = connections[database].features

    if features.has_select_for_update:
        # Only the record's own row: its joins may be nullable, and
        # PostgreSQL refuses to lock the nullable side of one.
        of = ("self",) if features.has_select_for_update_of else ()
        queryset = queryset.select_for_update(of=of)

    return queryset.get(pk=pk)


def take(
    resource: Any,
    request: Any,
    pk: Any,
    name: str,
    values: dict[str, Any] | None = None,
) -> Any:
    """Run one transition on one record, in one transaction.

    Raises ``TransitionRefused``: 404 for a name the resource does not
    declare or a record out of reach, 403 for a reader not allowed, 409
    for a record no longer in a state the transition leaves, 400 for
    values the form refuses.
    """
    from django.utils.translation import gettext
    from rest_framework.exceptions import ValidationError

    from generic.history import acting_as

    info = resource.get_transitions().get(name)

    if info is None:
        raise TransitionRefused(404, gettext("There is no such transition."))

    with transaction.atomic(using=router.db_for_write(resource.model)):
        try:
            obj = locked(resource, request, pk)
        except resource.model.DoesNotExist:
            raise TransitionRefused(404, gettext("There is no such record."))

        meta = info.meta()
        state = state_of(obj, info.field)

        if not meta.has_transition(state) or not meta.conditions_met(
            obj, state
        ):
            raise TransitionRefused(
                409,
                gettext(
                    "This record is no longer in a state it can be "
                    "%(action)s from."
                )
                % {"action": force_str(info.label).lower()},
            )

        if not resource.has_change_permission(
            request, obj
        ) or not meta.has_transition_perm(obj, state, request.user):
            raise TransitionRefused(
                403, gettext("You may not do this to this record.")
            )

        if info.fields:
            written = {
                field: value
                for field, value in (values or {}).items()
                if field in info.fields
            }
            serializer = resource.get_form_serializer_class()(
                obj,
                data=written,
                partial=True,
                context={"request": request},
            )
            required = [
                field
                for field in info.fields
                if describe_field(resource, field)["required"]
                and written.get(field) in (None, "")
            ]

            if required:
                raise ValidationError(
                    {
                        field: [gettext("This field is required.")]
                        for field in required
                    }
                )

            serializer.is_valid(raise_exception=True)

            for field, value in serializer.validated_data.items():
                setattr(obj, field, value)

        with acting_as(request.user, source=f"Transition: {info.label}"):
            getattr(obj, name)()
            obj.save()

    return obj


def bulk_action(resource: Any, info: TransitionInfo) -> Any:
    """The list's action for one transition: each row it can leave."""
    from django.utils.translation import gettext

    def run(request: Any, queryset: Any) -> dict[str, Any]:
        done = skipped = 0

        for pk in queryset.values_list("pk", flat=True):
            try:
                take(resource, request, pk, info.name)
            except TransitionRefused:
                skipped += 1
            else:
                done += 1

        message = gettext(
            "%(action)s: %(done)s done, %(skipped)s skipped (not in a state "
            "that allows it, or not allowed)."
        ) % {
            "action": force_str(info.label),
            "done": done,
            "skipped": skipped,
        }

        return {
            "message": message,
            "level": "success" if done and not skipped else "warning",
        }

    return run


ACTION_PREFIX = "transition:"


def action_name(info: TransitionInfo) -> str:
    return f"{ACTION_PREFIX}{info.name}"


def is_transition_action(name: str) -> bool:
    return name.startswith(ACTION_PREFIX)


__all__: Sequence[str] = (
    "TransitionInfo",
    "TransitionRefused",
    "available",
    "read_transitions",
    "take",
)
