"""Pages of a resource's own, beside the ones it generates.

A resource generates its list, its forms and its summary. Anything else
- a map of the records, the timeline of one, a gallery, a report, a long
text on a page of its own, a JSON feed - is a page the project writes,
and declares on the resource. The framework mounts it at the resource's
address, guards it with the resource's permissions, draws it in the
frame and offers it where it belongs; what the page shows is entirely
the project's::

    @register(Customer)
    class CustomerResource(ModelResource):

        # A page of the resource: /example/customer/map/
        @page(title=_("Map"), icon="map", template="myapp/customer_map.html")
        def map(self, request):
            return {"customers": self.get_queryset(request)}

        # A page of each record: /example/customer/<pk>/timeline/
        @page(title=_("Timeline"), detail=True, icon="timeline",
              template="myapp/customer_timeline.html")
        def timeline(self, request, customer):
            return {"events": customer.events()}

        # Any response goes through as it is: JSON, a file, a redirect.
        @page(button=False)
        def geojson(self, request):
            return JsonResponse(...)

        # Or a view of the project's own, class or function.
        pages = (
            ResourcePage("gallery", view=GalleryView, detail=True,
                         title=_("Photos"), icon="photo_library"),
        )

Three ways to write one, from the least code to the most:

1. A method decorated with ``@page`` returning the context its
   ``template`` is drawn with - the template extends
   ``generic/resource/page.html`` and fills ``page_content``.
2. The same method returning a response of its own.
3. A view declared with ``ResourcePage(name, view=...)``: a subclass of
   :class:`ResourcePageView` gets everything a method page gets - it is
   a ``TemplateView`` with ``resource``, ``page`` and ``object`` - and
   any other Django view, class or function, gets the guard: signed in,
   allowed, and the record found, before it runs with the address's
   arguments (``pk``, or ``key`` for a data resource).

Works the same on a ``ModelResource``, an ``AutoResource`` and a
``DataResource``.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any, Callable, Mapping, Sequence

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import HttpResponseBase
from django.urls import path
from django.utils.encoding import force_str
from django.views.generic import TemplateView

from generic.api.columns import prettify_field_name
from generic.sites.views import SiteViewMixin
from generic.views.toolbar import Breadcrumb, ToolbarItem

#: A page's name is a piece of its address, and of its route's name.
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: Taken by the generated pages' routes: ``<prefix>_list``, ``_add``...
RESERVED_NAMES = frozenset(
    {"add", "change", "delete", "detail", "import", "list"}
)

#: What a method page may answer; a view of its own answers what it
#: implements.
PAGE_METHODS = frozenset({"get", "post"})

#: Permissions named by what they allow on the resource, as ``@action``
#: names them.
RESOURCE_PERMISSIONS = frozenset({"view", "add", "change", "delete"})

#: Stands for a record's key while its page's address is reversed.
KEY_PLACEHOLDER = "__page_key__"


@dataclasses.dataclass(frozen=True)
class ResourcePage:
    """One page of a resource's own. ``@page`` builds one from a method;
    ``pages = (ResourcePage(...),)`` declares one around a view."""

    #: A piece of the address - lower case, digits, dashes - and of the
    #: route's name: ``site:<app>_<model>_<name>``, ``site:data_<name>_
    #: <name>``.
    name: str
    #: The view: a ``ResourcePageView`` subclass, any other Django view,
    #: or a function. ``None`` for a ``@page`` method.
    view: Any = None
    title: Any = None
    #: A page of each record (``<pk>/<name>/``) rather than of the
    #: resource (``<name>/``).
    detail: bool = False
    icon: str = "article"
    #: Under the title; a record's page shows the record's name there.
    description: Any = ""
    #: The template a method's context is drawn with - usually one
    #: extending ``generic/resource/page.html``.
    template: str | None = None
    #: Needed besides the resource's view permission: ``"change"`` (or
    #: ``view``, ``add``, ``delete``: the resource's own), a permission
    #: string, several of them, or ``callable(user)``.
    permission: Any = None
    #: A button on the list page - on the record's page for a record's
    #: page - for whoever may open it.
    button: bool = True
    #: An entry of each row's menu in the table (a record's page).
    row_menu: bool = False
    #: An entry of the navigation, in the resource's group (a page of the
    #: resource).
    navigation: bool = False
    #: What a method page answers: ``("get",)``, or ``("get", "post")``
    #: for a page with a form.
    methods: Sequence[str] = ("get",)
    #: Set by ``@page``: the resource method answering the page.
    method: str | None = None

    def get_title(self) -> str:
        if self.title:
            return force_str(self.title)

        return prettify_field_name(self.name.replace("-", "_"))


def page(
    function: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    title: Any = None,
    detail: bool = False,
    icon: str = "article",
    description: Any = "",
    template: str | None = None,
    permission: Any = None,
    button: bool = True,
    row_menu: bool = False,
    navigation: bool = False,
    methods: Sequence[str] = ("get",),
) -> Any:
    """Make a resource method a page of the resource.

    ::

        @page(title=_("Map"), icon="map", template="myapp/map.html")
        def map(self, request):
            return {"customers": self.get_queryset(request)}

        @page(title=_("Timeline"), detail=True,
              template="myapp/timeline.html")
        def timeline(self, request, customer):
            return {"events": ...}

    A page of the resource takes ``(request)``, a record's page
    ``(request, record)`` - the record already found through the
    resource, and the reader already allowed to see it. It returns the
    context its ``template`` is drawn with, or a response of its own.
    The name is the method's, dashes for underscores.
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        func.generic_page = ResourcePage(  # type: ignore[attr-defined]
            name=name or func.__name__.replace("_", "-"),
            title=title,
            detail=detail,
            icon=icon,
            description=description,
            template=template,
            permission=permission,
            button=button,
            row_menu=row_menu,
            navigation=navigation,
            methods=tuple(method.lower() for method in methods),
            method=func.__name__,
        )

        return func

    return decorate if function is None else decorate(function)


