"""Inlines: editing related rows alongside their parent.

One request carries the parent and its related rows, and the whole thing
either lands or does not.

Applying an inline payload runs in three phases, inside the caller's
transaction:

1. **Parse** - structural checks that need no database write: row shape,
   ownership of every referenced row, add/change/delete permissions, row
   counts.
2. **Delete** - the removals are executed.
3. **Validate and save** - the remaining rows are validated against the
   state left by phase 2, then written.

Deleting before validating is what lets one request free a slot and
reuse it: swapping the row occupying a unique position only validates if
the old row is already gone. Any failure in phase 3 raises, and the
caller's transaction takes the deletions back with it.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Iterable, Literal

from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from generic.api.forms import (
    FILE_TYPES,
    FormSerializerMixin,
    remove_none_values,
    resolve_related_editor_url,
)

#: Key under which the client nests its inline rows.
INLINE_PAYLOAD_KEY = "_inlines"

#: Row flag asking for a deletion.
DELETE_FLAG = "_delete"

#: Key carrying errors that belong to a collection rather than a row.
COLLECTION_ERRORS_KEY = "_errors"

#: How the rows are drawn: a compact table, or one card per row.
PRESENTATIONS = frozenset({"tabular", "stacked"})

Operation = Literal["create", "update", "delete"]


@dataclasses.dataclass(frozen=True)
class PendingRow:
    """A row to write, before its serializer has run."""

    key: str
    data: dict[str, Any]
    instance: Any = None

    @property
    def operation(self) -> Operation:
        return "update" if self.instance is not None else "create"


@dataclasses.dataclass
class ParsedCollection:
    """One inline collection, split into what it does."""

    deletions: list[Any] = dataclasses.field(default_factory=list)
    writes: list[PendingRow] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class InlineOperation:
    """One write that has been validated and is ready to apply."""

    operation: Operation
    instance: Any = None
    serializer: serializers.Serializer | None = None


@dataclasses.dataclass(frozen=True)
class InlineFormDefinition:
    """Configure one inline collection.

    ``serializer_class``
        Must inherit :class:`~generic.api.forms.FormSerializerMixin`.
    ``related_name``
        Reverse manager on the parent model.
    ``parent_field``
        Foreign key field on the inline model, supplied on save.
    """

    name: str
    serializer_class: type[serializers.Serializer]
    related_name: str
    parent_field: str
    title: str

    description: str = ""
    #: Singular name of one row, for "Add another ...".
    verbose_name: str = ""
    primary_key: str = "id"
    position: int = 0
    #: Blank rows the client pre-renders.
    extra: int = 0
    min_rows: int = 0
    max_rows: int | None = None
    can_add: bool = True
    #: Whether rows that already exist may be edited.
    can_change: bool = True
    can_delete: bool = True
    #: Nothing may be changed at all: the rows are only shown.
    read_only: bool = False
    #: ``tabular`` or ``stacked``.
    presentation: str = "tabular"
    #: Drawn in its own tab rather than below the fieldsets.
    tab: bool = False
    #: Starts folded.
    collapsed: bool = False
    add_label: str = _("Add a row")
    delete_label: str = _("Remove")

    #: Presentation overrides applied on top of the serializer metadata.
    form_overrides: dict[str, dict[str, Any]] = dataclasses.field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not issubclass(self.serializer_class, FormSerializerMixin):
            raise TypeError(
                f"{self.serializer_class.__name__} must inherit "
                f"FormSerializerMixin to be used as an inline."
            )

        if self.presentation not in PRESENTATIONS:
            raise ValueError(
                f"Unknown inline presentation '{self.presentation}'. "
                f"Expected one of: {', '.join(sorted(PRESENTATIONS))}."
            )

    # -- data ---------------------------------------------------------

    def get_queryset(self, parent: Any) -> QuerySet:
        """Rows currently attached to ``parent``."""
        return getattr(parent, self.related_name).all()

    # -- schema -------------------------------------------------------

    def get_form_fields(
        self,
        request: Any = None,
    ) -> list[dict[str, Any]]:
        # Guaranteed to be a FormSerializerMixin by __post_init__.
        serializer_class: Any = self.serializer_class
        fields = serializer_class.get_form_fields(request=request)
        result: list[dict[str, Any]] = []

        for configuration in fields:
            configuration = dict(configuration)
            field_name = configuration["name"]

            # The parent link is supplied on save, never edited.
            if field_name == self.parent_field:
                continue

            overrides = self.form_overrides.get(field_name, {})

            if overrides.get("enabled") is False:
                continue

            overrides = resolve_related_editor_url(
                overrides,
                field_name=field_name,
            )
            configuration.update(overrides)

            # A row travels inside the parent's JSON, under _inlines,
            # where a file cannot: an inline shows its files, and a
            # file is chosen on the row's own form.
            if self.read_only or configuration.get("type") in FILE_TYPES:
                configuration["readOnly"] = True

            result.append(remove_none_values(configuration))

        result.sort(key=lambda item: item.get("position", 0))

        return result

    def get_schema(self, request: Any = None) -> dict[str, Any]:
        editable = not self.read_only

        return remove_none_values(
            {
                "name": self.name,
                "title": str(self.title),
                "description": str(self.description),
                "verboseName": str(self.verbose_name or self.title),
                "presentation": self.presentation,
                "tab": self.tab,
                "collapsed": self.collapsed,
                "readOnly": self.read_only,
                "position": self.position,
                "primaryKey": self.primary_key,
                "parentField": self.parent_field,
                "extra": self.extra if editable and self.can_add else 0,
                "minRows": self.min_rows,
                "maxRows": self.max_rows,
                "canAdd": editable and self.can_add,
                "canChange": editable and self.can_change,
                "canDelete": editable and self.can_delete,
                "addLabel": str(self.add_label),
                "deleteLabel": str(self.delete_label),
                "fields": self.get_form_fields(request=request),
            }
        )


class InlineProcessor:
    """Validate and apply an inline payload.

    Kept out of the viewset so the rules can be exercised directly,
    without going through HTTP.
    """

    def __init__(
        self,
        definitions: Iterable[InlineFormDefinition],
        *,
        context: dict[str, Any] | None = None,
        payload_key: str = INLINE_PAYLOAD_KEY,
    ) -> None:
        self.definitions = tuple(definitions)
        self.context = context or {}
        self.payload_key = payload_key

    # -- lookup -------------------------------------------------------

    @property
    def definitions_by_name(self) -> dict[str, InlineFormDefinition]:
        return {definition.name: definition for definition in self.definitions}

    def get_definition(self, name: str) -> InlineFormDefinition:
        definition = self.definitions_by_name.get(name)

        if definition is None:
            raise ValidationError(
                {self.payload_key: {name: [_("Unknown inline.")]}}
            )

        return definition

    def get_serializer_context(
        self,
        definition: InlineFormDefinition,
    ) -> dict[str, Any]:
        return self.context

    def get_queryset(
        self,
        definition: InlineFormDefinition,
        parent: Any,
    ) -> QuerySet:
        return definition.get_queryset(parent)

    def fail(self, errors: dict[str, Any]) -> None:
        raise ValidationError({self.payload_key: errors})

    # -- read ---------------------------------------------------------

    def serialize(self, parent: Any) -> dict[str, Any]:
        result = {}

        for definition in self.definitions:
            serializer = definition.serializer_class(
                self.get_queryset(definition, parent),
                many=True,
                context=self.get_serializer_context(definition),
            )
            result[definition.name] = serializer.data

        return result

    def get_schemas(self, request: Any = None) -> list[dict[str, Any]]:
        ordered = sorted(
            self.definitions,
            key=lambda definition: (
                definition.position,
                definition.name,
            ),
        )

        return [
            definition.get_schema(request=request) for definition in ordered
        ]

    # -- phase 1: parse -----------------------------------------------

    def parse(
        self,
        *,
        parent: Any,
        inline_data: dict[str, Any],
    ) -> dict[str, ParsedCollection]:
        """Structural checks, before anything is written."""
        parsed: dict[str, ParsedCollection] = {}
        errors: dict[str, Any] = {}

        known = set(self.definitions_by_name)

        for unknown in sorted(set(inline_data) - known):
            errors[unknown] = {COLLECTION_ERRORS_KEY: [_("Unknown inline.")]}

        for definition in self.definitions:
            if definition.name not in inline_data:
                continue

            rows = inline_data[definition.name]

            if not isinstance(rows, list):
                errors[definition.name] = {
                    COLLECTION_ERRORS_KEY: [_("A list of rows is expected.")]
                }
                continue

            if definition.read_only and rows:
                errors[definition.name] = {
                    COLLECTION_ERRORS_KEY: [
                        _("These rows cannot be changed here.")
                    ]
                }
                continue

            collection_errors, collection = self.parse_rows(
                definition=definition,
                parent=parent,
                rows=rows,
            )

            if collection_errors:
                errors[definition.name] = collection_errors
            else:
                parsed[definition.name] = collection

        if errors:
            self.fail(errors)

        return parsed

    def parse_rows(
        self,
        *,
        definition: InlineFormDefinition,
        parent: Any,
        rows: list[Any],
    ) -> tuple[dict[str, Any], ParsedCollection]:
        errors: dict[str, Any] = {}
        collection = ParsedCollection()

        # Existing rows are looked up once, among the rows that actually
        # belong to this parent: that is what stops a crafted primary
        # key from reaching somebody else's row.
        current: dict[str, Any] = {}

        if parent is not None:
            current = {
                str(getattr(item, definition.primary_key)): item
                for item in self.get_queryset(definition, parent)
            }

        for index, raw_row in enumerate(rows):
            row_key = str(index)

            if not isinstance(raw_row, dict):
                errors[row_key] = {
                    COLLECTION_ERRORS_KEY: [_("A JSON object is expected.")]
                }
                continue

            row = dict(raw_row)
            primary_key = row.pop(definition.primary_key, None)
            delete_requested = bool(row.pop(DELETE_FLAG, False))

            instance = None

            if primary_key not in (None, ""):
                instance = current.get(str(primary_key))

                if instance is None:
                    errors[row_key] = {
                        definition.primary_key: [
                            _(
                                "Row not found, or not attached to "
                                "this record."
                            )
                        ]
                    }
                    continue

            if delete_requested:
                # Deleting a row that was never saved is a no-op.
                if instance is None:
                    continue

                if not definition.can_delete:
                    errors[row_key] = {
                        DELETE_FLAG: [_("Deletion is not allowed.")]
                    }
                    continue

                collection.deletions.append(instance)
                continue

            if instance is None and not definition.can_add:
                errors[row_key] = {
                    COLLECTION_ERRORS_KEY: [_("Adding rows is not allowed.")]
                }
                continue

            if instance is not None and not definition.can_change:
                errors[row_key] = {
                    COLLECTION_ERRORS_KEY: [
                        _("Existing rows cannot be changed.")
                    ]
                }
                continue

            collection.writes.append(
                PendingRow(key=row_key, data=row, instance=instance)
            )

        count_errors = self.validate_row_count(
            definition,
            self.retained_count(
                definition,
                current,
                collection,
            ),
        )

        if count_errors:
            errors.setdefault(COLLECTION_ERRORS_KEY, []).extend(count_errors)

        return errors, collection

    @staticmethod
    def retained_count(
        definition: InlineFormDefinition,
        current: dict[str, Any],
        collection: ParsedCollection,
    ) -> int:
        """Rows attached to the parent once this payload is applied.

        A client only sends the rows it changed, so the count starts
        from what exists, adds the new rows and takes off the deleted
        ones.
        """
        added = sum(1 for row in collection.writes if row.instance is None)

        return len(current) + added - len(collection.deletions)

    @staticmethod
    def validate_row_count(
        definition: InlineFormDefinition,
        retained: int,
    ) -> list[Any]:
        errors: list[Any] = []

        if retained < definition.min_rows:
            errors.append(
                _("At least %(count)s row(s) are required.")
                % {"count": definition.min_rows}
            )

        if definition.max_rows is not None and retained > definition.max_rows:
            errors.append(
                _("At most %(count)s row(s) are allowed.")
                % {"count": definition.max_rows}
            )

        return errors

    # -- phase 3: validate --------------------------------------------

    def build_row_serializer(
        self,
        definition: InlineFormDefinition,
        row: PendingRow,
        parent: Any,
    ) -> serializers.Serializer:
        """Build the serializer validating one row.

        The parent link is never taken from the payload: whatever the
        client sent is overwritten with the real parent, so a crafted
        request cannot reparent a row. Supplying it rather than dropping
        it also keeps DRF's unique-together validator working, since a
        constraint spanning the parent cannot be checked without it.
        """
        data = dict(row.data)

        if parent is None:
            data.pop(definition.parent_field, None)
        else:
            data[definition.parent_field] = parent.pk

        serializer = definition.serializer_class(
            row.instance,
            data=data,
            partial=row.instance is not None,
            context=self.get_serializer_context(definition),
        )

        parent_field = serializer.fields.get(definition.parent_field)

        if parent_field is not None and parent is None:
            parent_field.required = False

        return serializer

    def validate_writes(
        self,
        *,
        parent: Any,
        parsed: dict[str, ParsedCollection],
    ) -> dict[str, list[InlineOperation]]:
        prepared: dict[str, list[InlineOperation]] = {}
        errors: dict[str, Any] = {}
        definitions = self.definitions_by_name

        for name, collection in parsed.items():
            definition = definitions[name]
            row_errors: dict[str, Any] = {}
            operations: list[InlineOperation] = []

            for row in collection.writes:
                serializer = self.build_row_serializer(
                    definition,
                    row,
                    parent,
                )

                if not serializer.is_valid():
                    row_errors[row.key] = serializer.errors
                    continue

                operations.append(
                    InlineOperation(
                        operation=row.operation,
                        instance=row.instance,
                        serializer=serializer,
                    )
                )

            if row_errors:
                errors[name] = row_errors
            else:
                prepared[name] = operations

        if errors:
            self.fail(errors)

        return prepared

    # -- orchestration ------------------------------------------------

    def apply(
        self,
        *,
        parent: Any,
        inline_data: dict[str, Any],
    ) -> None:
        """Run the whole payload against ``parent``.

        Must be called inside a transaction: phase 2 writes before phase
        3 has had its say, and only a rollback can undo that.
        """
        parsed = self.parse(parent=parent, inline_data=inline_data)

        self.delete(parsed)

        prepared = self.validate_writes(parent=parent, parsed=parsed)

        self.save(parent, prepared)

    def delete(self, parsed: dict[str, ParsedCollection]) -> None:
        for collection in parsed.values():
            for instance in collection.deletions:
                instance.delete()

    def save(
        self,
        parent: Any,
        prepared: dict[str, list[InlineOperation]],
    ) -> None:
        definitions = self.definitions_by_name

        for name, operations in prepared.items():
            definition = definitions[name]

            for operation in operations:
                assert operation.serializer is not None
                operation.serializer.save(**{definition.parent_field: parent})
