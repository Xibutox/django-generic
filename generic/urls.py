"""Framework REST routes.

Mount them under whatever prefix suits the project::

    path("api/generic/", include("generic.urls", namespace="generic")),

The pages - dashboard, account, sign in - come with the site instead::

    path("", site.urls),
"""

from django.apps import apps
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from generic.accounts.api import (
    FormSchemaView,
    PreferencesView,
    ProfileView,
    SavedViewViewSet,
)
from generic.accounts.serializers import (
    PreferencesSerializer,
    ProfileSerializer,
)
from generic.events.api import NotificationViewSet
from generic.maintenance.api import (
    RestartAnnouncementView,
    RestartFormSchemaView,
)
from generic.watch.api import WatchViewSet

app_name = "generic"

router = DefaultRouter()
router.register(
    "notifications",
    NotificationViewSet,
    basename="notification",
)
router.register("saved-views", SavedViewViewSet, basename="saved-view")
router.register("watches", WatchViewSet, basename="watch")

# A person's own API tokens, where the project installed them.
if apps.is_installed("generic.tokens"):
    from generic.tokens.api import ApiTokenViewSet

    router.register("tokens", ApiTokenViewSet, basename="api-token")

urlpatterns = [
    path(
        "account/preferences/",
        PreferencesView.as_view(),
        name="preferences",
    ),
    path(
        "account/preferences/form-schema/",
        FormSchemaView.as_view(serializer_class=PreferencesSerializer),
        name="preferences-schema",
    ),
    path("account/profile/", ProfileView.as_view(), name="profile"),
    path(
        "account/profile/form-schema/",
        FormSchemaView.as_view(serializer_class=ProfileSerializer),
        name="profile-schema",
    ),
    # Planned restarts: read by every page, written by whoever holds
    # the announcement's add permission.
    path("restart/", RestartAnnouncementView.as_view(), name="restart"),
    path(
        "restart/form-schema/",
        RestartFormSchemaView.as_view(),
        name="restart-schema",
    ),
    path("", include(router.urls)),
]

# Images and files the wiki's editor uploads into a page, where the
# wiki is installed; they are served from the wiki's own images/<id>/
# and files/<id>/.
if apps.is_installed("generic.wiki"):
    from generic.wiki.api import WikiFileUploadView, WikiImageUploadView

    urlpatterns[:0] = [
        path(
            "wiki/images/",
            WikiImageUploadView.as_view(),
            name="wiki-images",
        ),
        path(
            "wiki/files/",
            WikiFileUploadView.as_view(),
            name="wiki-files",
        ),
    ]

# Word files merged with a template, where generic.docx is installed;
# its page, in generic.docx.urls, sends them here.
if apps.is_installed("generic.docx"):
    from generic.docx.api import DocxMergeView

    urlpatterns[:0] = [
        path("docx/merge/", DocxMergeView.as_view(), name="docx-merge"),
    ]