def allows(user: Any, permission: Any) -> bool:
    """A permission string, several (all needed), or ``callable(user)``."""
    if callable(permission):
        return bool(permission(user))

    if isinstance(permission, str):
        return user.has_perm(permission)

    return all(user.has_perm(item) for item in permission)


# ---------------------------------------------------------------------
# On the resource
# ---------------------------------------------------------------------


class PagesMixin:
    """What a resource knows of its pages. Mixed into ``ModelResource``
    and ``DataResource``, which say what a record is:
    ``page_object_argument``, ``get_page_object`` and
    ``get_page_object_key``."""

    #: Pages around a view: ``(ResourcePage("gallery", view=...),)``.
    #: Methods decorated with ``@page`` are added after them.
    pages: Sequence[ResourcePage] = ()

    #: The address's argument naming a record, and its converter.
    page_object_argument = "pk"
    page_object_converter = "path"

    def get_page_object(self, request: Any, value: Any) -> Any:
        """The record ``value`` names, as this reader may see it; a 404
        otherwise."""
        raise NotImplementedError

    def get_page_object_key(self, obj: Any) -> Any:
        """What names ``obj`` in an address; ``obj`` may be that already."""
        raise NotImplementedError

    # -- declarations -------------------------------------------------

    def get_page_declarations(self) -> list[ResourcePage]:
        """Every page, in order: ``pages``, then the ``@page`` methods
        in the order they are written, a subclass's replacing its
        parent's of the same name."""
        cached = self.__dict__.get("_page_declarations")

        if cached is not None:
            return cached

        methods: dict[str, ResourcePage] = {}

        for klass in reversed(type(self).__mro__):
            for attribute, value in vars(klass).items():
                declared = getattr(value, "generic_page", None)

                if isinstance(declared, ResourcePage):
                    methods[attribute] = declared
                elif attribute in methods:
                    # Redefined without the decorator: no longer a page.
                    del methods[attribute]

        declarations = [*self.pages, *methods.values()]
        self.__dict__["_page_declarations"] = declarations

        return declarations

    def check_pages(self) -> None:
        """Refuse a declaration that could not work, at registration."""
        owner = type(self).__name__
        seen: set[str] = set()

        for declared in self.get_page_declarations():
            if not isinstance(declared, ResourcePage):
                raise ImproperlyConfigured(
                    f"{owner}.pages holds {declared!r}: ResourcePage(...) "
                    f"is expected."
                )

            where = f"{owner}: the page {declared.name!r}"

            if not NAME_PATTERN.match(declared.name):
                raise ImproperlyConfigured(
                    f"{where} must be named with lower case letters, "
                    f"digits and dashes."
                )

            if declared.name in RESERVED_NAMES:
                raise ImproperlyConfigured(
                    f"{where} takes a name the generated pages use: "
                    f"{', '.join(sorted(RESERVED_NAMES))}."
                )

            if declared.name in seen:
                raise ImproperlyConfigured(f"{where} is declared twice.")

            seen.add(declared.name)

            if declared.method is None:
                view = declared.view

                if view is None or not (
                    callable(view) or hasattr(view, "as_view")
                ):
                    raise ImproperlyConfigured(
                        f"{where} needs a view: a class-based view or a "
                        f"function."
                    )
            elif not callable(getattr(self, declared.method, None)):
                raise ImproperlyConfigured(
                    f"{where} names the method {declared.method!r}, "
                    f"which the resource does not have."
                )

            unknown = set(declared.methods) - PAGE_METHODS

            if unknown:
                raise ImproperlyConfigured(
                    f"{where} answers {', '.join(sorted(unknown))}: a "
                    f"method page answers GET and POST; a view of its own "
                    f"answers whatever it implements."
                )

            if declared.navigation and declared.detail:
                raise ImproperlyConfigured(
                    f"{where} is a record's page: it has no place in the "
                    f"navigation, which leads to the resource's pages."
                )

            if declared.row_menu and not declared.detail:
                raise ImproperlyConfigured(
                    f"{where} is a page of the resource: a row's menu "
                    f"leads to the record's pages."
                )

    def get_page(self, name: str) -> ResourcePage | None:
        for declared in self.get_page_declarations():
            if declared.name == name:
                return declared

        return None

    # -- permissions --------------------------------------------------

    def has_page_permission(
        self,
        request: Any,
        page: ResourcePage,
        obj: Any = None,
    ) -> bool:
        """Whether this reader may open ``page`` - of ``obj``, for a
        record's page. The resource's view permission, then the page's
        own. Override for a rule of the record's: a map only for the
        customers with an address."""
        user = getattr(request, "user", None)

        if user is None or not user.is_authenticated:
            return False

        if not self.has_view_permission(request, obj):  # type: ignore
            return False

        required = page.permission

        if required is None:
            return True

        if callable(required):
            return bool(required(user))

        names = [required] if isinstance(required, str) else list(required)

        return all(
            self.has_named_permission(request, name, obj) for name in names
        )

    def has_named_permission(self, request: Any, name: str, obj: Any) -> bool:
        """``view``, ``add``, ``change``, ``delete`` on this resource, or a
        full permission string."""
        if name in RESOURCE_PERMISSIONS:
            check = getattr(self, f"has_{name}_permission")

            return bool(
                check(request) if name == "add" else check(request, obj)
            )

        return allows(request.user, name)

    # -- addresses ----------------------------------------------------

    def get_page_url(self, name: str, obj: Any = None) -> str:
        """The address of the page ``name`` - of ``obj``, or of the
        record whose key ``obj`` is, for a record's page."""
        declared = self.get_page(name)

        if declared is None:
            return ""

        if not declared.detail:
            return self._reverse(self.url_name(name))  # type: ignore

        if obj is None:
            return ""

        return self._reverse(  # type: ignore[attr-defined]
            self.url_name(name),  # type: ignore[attr-defined]
            **{self.page_object_argument: self.get_page_object_key(obj)},
        )

    def get_page_url_template(self, name: str, token: str) -> str:
        """A record's page's address, its key left as ``token``."""
        url = self._reverse(  # type: ignore[attr-defined]
            self.url_name(name),  # type: ignore[attr-defined]
            **{self.page_object_argument: KEY_PLACEHOLDER},
        )

        return url.replace(KEY_PLACEHOLDER, token) if url else ""

    def get_page_urlpatterns(self, prefix: str) -> list[Any]:
        """The routes of every page, under ``prefix``. Placed before the
        record's own route, which would take ``<pk>/<name>/`` for a key."""
        argument = (
            f"<{self.page_object_converter}:{self.page_object_argument}>"
        )
        patterns = []

        for declared in self.get_page_declarations():
            route = (
                f"{prefix}{argument}/{declared.name}/"
                if declared.detail
                else f"{prefix}{declared.name}/"
            )
            patterns.append(
                path(
                    route,
                    build_page_view(self.site, self, declared),  # type: ignore
                    name=f"{self.url_prefix}_{declared.name}",  # type: ignore
                )
            )

        return patterns

    # -- where they are offered ---------------------------------------

    def get_page_buttons(self, request: Any, obj: Any = None) -> list[Any]:
        """The toolbar buttons of the pages this reader may open: the
        resource's on its list, a record's on that record's page."""
        detail = obj is not None
        buttons = []

        for declared in self.get_page_declarations():
            if declared.detail != detail or not declared.button:
                continue

            if not self.has_page_permission(request, declared, obj):
                continue

            url = self.get_page_url(declared.name, obj)

            if url:
                buttons.append(
                    ToolbarItem(
                        url=url,
                        label=declared.get_title(),
                        icon=declared.icon,
                        variant="ghost",
                    )
                )

        return buttons

    def get_page_row_actions(self, request: Any, token: str) -> list[dict]:
        """Row menu entries of the record's pages declared ``row_menu``.

        Asked once for the whole table: the page checks the record
        itself when it is opened."""
        actions = []

        for declared in self.get_page_declarations():
            if not (declared.detail and declared.row_menu):
                continue

            if not self.has_page_permission(request, declared):
                continue

            url = self.get_page_url_template(declared.name, token)

            if url:
                actions.append(
                    {
                        "name": f"page-{declared.name}",
                        "label": declared.get_title(),
                        "icon": declared.icon,
                        "url": url,
                    }
                )

        return actions

    def get_page_navigation(self, request: Any) -> list[dict[str, Any]]:
        """The resource's pages declared ``navigation``, as entries."""
        entries = []

        for declared in self.get_page_declarations():
            if not declared.navigation:
                continue

            if not self.has_page_permission(request, declared):
                continue

            url = self.get_page_url(declared.name)

            if url:
                entries.append(
                    {
                        "label": declared.get_title(),
                        "url": url,
                        "icon": declared.icon,
                        "order": self.order,  # type: ignore[attr-defined]
                    }
                )

        return entries

    def get_page_table_config(
        self,
        request: Any,
        key: str,
        **options: Any,
    ) -> dict[str, Any]:
        """This resource's table, for a page to show among other things:
        its own saved layout, and the address left to the page."""
        config = self.get_table_config(request)  # type: ignore
        merged = dict(config["options"])
        merged.update(
            stateKey=f"{merged.get('stateKey', '')}.in.{key}",
            syncUrl=False,
            **options,
        )

        return {**config, "options": merged}


