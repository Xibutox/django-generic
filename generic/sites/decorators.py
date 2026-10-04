"""Decorators for resource methods, in the admin's style.

They only set attributes, the same ones ``django.contrib.admin`` reads
(``short_description``, ``admin_order_field``, ``boolean``), so a method
decorated with ``@admin.display`` works here unchanged.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

Function = Callable[..., Any]


def action(
    function: Function | None = None,
    *,
    description: Any = None,
    permissions: Sequence[str] = ("change",),
    confirm: Any = None,
    icon: str = "",
    variant: str = "default",
    help: Any = None,
) -> Any:
    """Mark a resource method as a bulk action on the table.

    ::

        @action(description=_("Close"), icon="task_alt",
                confirm=_("Close the selected tickets?"))
        def close(self, request, queryset):
            queryset.update(status="closed")
            return _("Closed.")

    ``permissions`` names the model permissions a user needs to see the
    action: ``view``, ``add``, ``change``, ``delete``, or any full
    permission string. The method may return nothing, a message, a
    ``{"message": ..., "level": ...}`` dict, or a DRF ``Response``.
    ``help`` says in a sentence what it does: the tip of its button.
    """

    def decorate(func: Function) -> Function:
        func.is_generic_action = True  # type: ignore[attr-defined]
        func.allowed_permissions = tuple(permissions)  # type: ignore
        func.confirmation = confirm  # type: ignore[attr-defined]
        func.icon = icon  # type: ignore[attr-defined]
        func.variant = variant  # type: ignore[attr-defined]
        func.help_text = help  # type: ignore[attr-defined]

        if description is not None:
            func.short_description = description  # type: ignore[attr-defined]

        return func

    if function is None:
        return decorate

    return decorate(function)


def display(
    function: Function | None = None,
    *,
    description: Any = None,
    ordering: str | None = None,
    boolean: bool | None = None,
    filter_field: str | None = None,
    filter_type: str | None = None,
    search_field: str | None = None,
    tags: Any = None,
    icons: bool = False,
) -> Any:
    """Describe a computed column of ``list_display``.

    ::

        @display(description=_("Age (days)"), ordering="opened_at")
        def age(self, ticket):
            return ticket.age_in_days

        @display(description=_("Flags"), tags=TagStyle(color="color"))
        def flags(self, ticket):
            return ticket.flags.all()

    ``ordering`` makes the column sortable on that ORM path;
    ``filter_field`` gives it a filter control on one. ``tags`` draws
    what the method returns - records, values, or dicts with
    ``label``, ``color`` and ``background`` - as coloured tags: a
    ``TagStyle``, or ``True`` for dicts and plain values. ``icons``
    draws the dicts it returns - ``{"icon", "url", "label"}``, and
    ``"target"`` - as icons one clicks, shortcuts of the row::

        @display(description=_("File"), icons=True)
        def shortcuts(self, ticket):
            return [{"icon": "download", "label": _("Download"),
                     "url": self.get_file_url(ticket.pk, "attachment")}]
    """

    def decorate(func: Function) -> Function:
        if description is not None:
            func.short_description = description  # type: ignore[attr-defined]

        if ordering is not None:
            func.admin_order_field = ordering  # type: ignore[attr-defined]

        if boolean is not None:
            func.boolean = boolean  # type: ignore[attr-defined]

        if filter_field is not None:
            func.filter_field = filter_field  # type: ignore[attr-defined]
            func.filter_type = filter_type  # type: ignore[attr-defined]

        if search_field is not None:
            func.search_field = search_field  # type: ignore[attr-defined]

        if tags:
            func.tags = tags  # type: ignore[attr-defined]

        if icons:
            func.icons = True  # type: ignore[attr-defined]

        return func

    if function is None:
        return decorate

    return decorate(function)
