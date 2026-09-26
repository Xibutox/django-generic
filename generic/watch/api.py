"""The endpoints behind the watch button and the watches page.

Everything is scoped to ``request.user``: no request can read, add or
remove another person's watches. What may be watched is decided by the
resource, with the request in hand - so asking to watch a record is
never a way to find out that it exists.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_permission_codename
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import QuerySet
from django.http import Http404
from django.utils.encoding import force_str
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from generic.watch.models import (
    Watch,
    clean_channels,
    clean_events,
    default_events,
)


class WatchSerializer(serializers.ModelSerializer):
    """One watch, as the page reads and writes it."""

    model = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()
    wholeModel = serializers.BooleanField(  # noqa: N815 - client casing
        source="is_whole_model",
        read_only=True,
    )
    objectId = serializers.CharField(  # noqa: N815 - client casing
        source="object_id",
        read_only=True,
    )
    url = serializers.SerializerMethodField()

    class Meta:
        model = Watch
        fields = (
            "id",
            "model",
            "objectId",
            "label",
            "wholeModel",
            "events",
            "channels",
            "url",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def get_model(self, watch: Watch) -> str:
        return watch.model_label

    def get_label(self, watch: Watch) -> str:
        return str(watch)

    def get_url(self, watch: Watch) -> str:
        """Where the watched thing lives, if the site still shows it."""
        from generic.sites import site

        model = watch.content_type.model_class()
        resource = site.get_resource(model) if model else None

        if resource is None:
            return ""

        if watch.is_whole_model:
            return resource.get_list_url()

        return resource.get_object_url(watch.object_id)

    def validate_events(self, value: Any) -> list[str]:
        whole = not (self.instance and self.instance.object_id)

        return clean_events(value, whole)

    def validate_channels(self, value: Any) -> list[str]:
        return clean_channels(value)


class WatchViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """The user's watches; start and stop one through ``toggle``."""

    serializer_class = WatchSerializer
    #: Read by the API description, which cannot ask get_queryset() -
    #: it has no signed-in user. Every request goes through it anyway.
    queryset = Watch.objects.none()
    permission_classes = (IsAuthenticated,)
    pagination_class = None

    def get_queryset(self) -> QuerySet:
        return Watch.objects.filter(user=self.request.user).select_related(
            "content_type"
        )

    # -- what a request may name ------------------------------------------

    def resolve_target(
        self, request: Any, source: Any
    ) -> tuple[Any, Any, str]:
        """The content type and record a request names, if visible.

        An empty ``objectId`` is the model itself, which is a request
        to hear about every record of it - so it is allowed only where
        the user may view the model at all.
        """
        label = force_str(source.get("model") or "")
        object_id = force_str(
            source.get("objectId") or source.get("object_id") or ""
        )

        try:
            app_label, model_name = label.split(".", 1)
            content_type = ContentType.objects.get_by_natural_key(
                app_label,
                model_name,
            )
        except (ValueError, ContentType.DoesNotExist):
            raise Http404 from None

        model = content_type.model_class()

        if model is None:
            raise Http404

        from generic.sites import site

        resource = site.get_resource(model)

        if resource is not None and not resource.watchable:
            raise PermissionDenied

        if resource is not None:
            queryset = resource.get_queryset(request)
            allowed = resource.has_view_permission(request)
        else:
            queryset = model._default_manager.all()
            codename = get_permission_codename("view", model._meta)
            allowed = request.user.has_perm(
                f"{model._meta.app_label}.{codename}"
            )

        if not allowed:
            raise PermissionDenied

        if not object_id:
            return content_type, None, ""

        obj = queryset.filter(pk=object_id).first()

        if obj is None:
            raise Http404

        return content_type, obj, object_id

    # -- the button --------------------------------------------------------

    @action(
        detail=False, methods=["get"], url_path="status", url_name="status"
    )
    def status(self, request: Any) -> Response:
        """Whether this record - and its model - is watched."""
        content_type, _obj, object_id = self.resolve_target(
            request,
            request.query_params,
        )
        watches = self.get_queryset().filter(content_type=content_type)
        record = (
            watches.filter(object_id=object_id).first() if object_id else None
        )
        whole = watches.filter(object_id="").first()

        return Response(
            {
                "watching": record is not None,
                "id": record.pk if record is not None else None,
                # Worth saying: the record is covered either way, and a
                # button that ignored this would look wrong.
                "wholeModel": whole is not None,
                "wholeModelId": whole.pk if whole is not None else None,
            }
        )

    @action(
        detail=False, methods=["post"], url_path="toggle", url_name="toggle"
    )
    def toggle(self, request: Any) -> Response:
        """Start watching what the request names, or stop."""
        content_type, obj, object_id = self.resolve_target(
            request,
            request.data,
        )
        whole_model = not object_id

        with transaction.atomic():
            watch, created = Watch.objects.get_or_create(
                user=request.user,
                content_type=content_type,
                object_id=object_id,
                defaults={
                    "label": force_str(obj)[:200] if obj is not None else "",
                    "events": clean_events(
                        request.data.get("events"),
                        whole_model,
                    )
                    or default_events(whole_model),
                    "channels": clean_channels(request.data.get("channels")),
                },
            )

            if not created:
                watch.delete()

                return Response({"watching": False, "id": None})

        return Response(
            {"watching": True, "id": watch.pk, **watch.as_client()},
            status=status.HTTP_201_CREATED,
        )