# ---------------------------------------------------------------------
# The views
# ---------------------------------------------------------------------


class ResourcePageView(SiteViewMixin, TemplateView):
    """A page of a resource, drawn in the frame.

    What a ``@page`` method is answered by, and the base of a page's own
    view::

        class TimelineView(ResourcePageView):
            template_name = "myapp/ticket_timeline.html"

            def get_context_data(self, **kwargs):
                context = super().get_context_data(**kwargs)
                context["events"] = self.object.events()
                return context

        pages = (ResourcePage("timeline", view=TimelineView, detail=True),)

    ``resource``, ``page`` and - on a record's page - ``object`` are
    set before anything runs; the template receives them, with the
    title, the breadcrumbs (list, record, page) and the frame.
    """

    template_name = "generic/resource/page.html"
    resource: Any = None
    page: Any = None
    object: Any = None

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        self.page_context: dict[str, Any] = {}

        if request.user.is_authenticated and self.page.detail:
            self.object = self.resource.get_page_object(
                request, kwargs[self.resource.page_object_argument]
            )

        return super().dispatch(request, *args, **kwargs)

    def has_permission(self) -> bool:
        return self.resource.has_page_permission(
            self.request, self.page, self.object
        )

    # -- a method page ------------------------------------------------

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        if self.page.method:
            response = self.answer()

            if response is not None:
                return response

        return super().get(request, *args, **kwargs)

    def post(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        if self.page.method:
            return self.get(request, *args, **kwargs)

        return self.http_method_not_allowed(request, *args, **kwargs)

    def answer(self) -> Any:
        """Call the page's method: its response, or ``None`` once its
        context is kept for the template."""
        allowed = set(self.page.methods)

        if "get" in allowed:
            allowed.add("head")

        if self.request.method.lower() not in allowed:
            return self.http_method_not_allowed(self.request)

        function = getattr(self.resource, self.page.method)
        arguments = (self.object,) if self.page.detail else ()
        result = function(self.request, *arguments)

        if isinstance(result, HttpResponseBase):
            return result

        if result is not None and not isinstance(result, Mapping):
            raise TypeError(
                f"{type(self.resource).__name__}.{self.page.method} returned "
                f"{type(result).__name__}: a page method returns the "
                f"template's context (a dict) or a response."
            )

        if not self.page.template:
            raise ImproperlyConfigured(
                f"{type(self.resource).__name__}.{self.page.method} returned "
                f"what to show, but the page declares no template: "
                f"@page(template=...)."
            )

        self.page_context = dict(result or {})

        return None

    # -- the frame ----------------------------------------------------

    def get_template_names(self) -> list[str]:
        if self.page.template:
            return [self.page.template]

        return [self.template_name]

    def get_page_title(self) -> str:
        return self.page_title or self.page.get_title()

    def get_page_subtitle(self) -> str:
        if self.page_subtitle:
            return self.page_subtitle

        if self.page.description:
            return force_str(self.page.description)

        if self.object is not None:
            return self.resource.get_object_label(self.object)

        return ""

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        resource = self.resource
        crumbs = [
            Breadcrumb(
                label=resource.get_label_plural(),
                url=resource.get_list_url(),
            )
        ]

        if self.object is not None:
            crumbs.append(
                Breadcrumb(
                    label=resource.get_object_label(self.object),
                    url=resource.get_object_url(
                        resource.get_page_object_key(self.object)
                    ),
                )
            )

        crumbs.append(Breadcrumb(label=self.get_page_title()))

        return crumbs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update(
            resource=self.resource,
            page=self.page,
            object=self.object,
            opts=getattr(self.resource, "opts", None),
        )
        context.update(self.page_context)

        return context


class TrashPageView(ResourcePageView):
    """A resource's trash (``ModelResource.trash``): what was deleted,
    restored or deleted for good from its table."""

    template_name = "generic/resource/trash.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from generic.conf import generic_settings

        context = super().get_context_data(**kwargs)
        context["table"] = self.resource.get_trash_table_config(self.request)
        context["days"] = generic_settings.TRASH_DAYS

        return context


def trash_page() -> ResourcePage:
    """The *Trash* page a resource keeping one gets, for whoever may
    delete its records."""
    from django.utils.translation import gettext_lazy as _

    return ResourcePage(
        "trash",
        view=TrashPageView,
        title=_("Trash"),
        icon="delete",
        description=_("Deleted records, until restored or deleted for good."),
        permission="delete",
    )


def build_page_view(site: Any, resource: Any, page: ResourcePage) -> Any:
    """The callable a page's route calls."""
    view = page.view

    if view is None or (
        isinstance(view, type) and issubclass(view, ResourcePageView)
    ):
        return (view or ResourcePageView).as_view(
            site=site, resource=resource, page=page
        )

    handler = view.as_view() if hasattr(view, "as_view") else view

    def guarded(request: Any, *args: Any, **kwargs: Any) -> Any:
        """Signed in, allowed, the record found - then the view."""
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(), site.get_login_url()
            )

        obj = (
            resource.get_page_object(
                request, kwargs[resource.page_object_argument]
            )
            if page.detail
            else None
        )

        if not resource.has_page_permission(request, page, obj):
            raise PermissionDenied

        return handler(request, *args, **kwargs)

    # A view exempt from the CSRF check - an API's - stays exempt.
    guarded.csrf_exempt = getattr(  # type: ignore[attr-defined]
        handler, "csrf_exempt", False
    )
    guarded.__name__ = getattr(handler, "__name__", "page")
    guarded.__doc__ = getattr(handler, "__doc__", None)

    return guarded


__all__ = [
    "PagesMixin",
    "ResourcePage",
    "ResourcePageView",
    "allows",
    "build_page_view",
    "page",
]
