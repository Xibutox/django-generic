"""Users, groups and permissions, as ordinary screens.

What the Django admin keeps under *Authentication and Authorization*,
declared the way everything else here is declared - so an application
built on the framework does not have to send its administrators to
``/admin/`` for the one job that decides what everybody else can do.

Three resources, and the third is the reason the first two are usable:
a permission is a row like any other, so the groups and the accounts
that point at it get the same autocomplete as any other relation
instead of a list of four hundred checkboxes.

The user model is whatever ``AUTH_USER_MODEL`` says, and that model may
have none of ``username``, ``first_name`` or ``is_staff``. Nothing here
is declared against fields that might not exist: the columns, the
fieldsets and the search are worked out from the model in
:func:`register_screens`, and what is not there is simply not offered.

The rules about who may grant what live in :mod:`generic.accounts.guard`.
"""

from __future__ import annotations

from typing import Any, Sequence

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import transaction
from django.db.models import Count
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from generic.accounts import guard
from generic.conf import generic_settings
from generic.sites import ModelResource, RelatedTable, action, display, site

#: The group these screens sit in, in the navigation.
GROUP = _("People")


def has(model: Any, *names: str) -> bool:
    """Whether the model carries every one of these fields."""
    known = {field.name for field in model._meta.get_fields()}

    return all(name in known for name in names)


def present(model: Any, names: Sequence[str]) -> tuple[str, ...]:
    """Those of ``names`` the model actually has, in order."""
    known = {field.name for field in model._meta.get_fields()}

    return tuple(name for name in names if name in known)


class UserResource(ModelResource):
    """One account: who it is, whether it works, and what it may do."""

    icon = "person"
    group = GROUP
    order = 0
    description = _("Who may sign in, and what each of them may do.")

    list_display_links = ("__str__",)
    ordering = ("-is_active", "pk")
    list_prefetch_related = ("groups",)
    actions = ("activate", "deactivate", "delete_selected")

    # A password hash is not a version of anything, and a history of
    # them would be a list of hashes to attack offline. The last sign-in
    # is left out for a duller reason: it changes on every sign-in, and
    # would write a version of the account each time.
    history_exclude = ("password", "last_login")

    # Written, never read back. The record's own endpoint returns every
    # other field, and this one would hand out the hash to anyone who
    # may open the form.
    form_field_kwargs = {
        "password": {
            "write_only": True,
            "required": False,
            "allow_blank": True,
        }
    }
    form_overrides = {
        "password": {
            "widget": "password",
            "label": _("New password"),
            "helpText": _(
                "Leave it empty to keep the current one. On a new "
                "account, leave it empty for somebody who signs in "
                "through the directory."
            ),
        },
        "user_permissions": {
            "helpText": _(
                "On top of what their groups already allow. Prefer a "
                "group: it is one place to change when the job changes."
            ),
        },
    }

    # -- who may do this ----------------------------------------------

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return super().has_change_permission(
            request, obj
        ) and guard.may_manage(request, obj)

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return super().has_delete_permission(
            request, obj
        ) and guard.may_manage(request, obj)

    def delete_model(self, request: Any, obj: Any) -> None:
        """The one place both the button and the bulk action go through.

        Raising here stops the whole bulk action inside its transaction,
        so a selection holding one account nobody may delete deletes
        none of them.
        """
        if obj.pk == getattr(request.user, "pk", None):
            raise PermissionDenied(
                gettext("You cannot delete the account you are signed in as.")
            )

        if not guard.may_manage(request, obj):
            raise PermissionDenied(
                gettext("Only a superuser can delete a superuser.")
            )

        super().delete_model(request, obj)

    # -- writing ------------------------------------------------------

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        """Check what is being granted, then hash what was typed.

        The password never reaches the database as it was typed: it is
        taken out of the validated data, checked against the project's
        password validators, and written through ``set_password``.
        """
        guard.check_user(request, serializer)

        password = str(serializer.validated_data.pop("password", "") or "")
        password = password.strip()

        if password:
            self.check_password_quality(serializer, password)

        with transaction.atomic():
            user = serializer.save()

            if password:
                user.set_password(password)
                user.save(update_fields=["password"])
            elif not change:
                # Created without one: the account exists, and signing
                # in happens somewhere else. An empty hash would be a
                # password nobody chose.
                user.set_unusable_password()
                user.save(update_fields=["password"])

        return user

    def check_password_quality(self, serializer: Any, password: str) -> None:
        """The project's own password validators, before anything is
        written - including the one that compares a password with the
        name and address of the account it is for."""
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        candidate = serializer.instance

        if candidate is None:
            columns = {
                field.name for field in self.model._meta.concrete_fields
            }
            candidate = self.model(
                **{
                    name: value
                    for name, value in serializer.validated_data.items()
                    if name in columns
                }
            )

        try:
            validate_password(password, candidate)
        except ValidationError as error:
            raise serializers.ValidationError(
                {"password": list(error.messages)}
            ) from error

    # -- columns ------------------------------------------------------

    @display(description=_("Name"), ordering="last_name")
    def full_name(self, user: Any) -> str:
        getter = getattr(user, "get_full_name", None)

        return (getter() if callable(getter) else "") or ""

    # -- actions ------------------------------------------------------

    @action(
        description=_("Activate"),
        icon="check_circle",
        permissions=("change",),
    )
    def activate(self, request: Any, queryset: Any) -> str:
        return self.set_active(request, queryset, True)

    @action(
        description=_("Deactivate"),
        icon="do_not_disturb_on",
        permissions=("change",),
        variant="danger",
        confirm=_("Deactivate the selected accounts? They cannot sign in."),
    )
    def deactivate(self, request: Any, queryset: Any) -> str:
        return self.set_active(request, queryset, False)

    def set_active(self, request: Any, queryset: Any, value: bool) -> str:
        """Turn accounts on or off, one save each.

        One save each rather than ``update()``: the change is announced,
        recorded and watched like any other, which for an account being
        switched off is the whole point.
        """
        changed = 0
        skipped = 0

        for user in queryset:
            if user.is_active == value:
                continue

            # The rules of the form, again: a bulk action is not a way
            # around them.
            if not value and (
                user.pk == request.user.pk
                or not guard.may_manage(request, user)
            ):
                skipped += 1
                continue

            user.is_active = value
            user.save(update_fields=["is_active"])
            changed += 1

        if skipped:
            return gettext(
                "%(count)s changed. %(skipped)s left alone: your own "
                "account, or one you may not manage."
            ) % {"count": changed, "skipped": skipped}

        return gettext("%(count)s changed.") % {"count": changed}


