"""How a relation field is edited in a schema-driven form.

A foreign key or a many-to-many becomes a Select2 control. Two ways to
feed it, chosen per field:

* **autocomplete** - when the related model is registered on the site
  with ``search_fields``, the control queries that model's own
  autocomplete endpoint as the user types. Nothing is embedded in the
  schema, so a table of a million rows costs nothing.
* **embedded choices** - otherwise, up to ``FORM_CHOICES_LIMIT`` options
  travel with the schema. DRF would happily embed the whole queryset;
  capping it keeps a forgotten registration from shipping a table.

Current values are labelled through ``_display`` on the record rather
than by looking them up again, so an existing selection renders at once.
"""

from __future__ import annotations

from typing import Any

from django.db import models
from django.utils.encoding import force_str
from rest_framework import serializers

from generic.conf import generic_settings

#: Key under which a record carries the labels of its related values.
DISPLAY_KEY = "_display"

#: Key under which a record carries its own label, ``str(record)``.
LABEL_KEY = "_label"


def is_related_field(field: serializers.Field) -> bool:
    return isinstance(
        field,
        (serializers.RelatedField, serializers.ManyRelatedField),
    )


def relation_of(field: serializers.Field) -> serializers.RelatedField:
    """The single-valued relation, unwrapping a many-to-many."""
    if isinstance(field, serializers.ManyRelatedField):
        return field.child_relation

    return field


def related_model_of(field: serializers.Field) -> type[models.Model] | None:
    queryset = getattr(relation_of(field), "queryset", None)

    return getattr(queryset, "model", None)


def value_key(relation: serializers.RelatedField, instance: Any) -> str:
    """The value the form sends for ``instance``, as a string.

    A slug relation submits the slug; everything else, the primary key.
    """
    if isinstance(relation, serializers.SlugRelatedField):
        return force_str(getattr(instance, relation.slug_field))

    return force_str(instance.pk)


def get_resource_for(model: type[models.Model] | None) -> Any:
    """The resource registered for ``model`` on the default site."""
    if model is None:
        return None

    try:
        from generic.sites import site
    except ImportError:  # pragma: no cover - the package always ships it
        return None

    return site.get_resource(model)


def narrow_relation(field: serializers.Field, request: Any) -> None:
    """Offer and accept only what the related resource lets ``request``
    reach, where that resource says so (``scope_relations``).

    The choices a form embeds and the values it validates come from the
    same queryset, so a record of another team is neither listed nor
    taken when its key is sent by hand.
    """
    relation = relation_of(field)
    queryset = getattr(relation, "queryset", None)
    resource = get_resource_for(getattr(queryset, "model", None))

    if resource is None:
        return

    scoped = resource.get_relation_queryset(request)

    if scoped is not None:
        relation.queryset = scoped


def embedded_choices(
    relation: serializers.RelatedField,
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Up to ``limit`` options, and whether there were more."""
    queryset = getattr(relation, "queryset", None)

    if queryset is None:
        return [], False

    rows = list(queryset.all()[: limit + 1])

    return (
        [
            {"value": value_key(relation, row), "label": force_str(row)}
            for row in rows[:limit]
        ],
        len(rows) > limit,
    )


def describe_relation(
    field: serializers.Field,
    request: Any = None,
) -> dict[str, Any]:
    """Schema entries telling the client how to feed a relation field."""
    relation = relation_of(field)
    model = related_model_of(field)

    if model is None:
        return {}

    info: dict[str, Any] = {
        "relatedModel": model._meta.label_lower,
        "relatedLabel": force_str(model._meta.verbose_name),
    }

    resource = get_resource_for(model)
    has_autocomplete = bool(
        resource is not None
        and resource.get_search_fields(request)
        and not isinstance(relation, serializers.SlugRelatedField)
    )

    if has_autocomplete:
        info["autocompleteUrl"] = resource.get_autocomplete_url()
    else:
        choices, truncated = embedded_choices(
            relation,
            generic_settings.FORM_CHOICES_LIMIT,
        )
        info["choices"] = choices

        if truncated:
            # Surfaced rather than silently dropped: the missing options
            # would otherwise just seem not to exist.
            info["choicesTruncated"] = True

    if resource is not None and request is not None:
        if resource.has_add_permission(request):
            info["relatedCreateUrl"] = resource.get_add_url()

        if resource.has_change_permission(request):
            info["relatedUpdateUrl"] = resource.get_change_url_template("{id}")

    return info


def build_display_labels(
    serializer: serializers.Serializer,
    instance: Any,
) -> dict[str, dict[str, str]]:
    """Labels of the related values ``instance`` currently holds.

    ``{"team": {"3": "Front office"}, "tags": {"1": "billing"}}`` - keyed
    by the submitted value, so the client can label any selection.
    """
    if not isinstance(instance, models.Model):
        return {}

    labels: dict[str, dict[str, str]] = {}

    for name, field in serializer.fields.items():
        if field.write_only or not is_related_field(field):
            continue

        source = field.source

        if not source or source == "*" or "." in source:
            continue

        try:
            value = getattr(instance, source)
        except Exception:
            # A dangling foreign key, or a relation on an unsaved row.
            continue

        if value is None:
            continue

        relation = relation_of(field)

        if hasattr(value, "all"):
            labels[name] = {
                value_key(relation, item): force_str(item)
                for item in value.all()
            }
        else:
            labels[name] = {value_key(relation, value): force_str(value)}

    return labels
