"""Dependent relations: a field's options narrowed by another field.

A resource declares which of its form's relations depend on another of
its fields::

    class TicketResource(ModelResource):
        forwards = (
            # The contacts of the customer chosen above.
            Forward("contact", on="customer", lookup="customer"),
        )

The form sends the value of ``on`` with each search of ``field``'s
autocomplete, which offers only the options matching it, and empties
``field`` when ``on`` changes. Saving checks it again: a value that is
not one of the options of the ``on`` chosen is refused, whatever sent
it - the form, a table's cell, a bulk edit or an import.

The client names the form and the field; what they filter on is
declared here, so it never sends an ORM path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db.models import Model, QuerySet
from django.utils.encoding import force_str
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

#: The query string of an autocomplete asked on behalf of a form.
FROM_PARAM = "forward_from"
FIELD_PARAM = "forward_field"
VALUE_PARAM = "forward_value"


@dataclass(frozen=True)
class Forward:
    """``field``'s options, narrowed by the value of ``on``.

    ``lookup`` is a path on the options' model matched against the
    value of ``on`` (its key, for a relation). ``filter`` does anything
    else: ``filter(queryset, value, request)`` returns the options,
    ``value`` being what ``on`` holds - for a relation, its key. One of
    the two is given.

    ``model`` is the options' model when ``field`` is not a relation of
    the model - a plain key whose autocomplete ``form_overrides``
    names - so that a save can still be checked. ``clear`` (True)
    empties ``field`` in the form when ``on`` changes.
    """

    field: str
    on: str
    lookup: str | None = None
    filter: Callable[[QuerySet, Any, Any], QuerySet] | None = None
    model: type[Model] | None = None
    clear: bool = True

    def __post_init__(self) -> None:
        if (self.lookup is None) == (self.filter is None):
            raise ImproperlyConfigured(
                f"Forward('{self.field}', on='{self.on}'): give a "
                f"lookup or a filter, one of the two."
            )

    def narrow(self, queryset: QuerySet, value: Any, request: Any) -> Any:
        """The options matching ``value``; all of them without one."""
        if value in (None, "", []):
            return queryset

        if self.filter is not None:
            return self.filter(queryset, value, request)

        try:
            return queryset.filter(**{str(self.lookup): value})
        except (TypeError, ValueError, ValidationError):
            # A value of the wrong kind matches nothing.
            return queryset.none()

    def describe(self, resource: Any) -> dict[str, Any]:
        """What the form needs: which field to read, and where from."""
        return {
            "on": self.on,
            "from": resource.label_lower,
            "field": self.field,
            "clear": self.clear,
        }


def forwards_of(resource: Any) -> dict[str, Forward]:
    """The resource's forwards, by dependent field."""
    declared = getattr(resource, "forwards", ()) or ()
    result: dict[str, Forward] = {}

    for forward in declared:
        if not isinstance(forward, Forward):
            raise ImproperlyConfigured(
                f"{type(resource).__name__}.forwards holds Forward "
                f"declarations, not {forward!r}."
            )

        result[forward.field] = forward

    return result


def form_overrides(resource: Any, overrides: dict | None) -> dict:
    """``overrides`` with each dependent field told what it follows."""
    merged = {name: dict(entry) for name, entry in (overrides or {}).items()}

    for name, forward in forwards_of(resource).items():
        merged.setdefault(name, {})["forward"] = forward.describe(resource)

    return merged


def key_of(value: Any) -> Any:
    """A record's key, a list of keys, or the value itself."""
    if isinstance(value, Model):
        return value.pk

    if isinstance(value, (list, tuple, QuerySet)):
        return [key_of(item) for item in value]

    if hasattr(value, "all") and callable(value.all):
        # A saved record's many-to-many: its manager.
        return [item.pk for item in value.all()]

    return value