class GroupResource(ModelResource):
    """A job, and what it is allowed to do."""

    icon = "groups"
    group = GROUP
    order = 1
    description = _("What a job is allowed to do, in one place.")

    list_display = ("name", "member_count", "permission_count")
    list_display_links = ("name",)
    search_fields = ("name",)
    ordering = ("name",)
    fieldsets = ((None, {"fields": ("name", "permissions")}),)
    form_overrides = {
        "permissions": {
            "helpText": _(
                "Everyone in this group gets these, and loses them "
                "when they leave it."
            ),
        }
    }

    def get_list_queryset(self, request: Any) -> Any:
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                member_count=Count(
                    get_user_model()._meta.model_name,
                    distinct=True,
                ),
                permission_count=Count("permissions", distinct=True),
            )
        )

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        guard.check_group(request, serializer)

        return super().save_model(request, serializer, change)

    @display(description=_("Members"), ordering="member_count")
    def member_count(self, group: Group) -> int:
        return getattr(group, "member_count", 0)

    @display(description=_("Permissions"), ordering="permission_count")
    def permission_count(self, group: Group) -> int:
        return getattr(group, "permission_count", 0)


class PermissionResource(ModelResource):
    """What the application knows how to allow.

    Read-only, because these are not written by hand: Django creates
    four per model when it migrates, and a project adds its own in a
    model's ``Meta.permissions``. Inventing one here would make a row
    that nothing ever checks.
    """

    icon = "key"
    group = GROUP
    order = 2
    description = _("Every permission the application declares.")

    list_display = ("name", "content_type", "codename")
    list_display_links = ("name",)
    search_fields = ("name", "codename")
    ordering = ("content_type__app_label", "content_type__model", "codename")
    list_select_related = ("content_type",)
    actions = ()

    history = False
    watchable = False

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False


def user_options() -> dict[str, Any]:
    """The declarations that depend on what the user model has."""
    model = get_user_model()
    username = getattr(model, "USERNAME_FIELD", "username")
    named = has(model, "first_name", "last_name")

    columns = [
        username,
        "full_name" if named else None,
        getattr(model, "EMAIL_FIELD", "email"),
        "is_active",
        "is_staff",
        "is_superuser",
        "groups",
        "last_login",
    ]
    identity = present(
        model,
        (username, "password", "first_name", "last_name", "email"),
    )
    access = present(model, ("is_active", "is_staff", "is_superuser"))
    belonging = present(model, ("groups", "user_permissions"))
    dates = present(model, ("last_login", "date_joined"))

    fieldsets: list[Any] = [(None, {"fields": identity})]

    if access:
        fieldsets.append(
            (
                _("Access"),
                {
                    "fields": access,
                    "description": _(
                        "An inactive account cannot sign in at all, "
                        "whatever else it is allowed."
                    ),
                },
            )
        )

    if belonging:
        fieldsets.append((_("Groups and permissions"), {"fields": belonging}))

    if dates:
        fieldsets.append((_("Dates"), {"fields": dates, "classes": ("tab",)}))

    options: dict[str, Any] = {
        "list_display": tuple(
            name
            for name in columns
            if name == "full_name" or (name and has(model, name))
        ),
        "list_display_links": (
            username if has(model, username) else "__str__",
        ),
        "search_fields": present(
            model,
            (username, "first_name", "last_name", "email"),
        ),
        "fieldsets": tuple(fieldsets),
        "readonly_fields": dates,
        "detail_stats": access,
    }

    # What this person has changed, on their own page. Only where the
    # history is kept at all - the tab would have no table otherwise.
    if generic_settings.HISTORY:
        options["related_tables"] = (
            RelatedTable("generic_history_entries", title=_("Changes")),
        )

    return options


def group_options() -> dict[str, Any]:
    """A group's members, where the user model has any."""
    model = get_user_model()

    if not has(model, "groups"):
        return {"list_display": ("name", "permission_count")}

    # The reverse relation as the model registry names it, which is
    # the related query name rather than the accessor: a related table
    # is resolved through ``_meta.get_field``.
    reverse = model._meta.get_field("groups").remote_field.name

    return {
        "related_tables": (
            RelatedTable(reverse, title=model._meta.verbose_name_plural),
        )
    }


def register_screens() -> None:
    """Put the people screens on the site.

    Called from ``GenericConfig.ready()`` after every app's
    ``resources.py``, so a project that declares its own user screens
    keeps them and this adds nothing.
    """
    if not generic_settings.SHOW_PEOPLE:
        return

    model = get_user_model()

    if not site.is_registered(model):
        site.register(model, UserResource, **user_options())

    if not site.is_registered(Group):
        site.register(Group, GroupResource, **group_options())

    if not site.is_registered(Permission):
        site.register(Permission, PermissionResource)
