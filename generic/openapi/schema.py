"""What the generated endpoints are, told to drf-spectacular.

A resource's endpoint is one viewset answering many actions - a
DataTables list, a form, a summary, charts, exports - most of which a
plain inspection cannot see: their answers are built by hand, not by a
serializer. This says what each one takes and gives.
"""

from __future__ import annotations

from typing import Any

from django.db import models
from drf_spectacular.extensions import (
    OpenApiAuthenticationExtension,
    OpenApiSerializerFieldExtension,
)
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import (
    build_array_type,
    build_basic_type,
    build_bearer_security_scheme_object,
    build_object_type,
)
from drf_spectacular.settings import spectacular_settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, inline_serializer
from rest_framework import serializers

#: Answers built by hand: JSON objects the page reads.
OBJECT_ACTIONS = frozenset(
    {
        "summary",
        "history",
        "chart",
        "facets",
        "form_schema",
        "deletion_preview",
        "autocomplete",
        "run_action",
        "cells",
        "rows",
        "import_schema",
        "import_rows",
        "list_transitions",
        "take_transition",
    }
)

#: Answers that are files.
FILE_ACTIONS = frozenset(
    {"export", "export_csv", "import_template", "download_file"}
)

#: Actions reading the table: they take its filters and search.
TABLE_ACTIONS = frozenset(
    {"list", "export", "export_csv", "chart", "facets", "run_action"}
)

STRING = OpenApiTypes.STR
INTEGER = OpenApiTypes.INT


def query(name: str, kind: Any, description: str) -> OpenApiParameter:
    return OpenApiParameter(
        name=name,
        type=kind,
        location=OpenApiParameter.QUERY,
        required=False,
        description=description,
    )


FILTER_PARAMETERS = [
    query(
        "filters",
        STRING,
        'A filter tree, as JSON: {"match": "all"|"any", "conditions": '
        '[{"column", "operator", "value"} or a nested group]}. Columns are '
        "the public names the list returns; operators per type: text "
        "contains, equals, starts_with, ends_with (and not_...); numbers "
        "equals, gt, gte, lt, lte, between; dates on, before, after, "
        "between, today, this_month, last_days, older_than_days...; "
        "booleans is_true, is_false; choices and relations any_of, "
        "none_of, all_of; every type empty, not_empty.",
    ),
    query(
        "search",
        STRING,
        'Words every row must contain; -word excludes, "a phrase" stays '
        "whole. Also accepted as search[value].",
    ),
    query(
        "_related",
        STRING,
        "<app>.<model>.<related table>:<pk>: the rows of a record's "
        "related table.",
    ),
]

LIST_PARAMETERS = [
    query(
        "ordering",
        STRING,
        "Columns to order by, comma separated, - for descending: "
        "-due_on,reference.",
    ),
    *FILTER_PARAMETERS,
]

EXPORT_PARAMETERS = [
    query("columns", STRING, "The columns to export, comma separated."),
    query("ordering", STRING, "As for the list."),
    *FILTER_PARAMETERS,
]


#: What ``import/`` takes: a file, its columns matched, and whether to
#: write or only look.
IMPORT_UPLOAD = inline_serializer(
    name="ImportUpload",
    fields={
        "file": serializers.FileField(),
        "mapping": serializers.CharField(
            required=False,
            help_text="JSON: one column name, or null, per header.",
        ),
        "commit": serializers.BooleanField(required=False),
    },
)


#: What the wiki's image upload takes: one image.
WIKI_IMAGE_UPLOAD = inline_serializer(
    name="WikiImageUpload",
    fields={
        "file": serializers.FileField(
            help_text="A PNG, JPEG, GIF or WebP image, up to "
            "GENERIC['FILE_MAX_SIZE'] bytes."
        ),
    },
)

#: Bodies of hand-built views, by the ``openapi_request`` they name.
REQUESTS = {"wiki_image_upload": WIKI_IMAGE_UPLOAD}


