"""The OpenAPI description: valid, and written for its reader."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from drf_spectacular.validation import validate_schema

from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

SCHEMA = "/api/schema/?format=json"


def paths_for(client) -> dict:
    response = client.get(SCHEMA)

    assert response.status_code == 200, response.content[:300]

    return response.json()


def test_the_description_is_valid_openapi(admin_client):
    validate_schema(paths_for(admin_client))


def test_a_superuser_sees_every_resource(admin_client):
    paths = paths_for(admin_client)["paths"]

    assert "/api/example/ticket/" in paths
    assert "/api/example/customer/import/" in paths
    assert "/api/auth/user/" in paths


def test_a_restricted_reader_sees_only_what_they_may_use(client):
    reader = UserFactory()
    reader.user_permissions.set(
        Permission.objects.filter(codename="view_ticket")
    )
    client.force_login(reader)

    paths = paths_for(client)["paths"]

    assert "/api/example/ticket/" in paths
    assert "/api/example/customer/" not in paths
    assert "/api/auth/user/" not in paths


def test_every_declared_chart_and_the_list_parameters(admin_client):
    from example.models import Ticket
    from generic.sites import site

    schema = paths_for(admin_client)
    paths = schema["paths"]
    resource = site.get_resource(Ticket)

    for chart in resource.get_charts():
        assert f"/api/example/ticket/charts/{chart.name}/" in str(paths) or (
            "/api/example/ticket/charts/{chart}/" in paths
        )

    names = {
        parameter["name"]
        for parameter in paths["/api/example/ticket/"]["get"]["parameters"]
    }
    assert {"draw", "start", "length", "filters", "search"} <= names


def test_the_list_is_the_datatables_envelope(admin_client):
    schema = paths_for(admin_client)
    content = schema["paths"]["/api/example/ticket/"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    reference = content["$ref"].split("/")[-1]
    envelope = schema["components"]["schemas"][reference]

    assert set(envelope["properties"]) == {
        "draw",
        "recordsTotal",
        "recordsFiltered",
        "data",
    }


def test_tokens_are_the_security_scheme(admin_client):
    schema = paths_for(admin_client)

    assert "tokenAuth" in schema["components"]["securitySchemes"]


def test_a_stranger_is_refused(client):
    assert client.get(SCHEMA).status_code in (401, 403)


def test_the_docs_page_serves_its_own_files(admin_client):
    response = admin_client.get("/api/docs/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "drf_spectacular_sidecar/swagger-ui-dist" in body
    assert "cdn.jsdelivr" not in body


def test_the_check_names_a_missing_schema_class(settings):
    from generic.checks import check_openapi

    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK}
    settings.REST_FRAMEWORK.pop("DEFAULT_SCHEMA_CLASS")

    assert [message.id for message in check_openapi()] == ["generic.E008"]
