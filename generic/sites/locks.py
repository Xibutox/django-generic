"""A record that locks: once a field says so, it can no longer change.

Declared on the resource::

    @register(Invoice)
    class InvoiceResource(ModelResource):
        # Locked while ``is_sent`` is true: nothing changes but the
        # flag itself, and the lines go with it.
        lock = Lock("is_sent", related=("lines",))
        # or, with more to say:
        lock = Lock(
            "status",                       # a field, or "order__status"
            values=("sent", "paid"),        # locked in these states
            fields=None,                    # what freezes: None = all
            exclude=("notes",),             # still written while locked
            related=("lines", "payments"),  # their records lock too
            delete=True,                    # nor may it be deleted
            permission="billing.unlock_invoice",  # who it does not hold
            message=_("A sent invoice cannot be changed."),
        )

The condition is one field of the record, or of a record it points at
(``"order__is_closed"``, through foreign keys): locked when its value is
one of ``values`` - or, without ``values``, when it is set (true, for a
boolean; neither empty nor null otherwise). The field itself stays
writable - unlocking is changing it - so who may lock and unlock is
whoever may change that field (``field_permissions`` guards it).

While locked, every write of the framework refuses to change a frozen
field, with ``message``: the form (the fields shown read only, the
change refused by the API), a cell of a grid, a bulk edit (the record
counted as refused), an import, a transition whose state field is
frozen, the inline rows of the form, and the records of the ``related``
relations - each one locked as if it declared ``Lock`` itself, a new one
refused under a locked record. A locked record cannot be deleted either
(``delete=False`` lets it), alone or in a selection.

Nothing here is a database constraint: a ``queryset.update()`` in a bulk
action, a shell, a migration still write. An action of the project's
own narrows its selection with ``resource.unlocked(request, queryset)``.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable, Sequence

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.db.models import Q
from django.utils.encoding import force_str
from django.utils.translation import gettext_lazy, ngettext
from rest_framework import serializers

#: What a refusal says when the declaration says nothing.
DEFAULT_MESSAGE = gettext_lazy("This record is locked: it cannot be changed.")


@dataclasses.dataclass(frozen=True)
class Lock:
    """When a record locks, and what it freezes.

    ``field`` - the field saying whether it is locked: the record's own,
    or a path through foreign keys (``"order__is_closed"``).
    ``values`` - the values that lock it; None: any value set (true,
    for a boolean). ``fields`` - the fields (and inlines, by name)
    frozen while locked; None: all of them. ``exclude`` - the ones
    still written while locked. ``related`` - one-to-many relations
    (their related names) whose records are locked with it.
    ``delete`` - whether a locked record may not be deleted.
    ``permission`` - who the lock does not hold back: a permission
    string, or ``callable(request, obj) -> bool``. ``message`` - what a
    refusal says, and the record's page.
    """

    field: str
    values: Sequence[Any] | None = None
    fields: Sequence[str] | None = None
    exclude: Sequence[str] = ()
    related: Sequence[str] = ()
    delete: bool = True
    permission: str | Callable[[Any, Any], bool] | None = None
    message: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.field, str) or not self.field:
            raise ImproperlyConfigured(
                f"Lock(field=...) is a field name, not {self.field!r}."
            )

        for name in ("values", "fields", "exclude", "related"):
            value = getattr(self, name)

            if value is None:
                continue

            if isinstance(value, str):
                raise ImproperlyConfigured(
                    f"Lock({name}=...) is a tuple, not one string: "
                    f"({value!r},)."
                )

            object.__setattr__(self, name, tuple(value))


class BoundLock:
    """A lock resolved against the resource's model.

    ``via`` is the foreign key of a lock a parent's ``related`` hands to
    its children: the child is locked when the record it points at is,
    and the whole of it freezes.
    """

    def __init__(
        self,
        resource: Any,
        declaration: Lock,
        path: str,
        via: str = "",
        source: Any = None,
    ) -> None:
        self.resource = resource
        self.declaration = declaration
        self.path = path
        self.via = via
        self.source = source
        self.segments = path.split("__")
        self.field = walk(resource.model, self.segments, self.owner())
        self.values = (
            None if declaration.values is None else tuple(declaration.values)
        )

        if via:
            self.fields: frozenset[str] | None = None
            self.exclude: frozenset[str] = frozenset()
            self.related: frozenset[str] = frozenset()
        else:
            self.fields = (
                None
                if declaration.fields is None
                else frozenset(declaration.fields)
            )
            # The lock's own field is how it is undone: never frozen.
            own = {path} if len(self.segments) == 1 else set()
            self.exclude = frozenset(declaration.exclude) | own
            self.related = frozenset(declaration.related)

    def owner(self) -> str:
        if self.source is not None:
            return f"{type(self.source).__name__}.lock (related)"

        return f"{type(self.resource).__name__}.lock"

    @property
    def through(self) -> bool:
        """Whether the condition is read on another record."""
        return len(self.segments) > 1

    @property
    def message(self) -> str:
        return force_str(self.declaration.message or DEFAULT_MESSAGE)

    # -- the condition -----------------------------------------------------

    def holds(self, value: Any) -> bool:
        """Whether the field's value locks."""
        if self.values is not None:
            return value in self.values

        if isinstance(self.field, models.BooleanField):
            return value is True

        return value not in (None, "")

    def read(self, obj: Any, segments: Sequence[str]) -> Any:
        """The value at the end of ``segments``; None past an empty
        relation."""
        value = obj

        for name in segments:
            if value is None:
                return None

            value = getattr(value, name, None)

        return value

    def is_set(self, obj: Any) -> bool:
        return self.holds(self.read(obj, self.segments))

    def is_set_from(self, target: Any) -> bool:
        """Whether a record pointing at ``target`` (through the first
        segment) would be locked."""
        return self.holds(self.read(target, self.segments[1:]))

    def q(self) -> Q:
        """The condition in SQL, for a queryset."""
        if self.values is not None:
            return Q(**{f"{self.path}__in": self.values})

        if isinstance(self.field, models.BooleanField):
            return Q(**{self.path: True})

        condition = Q(**{f"{self.path}__isnull": False})

        if isinstance(self.field, (models.CharField, models.TextField)):
            condition &= ~Q(**{self.path: ""})

        return condition

    # -- who it holds back -------------------------------------------------

    def spares(self, request: Any, obj: Any) -> bool:
        """Whether this reader is not held back by it."""
        permission = self.declaration.permission

        if permission is None:
            return False

        if callable(permission):
            return bool(permission(request, obj))

        user = getattr(request, "user", None)

        return bool(user is not None and user.has_perm(permission))

    def applies(self, request: Any, obj: Any) -> bool:
        return self.is_set(obj) and not self.spares(request, obj)

    # -- what it freezes ---------------------------------------------------

    def freezes(self, name: str) -> bool:
        if name in self.exclude:
            return False

        if name in self.related:
            return True

        return self.fields is None or name in self.fields


