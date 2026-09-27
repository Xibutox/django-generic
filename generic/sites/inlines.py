"""Related rows edited on their parent's form.

Declared the way the admin declares them::

    class CommentInline(TabularInline):
        model = Comment
        fields = ("author", "body", "position")
        extra = 1

    class TicketResource(ModelResource):
        inlines = (CommentInline,)

``TabularInline`` draws one table row per record, ``StackedInline`` one
card per record. Either way the rows travel inside the parent's own API
request, under ``_inlines``, and land in the same transaction.
"""

from __future__ import annotations

from typing import Any, Sequence

from django.contrib.auth import get_permission_codename
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.forms.models import _get_foreign_key
from django.utils.encoding import force_str
from django.utils.translation import gettext

from generic.api.inlines import InlineFormDefinition
from generic.sites.serializers import (
    build_form_serializer,
    default_form_fields,
)


class InlineResource:
    """One collection of related rows on a resource's form."""

    model: Any = None
    #: Columns, or fields of each card. Defaults to every editable field.
    fields: Sequence[str] | None = None
    exclude: Sequence[str] = ()
    readonly_fields: Sequence[str] = ()
    #: The foreign key to the parent, when there are several.
    fk_name: str | None = None

    #: Blank rows offered on a new record.
    extra: int = 0
    min_num: int = 0
    max_num: int | None = None
    can_delete: bool = True

    verbose_name: Any = None
    verbose_name_plural: Any = None
    description: Any = ""
    #: ``("tab",)`` gives the collection a tab of its own;
    #: ``("collapse",)`` starts it folded.
    classes: Sequence[str] = ()
    position: int = 0

    #: ``tabular`` or ``stacked``; set by the two subclasses.
    presentation: str = "tabular"

    #: Presentation per field: width, placeholder, label...
    form_overrides: dict[str, dict[str, Any]] = {}
    #: A hand-written ``FormModelSerializer``, replacing the generated one.
    serializer_class: Any = None

    def __init__(self, parent_model: Any, site: Any) -> None:
        if self.model is None:
            raise ImproperlyConfigured(
                f"{type(self).__name__} must define 'model'."
            )

        self.parent_model = parent_model
        self.site = site
        self.opts = self.model._meta
        self.fk = _get_foreign_key(
            parent_model,
            self.model,
            fk_name=self.fk_name,
        )
        self._serializer_class: Any = None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} for {self.opts.label}>"

    # -- identity ------------------------------------------------------

    @property
    def name(self) -> str:
        """The reverse accessor on the parent, such as ``comments``."""
        return self.fk.remote_field.get_accessor_name()

    def get_verbose_name(self) -> str:
        return force_str(self.verbose_name or self.opts.verbose_name)

    def get_verbose_name_plural(self) -> str:
        return force_str(
            self.verbose_name_plural or self.opts.verbose_name_plural
        ).capitalize()

    # -- fields --------------------------------------------------------

    def get_fields(self) -> list[str]:
        if self.fields is not None:
            return list(self.fields)

        return default_form_fields(
            self.model,
            exclude=[*self.exclude, self.fk.name],
        )

    def get_serializer_class(self) -> Any:
        if self.serializer_class is not None:
            return self.serializer_class

        if self._serializer_class is None:
            fields = self.get_fields()
            # A row travels inside its parent's JSON, where no file can:
            # its files are shown, and chosen on its own form.
            files = [
                name
                for name in fields
                if name not in self.readonly_fields
                and isinstance(self._model_field(name), models.FileField)
            ]

            # The parent link is part of the serializer so a constraint
            # spanning it can be validated; it is supplied on save and
            # left out of the schema.
            self._serializer_class = build_form_serializer(
                self.model,
                fields=[*fields, self.fk.name],
                readonly_fields=[*self.readonly_fields, *files],
                overrides=self.form_overrides,
                source=self,
                name=f"{self.model.__name__}InlineSerializer",
            )

        return self._serializer_class

    def _model_field(self, name: str) -> Any:
        try:
            return self.opts.get_field(name)
        except FieldDoesNotExist:
            return None

    # -- permissions ----------------------------------------------------
    #
    # The admin's rule: an inline answers to its own model's
    # permissions, not to the parent's.

    def _has(self, request: Any, action: str) -> bool:
        user = getattr(request, "user", None)

        if user is None or not user.is_active:
            return False

        codename = get_permission_codename(action, self.opts)

        return bool(user.has_perm(f"{self.opts.app_label}.{codename}"))

    def has_view_permission(self, request: Any, obj: Any = None) -> bool:
        return self._has(request, "view") or self._has(request, "change")

    def has_add_permission(self, request: Any, obj: Any = None) -> bool:
        return self._has(request, "add")

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return self._has(request, "change")

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return self._has(request, "delete")

    def is_visible(self, request: Any, obj: Any = None) -> bool:
        return self.has_view_permission(request, obj) or (
            self.has_add_permission(request, obj)
        )

    # -- definition ----------------------------------------------------

    def get_definition(
        self,
        request: Any,
        obj: Any = None,
    ) -> InlineFormDefinition:
        can_add = self.has_add_permission(request, obj)
        can_change = self.has_change_permission(request, obj)
        can_delete = self.can_delete and self.has_delete_permission(
            request,
            obj,
        )
        verbose_name = self.get_verbose_name()

        return InlineFormDefinition(
            name=self.name,
            serializer_class=self.get_serializer_class(),
            related_name=self.name,
            parent_field=self.fk.name,
            title=self.get_verbose_name_plural(),
            description=force_str(self.description),
            verbose_name=verbose_name,
            primary_key=self.opts.pk.name,
            position=self.position,
            extra=self.extra,
            min_rows=self.min_num,
            max_rows=self.max_num,
            can_add=can_add,
            can_change=can_change,
            can_delete=can_delete,
            read_only=not (can_add or can_change or can_delete),
            presentation=self.presentation,
            tab="tab" in self.classes,
            collapsed="collapse" in self.classes,
            add_label=gettext("Add another %(name)s") % {"name": verbose_name},
            form_overrides={},
        )


class TabularInline(InlineResource):
    """One table row per related record."""

    presentation = "tabular"


class StackedInline(InlineResource):
    """One card per related record, for rows with many fields."""

    presentation = "stacked"