class ResourceAutoSchema(AutoSchema):
    """drf-spectacular's inspector, for the framework's endpoints."""

    @property
    def action(self) -> str:
        return getattr(self.view, "action", None) or ""

    def is_excluded(self) -> bool:
        # The download of a record's files is every resource's action;
        # only a model that has files has anything to download.
        if self.action == "download_file":
            model = getattr(
                getattr(self.view, "resource", None), "model", None
            )

            return model is None or not any(
                isinstance(field, models.FileField)
                for field in model._meta.fields
            )

        return super().is_excluded()

    def get_tags(self) -> list[str]:
        resource = getattr(self.view, "resource", None)

        if resource is not None and hasattr(resource, "get_label_plural"):
            return [str(resource.get_label_plural()).capitalize()]

        return super().get_tags()

    def get_request_serializer(self) -> Any:
        action = self.action
        declared = REQUESTS.get(getattr(self.view, "openapi_request", ""))

        if declared is not None:
            return declared

        if action in ("run_action", "cells", "rows", "take_transition"):
            return OpenApiTypes.OBJECT

        if action == "import_rows":
            return IMPORT_UPLOAD

        if action in OBJECT_ACTIONS or action in FILE_ACTIONS:
            return None

        if not self._is_table():
            return (
                OpenApiTypes.OBJECT
                if self.method in ("POST", "PUT", "PATCH")
                else None
            )

        return super().get_request_serializer()

    def get_response_serializers(self) -> Any:
        action = self.action

        if action in FILE_ACTIONS:
            return OpenApiTypes.BINARY

        if action in OBJECT_ACTIONS:
            return OpenApiTypes.OBJECT

        # A view answering JSON it builds itself - an autocomplete, the
        # palette's search: an object, described in its docstring.
        if not self._is_table():
            return OpenApiTypes.OBJECT

        return super().get_response_serializers()

    def get_override_parameters(self) -> list[Any]:
        action = self.action
        parameters = list(super().get_override_parameters())

        if action == "list" and self._is_table():
            parameters += LIST_PARAMETERS
        elif action in ("export", "export_csv"):
            parameters += EXPORT_PARAMETERS
        elif action in TABLE_ACTIONS:
            parameters += FILTER_PARAMETERS

        if action == "chart":
            parameters.append(
                query("period", STRING, "day, week, month, quarter or year.")
            )
        elif action == "facets":
            parameters += [
                query("column", STRING, "The column whose values to list."),
                query("q", STRING, "Only values whose label contains it."),
                query("ids", STRING, "Label these values, comma separated."),
            ]
        elif action == "autocomplete":
            parameters += [
                query("q", STRING, "Records matching it."),
                query("page", INTEGER, "The page of results, from 1."),
                query("ids", STRING, "Label these records, comma separated."),
            ]

        return parameters

    def get_serializer_name(self, serializer: Any, direction: str) -> str:
        """Generated serializers named after their app as well.

        ``AgentTableSerializer`` is generated for every registered Agent
        model, and a project may write one of that name itself: the
        app keeps the components apart.
        """
        name = super().get_serializer_name(serializer, direction)
        module = type(serializer).__module__

        if module.startswith("generic.sites") or module.startswith(
            "generic.api"
        ):
            model = getattr(getattr(serializer, "Meta", None), "model", None)

            if model is not None:
                label = model._meta.app_label.title().replace("_", "")

                return f"{label}{name}"

        return name

    def get_filter_backends(self) -> list[Any]:
        # The filter backends read DataTables parameters, described
        # above; left to themselves they would describe nothing useful.
        return []

    def _is_table(self) -> bool:
        return hasattr(self.view, "get_serializer_class")

    def _map_serializer_field(
        self,
        field: Any,
        direction: str,
        bypass_extensions: bool = False,
    ) -> Any:
        # The hidden row key and links of a table: text, whatever the
        # key is made of.
        if isinstance(field, serializers.ReadOnlyField) and str(
            field.field_name
        ).startswith("_"):
            return build_basic_type(STRING)

        # Choices that are not plain values - time zones, enums of a
        # library - travel as their text.
        if isinstance(field, serializers.ChoiceField) and not all(
            choice is None or isinstance(choice, (str, int, float, bool))
            for choice in field.choices
        ):
            return build_basic_type(STRING)

        return super()._map_serializer_field(
            field, direction, bypass_extensions
        )


class TagsColumnExtension(OpenApiSerializerFieldExtension):
    """A tags column: a list of ``{label, id, color, background, ...}``."""

    target_class = "generic.api.columns.TagsColumn"
    match_subclasses = True

    def map_serializer_field(self, auto_schema: Any, direction: str) -> Any:
        tag = build_object_type(
            properties={
                "label": build_basic_type(STRING),
                "value": build_basic_type(OpenApiTypes.ANY),
                "id": build_basic_type(OpenApiTypes.ANY),
                "color": build_basic_type(STRING),
                "background": build_basic_type(STRING),
                "title": build_basic_type(STRING),
            }
        )

        return build_array_type(tag)


def stored_file_object() -> Any:
    """``{"name", "url", "size"}``: a stored file, as it is read."""
    described = build_object_type(
        properties={
            "name": build_basic_type(STRING),
            "url": {**build_basic_type(STRING), "nullable": True},
            "size": {**build_basic_type(INTEGER), "nullable": True},
        },
        description="The file's name, where it is downloaded (the "
        "record's files/<field>/ endpoint) and its size in bytes.",
    )
    described["nullable"] = True

    return described


class FormFileFieldExtension(OpenApiSerializerFieldExtension):
    """A form's file: read as an object, written as a multipart part."""

    target_class = "generic.api.files.FormFileField"
    match_subclasses = True

    def map_serializer_field(self, auto_schema: Any, direction: str) -> Any:
        # drf-spectacular's own rule for a file field: the upload is
        # only described where requests have components of their own.
        if (
            direction == "request"
            and spectacular_settings.COMPONENT_SPLIT_REQUEST
        ):
            written = build_basic_type(OpenApiTypes.BINARY)
            written["nullable"] = True
            written["description"] = (
                "A file part; null removes the current file, where the "
                "field may be empty."
            )

            return written

        return stored_file_object()


class FileColumnExtension(OpenApiSerializerFieldExtension):
    """A table's file cell: the same object, its size left out."""

    target_class = "generic.api.columns.FileColumn"
    match_subclasses = True

    def map_serializer_field(self, auto_schema: Any, direction: str) -> Any:
        return stored_file_object()


class ManyRelatedColumnExtension(OpenApiSerializerFieldExtension):
    """Related labels, comma separated."""

    target_class = "generic.api.columns.ManyRelatedColumn"
    match_subclasses = True

    def map_serializer_field(self, auto_schema: Any, direction: str) -> Any:
        return build_basic_type(STRING)


class TokenScheme(OpenApiAuthenticationExtension):
    """``Authorization: Token <token>`` (generic.tokens)."""

    target_class = "generic.tokens.authentication.TokenAuthentication"
    name = "tokenAuth"

    def get_security_definition(self, auto_schema: Any) -> Any:
        return build_bearer_security_scheme_object(
            header_name="Authorization", token_prefix="Token"
        )