class LockState:
    """The locks holding one record for one reader, now."""

    def __init__(self, parts: Sequence[BoundLock]) -> None:
        self.parts = tuple(parts)

    def __bool__(self) -> bool:
        return bool(self.parts)

    @property
    def locked(self) -> bool:
        return bool(self.parts)

    @property
    def message(self) -> str:
        return " ".join(dict.fromkeys(part.message for part in self.parts))

    @property
    def delete(self) -> bool:
        """Whether it refuses to be deleted."""
        return any(part.declaration.delete or part.via for part in self.parts)

    @property
    def everything(self) -> bool:
        """Whether nothing of it may be written at all."""
        return any(
            part.fields is None and not part.exclude for part in self.parts
        )

    def freezes(self, name: str) -> bool:
        return any(part.freezes(name) for part in self.parts)

    def as_client(self) -> dict[str, Any] | None:
        """What the record's page and form read: ``fields`` frozen (null:
        every one but ``except``)."""
        if not self.parts:
            return None

        named: set[str] = set()
        excepted: set[str] | None = None

        for part in self.parts:
            if part.fields is None:
                excepted = (
                    set(part.exclude)
                    if excepted is None
                    else excepted & set(part.exclude)
                )
            else:
                named |= set(part.fields) - part.exclude

            named |= set(part.related) - part.exclude

        return {
            "locked": True,
            "message": self.message,
            "fields": None if excepted is not None else sorted(named),
            "except": sorted((excepted or set()) - named),
            "delete": self.delete,
            "everything": self.everything,
        }


# -- resolution ---------------------------------------------------------------


