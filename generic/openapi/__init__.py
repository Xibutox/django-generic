"""The OpenAPI description of the API, and its pages.

Optional, on drf-spectacular::

    INSTALLED_APPS = [..., "drf_spectacular", "drf_spectacular_sidecar"]
    REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = (
        "drf_spectacular.openapi.AutoSchema"
    )

    # urls.py, before site.urls
    path("api/", include("generic.openapi.urls")),   # api/schema/, api/docs/

Every generated endpoint is described as it really behaves - the list
as the DataTables envelope and its query parameters, the filter tree,
the summary, history, facets, one path per declared chart, the bulk
actions, the exports as files, the import - by
:class:`~generic.openapi.schema.ResourceAutoSchema`, which the
framework's viewsets carry whenever drf-spectacular is installed.

The description is written for its reader: only the endpoints they may
use are listed, so it never reveals a model to someone who may not
open it.
"""

from __future__ import annotations

from typing import Any


def framework_schema() -> Any:
    """The schema inspector the framework's views carry.

    drf-spectacular's, taught what the generated endpoints do, when it
    is installed; DRF's default otherwise, so nothing changes for a
    project without it.
    """
    from django.conf import settings
    from rest_framework.schemas import DefaultSchema

    # Installed as an app, not merely importable: a project describing
    # its API another way keeps DRF's inspector on these views too.
    if "drf_spectacular" not in getattr(settings, "INSTALLED_APPS", ()):
        return DefaultSchema()

    try:
        from generic.openapi.schema import ResourceAutoSchema
    except ImportError:  # pragma: no cover - listed, not installed
        return DefaultSchema()

    return ResourceAutoSchema()
