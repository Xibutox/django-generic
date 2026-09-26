"""Form schema: DRF stays the source of truth, overrides only decorate."""

from __future__ import annotations

import pytest

from generic.api.forms import FormModelSerializer
from tests.testapp.models import Book
from tests.testapp.serializers import BookFormSerializer

pytestmark = pytest.mark.django_db

SCHEMA_URL = "/api/book-forms/form-schema/"


def fields_by_name(schema: dict) -> dict:
    return {field["name"]: field for field in schema["fields"]}


@pytest.fixture
def schema(api_client, db) -> dict:
    response = api_client.get(SCHEMA_URL)

    assert response.status_code == 200

    return response.data


class TestSchemaShape:
    def test_the_schema_carries_sections_fields_and_inlines(
        self,
        schema,
    ):
        assert set(schema) >= {
            "version",
            "sections",
            "fields",
            "inlines",
            "mode",
            "title",
            "submitLabel",
        }

    def test_sections_are_ordered_by_position(self, schema):
        names = [section["name"] for section in schema["sections"]]

        assert names == ["general", "commercial"]

    def test_mode_selects_the_labels(self, api_client, db):
        create = api_client.get(SCHEMA_URL, {"mode": "create"}).data
        delete = api_client.get(SCHEMA_URL, {"mode": "delete"}).data

        assert create["mode"] == "create"
        assert create["submitLabel"] != delete["submitLabel"]

    def test_an_unknown_mode_falls_back_to_update(self, api_client, db):
        response = api_client.get(SCHEMA_URL, {"mode": "sudo"})

        assert response.data["mode"] == "update"


class TestFieldMetadata:
    def test_types_are_inferred_from_the_serializer(self, schema):
        fields = fields_by_name(schema)

        assert fields["title"]["type"] == "text"
        assert fields["pages"]["type"] == "integer"
        assert fields["price"]["type"] == "decimal"
        assert fields["is_available"]["type"] == "boolean"
        assert fields["genre"]["type"] == "select"
        assert fields["author"]["type"] == "select"

    def test_a_relation_is_flagged(self, schema):
        fields = fields_by_name(schema)

        assert fields["author"]["relation"] is True
        assert fields["title"]["relation"] is False

    def test_required_comes_from_drf(self, schema):
        fields = fields_by_name(schema)

        assert fields["title"]["required"] is True
        # publisher is null=True, blank=True on the model.
        assert fields["publisher"]["required"] is False

    def test_the_primary_key_is_read_only(self, schema):
        assert fields_by_name(schema)["id"]["readOnly"] is True

    def test_choices_are_exposed(self, schema):
        choices = fields_by_name(schema)["genre"]["choices"]
        values = [choice["value"] for choice in choices]

        assert set(values) >= {"fiction", "essay", "poetry"}

    def test_limits_come_from_the_model(self, schema):
        assert fields_by_name(schema)["title"]["maxLength"] == 200


class TestOverrides:
    def test_presentation_overrides_are_applied(self, schema):
        title = fields_by_name(schema)["title"]

        assert title["placeholder"] == "Book title"

    def test_fields_are_assigned_to_their_section(self, schema):
        fields = fields_by_name(schema)

        assert fields["price"]["section"] == "commercial"
        assert fields["title"]["section"] == "general"

    def test_fields_are_ordered_by_position(self, schema):
        general = [
            field["name"]
            for field in schema["fields"]
            if field["section"] == "general"
        ]

        assert general.index("title") < general.index("author")

    def test_a_disabled_field_is_dropped(self, db):
        class Serializer(BookFormSerializer):
            form_overrides = {"pages": {"enabled": False}}

        names = {field["name"] for field in Serializer.get_form_fields()}

        assert "pages" not in names

    def test_overrides_merge_along_the_mro(self, db):
        class Serializer(BookFormSerializer):
            form_overrides = {"title": {"label": "Renamed"}}

        merged = Serializer.get_merged_form_overrides()

        # The subclass adds a label without losing the placeholder.
        assert merged["title"]["label"] == "Renamed"
        assert merged["title"]["placeholder"] == "Book title"


class TestSchemaValidation:
    def test_a_field_in_an_undeclared_section_is_caught(self, db):
        class Serializer(FormModelSerializer):
            class Meta:
                model = Book
                fields = ("id", "title")

            form_overrides = {"title": {"section": "nowhere"}}

        with pytest.raises(RuntimeError, match="undeclared sections"):
            Serializer.get_form_schema()

    def test_an_unreversible_related_editor_route_is_caught(self, db):
        class Serializer(FormModelSerializer):
            class Meta:
                model = Book
                fields = ("id", "author")

            form_overrides = {
                "author": {"relatedEditorView": "does-not-exist"}
            }

        with pytest.raises(RuntimeError, match="relatedEditorView"):
            Serializer.get_form_fields()


class TestDefaults:
    def test_a_callable_default_is_not_frozen_into_the_schema(self, db):
        """``now`` must be resolved on save, not at schema build."""
        from rest_framework import serializers

        from generic.api.forms import get_field_default

        field = serializers.DateTimeField(default=lambda: "resolved-later")

        assert get_field_default(field) is None

    def test_an_add_form_opens_on_the_model_defaults(self, schema):
        """DRF keeps a model default to itself; an add form needs it.

        Without this the field opens blank, which says the opposite of
        what the model declares - ``is_available`` defaults to true.
        """
        fields = {field["name"]: field for field in schema["fields"]}

        assert fields["is_available"]["default"] is True
        assert fields["pages"]["default"] == 0

    def test_a_field_without_one_says_nothing(self, schema):
        fields = {field["name"]: field for field in schema["fields"]}

        # Nothing declared, nothing sent: the schema drops empty keys.
        assert "default" not in fields["title"]