def walk(model: Any, segments: Sequence[str], owner: str) -> Any:
    """The field at the end of ``segments``, through foreign keys."""
    current = model
    field = None

    for index, name in enumerate(segments):
        try:
            field = current._meta.get_field(name)
        except FieldDoesNotExist:
            raise ImproperlyConfigured(
                f"{owner} reads {'__'.join(segments)!r}, but "
                f"{current.__name__} has no field {name!r}."
            ) from None

        last = index == len(segments) - 1

        if field.many_to_many or field.one_to_many:
            raise ImproperlyConfigured(
                f"{owner} reads {'__'.join(segments)!r}: {name!r} holds "
                f"many records, and a lock reads one value."
            )

        if not last:
            if not field.is_relation:
                raise ImproperlyConfigured(
                    f"{owner} reads {'__'.join(segments)!r}: {name!r} "
                    f"is not a foreign key to go through."
                )

            current = field.related_model

    return field


def frozen_names(resource: Any) -> set[str]:
    """Every name ``fields``, ``exclude`` and ``related`` may use: the
    model's fields and its one-to-many relations (inlines)."""
    opts = resource.model._meta
    names = {field.name for field in [*opts.fields, *opts.many_to_many]}
    names |= {
        relation.get_accessor_name()
        for relation in opts.related_objects
        if relation.one_to_many or relation.one_to_one
    }
    names |= set(getattr(resource, "form_extra_fields", {}) or {})

    return names


def one_to_many(model: Any, name: str) -> Any:
    for relation in model._meta.related_objects:
        if relation.one_to_many and relation.get_accessor_name() == name:
            return relation

    return None


def resolve(resource: Any) -> BoundLock | None:
    """``resource.lock`` resolved and checked, or None."""
    declared = getattr(resource, "lock", None)
    owner = f"{type(resource).__name__}.lock"

    if not declared:
        return None

    if not isinstance(declared, Lock):
        raise ImproperlyConfigured(
            f"{owner} is None or a Lock(...), not {declared!r}."
        )

    bound = BoundLock(resource, declared, declared.field)
    known = frozen_names(resource)

    for attribute in ("fields", "exclude"):
        for name in getattr(declared, attribute) or ():
            if name not in known:
                raise ImproperlyConfigured(
                    f"{owner} {attribute} {name!r}, which is neither a "
                    f"field nor an inline of {resource.model.__name__}."
                )

    for name in declared.related:
        if one_to_many(resource.model, name) is None:
            raise ImproperlyConfigured(
                f"{owner} locks {name!r} with it, which is not the "
                f"related name of a foreign key pointing at "
                f"{resource.model.__name__}."
            )

    return bound


def locks_of(resource: Any) -> tuple[BoundLock, ...]:
    """The resource's own lock, and the ones its parents' ``related``
    hand down to it. The second depend on every registration: worked
    out again whenever the registry changes."""
    site = resource.site
    registry = getattr(site, "_registry", {}) if site is not None else {}
    key = len(registry)
    cached = resource.__dict__.get("_locks")

    if cached is not None and cached[0] == key:
        return cached[1]

    found: list[BoundLock] = []
    own = resource.get_lock()

    if own is not None:
        found.append(own)

    for parent in list(registry.values()):
        bound = parent.get_lock()

        if bound is None:
            continue

        for name in sorted(bound.related):
            relation = one_to_many(parent.model, name)

            if relation is None or relation.related_model is not (
                resource.model
            ):
                continue

            via = relation.field.name
            found.append(
                BoundLock(
                    resource,
                    bound.declaration,
                    f"{via}__{bound.path}",
                    via=via,
                    source=parent,
                )
            )

    result = tuple(found)
    resource.__dict__["_locks"] = (key, result)

    return result


# -- reading ------------------------------------------------------------------


def state(resource: Any, request: Any, obj: Any) -> LockState:
    """The locks holding ``obj`` for this reader."""
    if obj is None or not isinstance(obj, resource.model):
        return LockState(())

    if getattr(obj, "pk", None) is None:
        return LockState(())

    return LockState(
        [bound for bound in locks_of(resource) if bound.applies(request, obj)]
    )


def unlocked(resource: Any, request: Any, queryset: Any, delete=False) -> Any:
    """``queryset`` without the records a lock holds for this reader -
    with ``delete``, the ones it keeps from being deleted."""
    for bound in locks_of(resource):
        if delete and not (bound.declaration.delete or bound.via):
            continue

        permission = bound.declaration.permission

        if permission is None:
            queryset = queryset.exclude(bound.q())
        elif callable(permission):
            held = [
                obj.pk
                for obj in queryset.filter(bound.q())
                if not bound.spares(request, obj)
            ]
            queryset = queryset.exclude(pk__in=held)
        elif not bound.spares(request, None):
            queryset = queryset.exclude(bound.q())

    return queryset