def requested(request: Any, site: Any) -> tuple[Forward, Any] | None:
    """The forward an autocomplete is asked for, and the value sent.

    None when the request names none, or one that is not declared, or
    the reader may not use that form: the options are then not
    narrowed, as for any other search.
    """
    params = getattr(request, "query_params", None) or {}
    label = params.get(FROM_PARAM)
    field = params.get(FIELD_PARAM)

    if not label or not field:
        return None

    resource = site.get_resource_by_label(label)

    if resource is None:
        return None

    forward = forwards_of(resource).get(field)

    if forward is None:
        return None

    if not (
        resource.has_add_permission(request)
        or resource.has_change_permission(request)
    ):
        return None

    raw = params.get(VALUE_PARAM, "")
    value: Any = (
        [item for item in raw.split(",") if item] if "," in raw else raw
    )

    return forward, value


def narrow_autocomplete(
    queryset: QuerySet,
    request: Any,
    site: Any,
) -> QuerySet:
    """An autocomplete's options, narrowed by the form that asks."""
    asked = requested(request, site)

    if asked is None:
        return queryset

    forward, value = asked

    return forward.narrow(queryset, value, request)


def options_of(
    forward: Forward,
    field: serializers.Field | None,
    model: type[Model],
    request: Any,
) -> QuerySet | None:
    """The options ``forward``'s field takes, before narrowing: the
    serializer field's, or those of the model it points at - a table's
    cell holds only the field it writes."""
    relation = getattr(field, "child_relation", field)
    queryset = getattr(relation, "queryset", None)

    if queryset is not None and forward.model is None:
        return queryset.all()

    target = forward.model

    if target is None:
        try:
            target = model._meta.get_field(forward.field).related_model
        except Exception:
            target = None

    if target is None:
        return None

    from generic.api.relations import get_resource_for

    resource = get_resource_for(target)

    if resource is not None and request is not None:
        return resource.get_autocomplete_queryset(request)

    return target._default_manager.all()


def check_forwards(serializer: Any, attrs: dict[str, Any]) -> None:
    """Hold a dependent value to the options of the ``on`` it is saved
    with.

    Only when one of the two changes: a record saved before the rule,
    or edited in another field, is left as it is. When ``on`` alone
    changes - a table's cell, a bulk edit - a value it no longer
    allows is emptied, as the form empties it, when the field may be
    empty and ``clear`` is set; refused otherwise. A value chosen with
    the wrong ``on`` is refused.
    """
    resource = getattr(serializer, "generic_resource", None)

    if resource is None:
        return

    instance = serializer.instance
    request = serializer.context.get("request")
    errors: dict[str, str] = {}

    for name, forward in forwards_of(resource).items():
        if name not in attrs and forward.on not in attrs:
            continue

        current = (
            attrs[name] if name in attrs else getattr(instance, name, None)
        )
        on_value = (
            attrs[forward.on]
            if forward.on in attrs
            else getattr(instance, forward.on, None)
        )
        keys = key_of(current)

        if keys in (None, "", []):
            continue

        if instance is not None and (
            key_of(getattr(instance, name, None)) == keys
            and key_of(getattr(instance, forward.on, None)) == key_of(on_value)
        ):
            continue

        field = serializer.fields.get(name)
        options = options_of(forward, field, serializer.Meta.model, request)

        if options is None:
            continue

        wanted = set(keys) if isinstance(keys, list) else {keys}
        narrowed = forward.narrow(options, key_of(on_value), request)
        found = {
            str(key)
            for key in narrowed.filter(pk__in=wanted).values_list(
                "pk", flat=True
            )
        }

        if found == {str(key) for key in wanted}:
            continue

        if name not in attrs and forward.clear and may_empty(instance, name):
            attrs[name] = [] if isinstance(keys, list) else None
            continue

        on_field = serializer.fields.get(forward.on)
        errors[name] = force_str(
            _("Not one of the choices for this %(field)s.")
            % {
                "field": force_str(
                    getattr(on_field, "label", None) or forward.on
                ).lower()
            }
        )

    if errors:
        raise serializers.ValidationError(errors)


def may_empty(instance: Any, name: str) -> bool:
    """Whether the model lets ``name`` be empty."""
    try:
        field = type(instance)._meta.get_field(name)
    except Exception:
        return False

    return bool(field.many_to_many or field.null)