# -- the writes ---------------------------------------------------------------


def unchanged(serializer: Any, instance: Any, name: str, value: Any) -> bool:
    """Whether writing ``value`` to ``name`` leaves ``instance`` as it is."""
    try:
        field = instance._meta.get_field(name)
    except FieldDoesNotExist:
        field = None

    if field is not None and field.many_to_many:
        current = {obj.pk for obj in getattr(instance, name).all()}

        return current == {getattr(obj, "pk", obj) for obj in value or ()}

    if field is not None and field.concrete:
        current = getattr(instance, field.attname)
        wanted = getattr(value, "pk", value) if field.is_relation else value

        if isinstance(field, models.FileField):
            return (current or "") == (getattr(value, "name", value) or "")

        return bool(current == wanted)

    # Not the model's: compared as the form reads it.
    entry = serializer.fields.get(name)

    if entry is None:
        return False

    try:
        return bool(
            entry.to_representation(entry.get_attribute(instance))
            == entry.to_representation(value)
        )
    except Exception:  # noqa: BLE001 - cannot tell: it changes
        return False


def refusals(
    resource: Any,
    serializer: Any,
    request: Any,
    instance: Any,
    attrs: dict[str, Any],
) -> dict[str, list[str]]:
    """What a lock refuses in ``attrs``, by field."""
    errors: dict[str, list[str]] = {}
    current = state(resource, request, instance)

    if current:
        for name, value in attrs.items():
            if current.freezes(name) and not unchanged(
                serializer, instance, name, value
            ):
                errors[name] = [current.message]

    # A record put under a locked one - created there, or moved there -
    # would be locked from the start: refused on the key that does it.
    for bound in locks_of(resource):
        if not bound.through:
            continue

        key = bound.segments[0]

        if key not in attrs or key in errors:
            continue

        target = attrs[key]

        if target is None:
            continue

        if instance is not None and getattr(instance, "pk", None):
            if unchanged(serializer, instance, key, target):
                continue

        if bound.is_set_from(target) and not bound.spares(request, instance):
            errors[key] = [bound.message]

    return errors


def guarded(serializer_class: Any, resource: Any) -> Any:
    """``serializer_class``, refusing what the resource's locks freeze.

    Every write of the framework validates through a form serializer -
    the form, the cells, bulk edits, imports, transitions, a grid's new
    row - so the check sits there, once. Built once per class.
    """
    if not locks_of(resource):
        return serializer_class

    # Kept on the class itself: a cell's serializer, built per write,
    # goes with its guarded one.
    built = serializer_class.__dict__.get("_generic_guarded")

    if built is None:
        built = {}
        serializer_class._generic_guarded = built

    cached = built.get(id(resource))

    if cached is not None and cached.generic_lock_resource is resource:
        return cached

    def validate(self: Any, attrs: Any) -> Any:
        attrs = super(guarded_class, self).validate(attrs)
        instance = self.instance

        if isinstance(instance, models.Model) or instance is None:
            errors = refusals(
                resource,
                self,
                self.context.get("request"),
                instance,
                dict(attrs),
            )

            if errors:
                raise serializers.ValidationError(errors)

        return attrs

    guarded_class: Any = type(
        serializer_class.__name__,
        (serializer_class,),
        {
            "validate": validate,
            "__module__": serializer_class.__module__,
            "generic_lock_resource": resource,
        },
    )
    built[id(resource)] = guarded_class

    return guarded_class


def frozen_inlines(
    resource: Any, request: Any, obj: Any, definitions: Sequence[Any]
) -> tuple[Any, ...]:
    """The form's inline definitions, read only where the record's
    lock freezes them."""
    current = state(resource, request, obj)

    if not current:
        return tuple(definitions)

    return tuple(
        (
            dataclasses.replace(definition, read_only=True)
            if current.freezes(definition.name)
            else definition
        )
        for definition in definitions
    )


def refused_delete(resource: Any, request: Any, obj: Any) -> str:
    """Why ``obj`` may not be deleted by this reader, or ``""``."""
    current = state(resource, request, obj)

    return current.message if current and current.delete else ""


def delete_refusal(count: int) -> str:
    return ngettext(
        "Nothing was deleted: %(count)s of the selected records is " "locked.",
        "Nothing was deleted: %(count)s of the selected records are "
        "locked.",
        count,
    ) % {"count": count}
