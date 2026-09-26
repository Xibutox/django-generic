"""The site: the registry of resources and the application around them.

One instance, ``site``, serves most projects. It owns the URLs of every
generated page and endpoint, the navigation, the command palette search
and the frame every page is drawn in.
"""

from __future__ import annotations

import dataclasses
import functools
import importlib.util
import re
from typing import Any, Callable, Iterable, Sequence
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models.base import ModelBase
from django.urls import NoReverseMatch, path, reverse
from django.utils.encoding import force_str
from django.utils.safestring import mark_safe
from django.utils.translation import gettext
from rest_framework.routers import SimpleRouter

from generic.conf import generic_settings
from generic.history import recording as history
from generic.i18n import language_menu
from generic.sites import realtime
from generic.sites.imports import check_import, declaration_of
from generic.sites.resources import ModelResource
from generic.sites.shortcuts import (
    Shortcut,
    clean_url,
    from_setting,
    group_entries,
)
from generic.sites.sso import SsoProvider
from generic.sites.sso import from_setting as from_sso_setting


class AlreadyRegistered(ImproperlyConfigured):
    """A model can be registered once per site."""


#: What a design token override may look like: a custom property name
#: and a value made of colours, lengths and plain words. Anything else
#: is dropped rather than injected into a <style> element.
_TOKEN_NAME = re.compile(r"^--[a-z0-9-]+$")
_TOKEN_VALUE = re.compile(r"^[#a-zA-Z0-9 .,%()/-]+$")


@dataclasses.dataclass
class NavigationLink:
    """A navigation entry that is not a registered resource."""

    label: Any
    url: str = ""
    route: str = ""
    icon: str = "link"
    group: Any = ""
    order: int = 0
    #: A permission string, an iterable of them, ``callable(user)``, or
    #: ``None`` for any signed-in user.
    permission: Any = None
    target: str = ""

    def resolve_url(self) -> str:
        if self.url:
            return force_str(self.url)

        try:
            return reverse(self.route)
        except NoReverseMatch:
            return ""

    def is_visible(self, user: Any) -> bool:
        if user is None or not user.is_authenticated:
            return False

        if self.permission is None or self.permission is True:
            return True

        if callable(self.permission):
            return bool(self.permission(user))

        if isinstance(self.permission, str):
            return user.has_perm(self.permission)

        return all(user.has_perm(item) for item in self.permission)


class GenericSite:
    """A registry of resources, and the application built from it."""

    #: Template of the dashboard; a project points it at its own.
    index_template = "generic/site/index.html"

    def __init__(
        self,
        name: str = "site",
        *,
        title: Any = None,
        header: Any = None,
        icon: str | None = None,
    ) -> None:
        self.name = name
        self._title = title
        self._header = header
        self._icon = icon
        self._registry: dict[Any, ModelResource] = {}
        #: Rows that are not a model's, by name (``generic.sites.data``).
        self._data: dict[str, Any] = {}
        self._links: list[NavigationLink] = []
        self._shortcuts: list[Shortcut] = []
        self._shortcut_providers: list[Callable[[Any], Any]] = []
        self._sso_providers: list[SsoProvider] = []
        self._index_context: list[Callable[[Any], dict[str, Any]]] = []

    def __repr__(self) -> str:
        return f"<GenericSite {self.name!r}>"

    # -- registration --------------------------------------------------------

    def register(
        self,
        model_or_iterable: Any,
        resource_class: type[ModelResource] | None = None,
        **options: Any,
    ) -> None:
        resource_class = resource_class or ModelResource
        models = (
            [model_or_iterable]
            if isinstance(model_or_iterable, ModelBase)
            else list(model_or_iterable)
        )

        for model in models:
            if model._meta.abstract:
                raise ImproperlyConfigured(
                    f"{model.__name__} is abstract and cannot be "
                    f"registered."
                )

            if model in self._registry:
                raise AlreadyRegistered(
                    f"{model.__name__} is already registered on " f"{self!r}."
                )

            klass = resource_class

            if options:
                klass = type(
                    f"{model.__name__}Resource",
                    (resource_class,),
                    {**options, "__module__": resource_class.__module__},
                )

            resource = klass(model, self)
            # A page that could not work is refused where it is declared,
            # and so is an import naming what the model does not have.
            resource.check_pages()
            check_import(resource)
            self._registry[model] = resource
            realtime.connect(resource)
            history.connect(resource)

    def auto(self, model_or_iterable: Any, **options: Any) -> None:
        """Register models with pages worked out from each model.

        ``site.auto(Equipment, related=("maintenances",))``. See
        ``generic.sites.auto``: ``options`` are resource attributes,
        and win over what is worked out.
        """
        from generic.sites.auto import AutoResource

        self.register(model_or_iterable, AutoResource, **options)

    def complete_auto(self) -> None:
        """Give pages to the related models ``auto`` resources name.

        Done once every ``resources.py`` has been read - at the end of
        the app's ``ready()``, and again when the URLs are built, for a
        registration made later - so a related model declared after its
        parent, by hand or with ``auto``, keeps its own declaration. One
        nobody declared is given pages worked out from it, out of the
        navigation: it is reached from the record it belongs to.
        """
        from generic.sites.auto import AutoResource

        for resource in list(self._registry.values()):
            if not isinstance(resource, AutoResource):
                continue

            for model in resource.get_related_models():
                if model not in self._registry:
                    self.register(
                        model,
                        AutoResource,
                        show_in_navigation=False,
                    )

    def unregister(self, model_or_iterable: Any) -> None:
        models = (
            [model_or_iterable]
            if isinstance(model_or_iterable, ModelBase)
            else list(model_or_iterable)
        )

        for model in models:
            resource = self._registry.pop(model, None)

            if resource is None:
                raise ImproperlyConfigured(
                    f"{model.__name__} is not registered on {self!r}."
                )

            realtime.disconnect(resource)
            history.disconnect(resource)

    def register_data(self, resource_class: type) -> Any:
        """Give rows that are not a model's a list page and a page per
        row: ``site.register_data(ServiceResource)``. See
        ``generic.sites.data``."""
        from generic.sites.data import DataResource

        if not (
            isinstance(resource_class, type)
            and issubclass(resource_class, DataResource)
        ):
            raise ImproperlyConfigured(
                "register_data() takes a DataResource subclass."
            )

        resource = resource_class(self)
        resource.check_pages()

        if resource.name in self._data:
            raise AlreadyRegistered(
                f"A data resource named {resource.name!r} is already "
                f"registered on {self!r}."
            )

        self._data[resource.name] = resource

        return resource

    def unregister_data(self, name: str) -> None:
        if self._data.pop(name, None) is None:
            raise ImproperlyConfigured(
                f"No data resource named {name!r} on {self!r}."
            )

    def get_data_resource(self, name: str) -> Any:
        return self._data.get(name)

    def get_data_resources(self) -> list[Any]:
        """Registration order, as the models'."""
        return list(self._data.values())

    def is_registered(self, model: Any) -> bool:
        return model in self._registry

    def get_resource(self, model: Any) -> ModelResource | None:
        return self._registry.get(model)

    def get_resources(self) -> list[ModelResource]:
        """Registration order, which is also the navigation order."""
        return list(self._registry.values())

    def get_related_table(self, key: str) -> Any:
        """The related table a ``_related`` parameter names, or None.

        ``key`` is ``<app>.<model>.<relation>``: the resource declaring
        the table, then the table's name.
        """
        label, _, name = key.rpartition(".")

        for resource in self._registry.values():
            if resource.label_lower == label:
                return resource.get_bound_related_table(name)

        return None

    def get_grid(self, key: str) -> Any:
        """The grid a ``_grid`` parameter names, or None.

        ``key`` is ``<app>.<model>.<grid>``: the resource declaring the
        grid, then the grid's name.
        """
        label, _, name = key.rpartition(".")

        for resource in self._registry.values():
            if resource.label_lower == label:
                return resource.get_bound_grid(name)

        return None

    def add_link(
        self,
        label: Any,
        *,
        url: str = "",
        route: str = "",
        icon: str = "link",
        group: Any = "",
        order: int = 0,
        permission: Any = None,
        target: str = "",
    ) -> NavigationLink:
        """Add a page that is not a resource to the navigation."""
        link = NavigationLink(
            label=label,
            url=url,
            route=route,
            icon=icon,
            group=group,
            order=order,
            permission=permission,
            target=target,
        )
        self._links.append(link)

        return link

    # -- the dashboard's hub -------------------------------------------

    def add_shortcut(
        self,
        label: Any,
        *,
        url: str = "",
        route: str = "",
        route_args: tuple[Any, ...] = (),
        icon: str = "arrow_forward",
        description: Any = "",
        group: Any = "",
        order: int = 0,
        permission: Any = None,
        count: Any = None,
        external: bool | None = None,
    ) -> Shortcut:
        """Put a card at the top of the dashboard.

        Anywhere worth going first: a filtered list, a page of the
        project's own, or an address outside the application.
        """
        shortcut = Shortcut(
            label=label,
            url=url,
            route=route,
            route_args=tuple(route_args),
            icon=icon,
            description=description,
            group=group,
            order=order,
            permission=permission,
            count=count,
            external=external,
        )
        # The address is refused now rather than on the first
        # dashboard, because it is a declaration. The *route* is not
        # resolved here on purpose: a resources.py is imported while
        # the site is still being built, and reverse() at that moment
        # freezes a URLconf holding only what happens to be registered
        # so far - which silently loses every screen added after it.
        clean_url(url, label)
        self._shortcuts.append(shortcut)

        return shortcut

    # -- signing in through somebody else ------------------------------

    def add_sso_provider(
        self,
        label: Any,
        *,
        url: str = "",
        route: str = "",
        icon: str = "shield_person",
        description: Any = "",
        order: int = 0,
        next_param: str = "next",
    ) -> SsoProvider:
        """Offer a way in that is not a password.

        The address is the one the project's own library already
        serves; the framework only puts it on the sign-in page.
        """
        provider = SsoProvider(
            label=label,
            url=url,
            route=route,
            icon=icon,
            description=description,
            order=order,
            next_param=next_param,
        )
        # Same reason as a shortcut: the address is checked where it is
        # written, the route is resolved when the page is drawn.
        clean_url(url, label)
        self._sso_providers.append(provider)

        return provider

    def get_sso_providers(self, destination: str = "") -> list[dict]:
        """Every way in, in the order they are offered."""
        declared = [
            *from_sso_setting(generic_settings.SSO_PROVIDERS),
            *self._sso_providers,
        ]
        entries = [
            provider.as_entry(destination)
            for provider in sorted(
                declared, key=lambda item: (item.order, force_str(item.label))
            )
        ]

        return [entry for entry in entries if entry["url"]]

    def offers_password_login(self, providers: list[dict]) -> bool:
        """Whether the sign-in page still shows the password form.

        A project may forbid local passwords - but a page offering no
        way in at all is a locked door, not a policy, so the form comes
        back as soon as nothing else is there.
        """
        if not providers:
            return True

        return bool(generic_settings.SSO_PASSWORD_LOGIN)

    def shortcut_provider(
        self,
        function: Callable[[Any], Any],
    ) -> Callable[[Any], Any]:
        """Add shortcuts worked out per request.

        The hook a project backs its hub with a model through, without
        the framework shipping one::

            @site.shortcut_provider
            def bookmarks(request):
                return [
                    Shortcut(label=row.title, url=row.url, icon=row.icon)
                    for row in Bookmark.objects.filter(team=...)
                ]
        """
        self._shortcut_providers.append(function)

        return function

    def get_shortcuts(self, request: Any) -> list[dict[str, Any]]:
        """The hub, in blocks, for whoever is asking.

        Declared three ways and answered as one: the setting, the
        registry, and whatever the providers add.
        """
        user = getattr(request, "user", None)
        declared = [
            *from_setting(generic_settings.SHORTCUTS),
            *self._shortcuts,
        ]

        for provider in self._shortcut_providers:
            declared.extend(provider(request) or ())

        entries = [
            shortcut.as_entry(request)
            for shortcut in declared
            if shortcut.is_visible(user)
        ]

        # A shortcut whose route is not mounted here has no address,
        # and a card pointing nowhere is worse than no card.
        return group_entries([entry for entry in entries if entry["url"]])

    # -- URLs -------------------------------------------------------------

    def get_urls(self) -> list[Any]:
        from generic.accounts import views as account_views
        from generic.help import views as help_views
        from generic.maintenance import views as maintenance_views
        from generic.sites import views
        from generic.tasks import views as task_views
        from generic.watch import views as watch_views

        # Before the resources are walked: a related model an auto
        # resource names needs pages, and this is when they are made.
        self.complete_auto()

        urlpatterns: list[Any] = [
            path("", views.SiteIndexView.as_view(site=self), name="index"),
            path(
                "api/search/",
                views.SiteSearchView.as_view(site=self),
                name="search",
            ),
            path(
                "login/",
                account_views.LoginView.as_view(site=self),
                name="login",
            ),
            path(
                "logout/",
                account_views.LogoutView.as_view(site=self),
                name="logout",
            ),
            path(
                "account/",
                account_views.AccountView.as_view(site=self),
                name="account",
            ),
            path(
                "account/password/",
                account_views.PasswordChangeView.as_view(site=self),
                name="password_change",
            ),
            path(
                "account/password/done/",
                account_views.PasswordChangeDoneView.as_view(site=self),
                name="password_change_done",
            ),
            path(
                "notifications/",
                account_views.NotificationsView.as_view(site=self),
                name="notifications",
            ),
            path(
                "set-language/",
                account_views.SetLanguageView.as_view(site=self),
                name="set_language",
            ),
            path(
                "restart/",
                maintenance_views.RestartAnnouncementPage.as_view(site=self),
                name="restart",
            ),
            path(
                "help/",
                help_views.HelpPage.as_view(site=self),
                name="help",
            ),
            path(
                "help/changes/",
                help_views.ChangelogPage.as_view(site=self),
                name="changelog",
            ),
            path(
                "tasks/",
                task_views.TasksPage.as_view(site=self),
                name="tasks",
            ),
            path(
                "watching/",
                watch_views.WatchesPage.as_view(site=self),
                name="watches",
            ),
        ]

        router = SimpleRouter()

        for resource in self._registry.values():
            prefix = f"{resource.app_label}/{resource.model_name}/"
            name = resource.url_prefix

            urlpatterns += [
                path(
                    prefix,
                    views.ResourceListView.as_view(
                        site=self, resource=resource
                    ),
                    name=f"{name}_list",
                ),
                path(
                    f"{prefix}add/",
                    views.ResourceFormView.as_view(
                        site=self,
                        resource=resource,
                        mode="create",
                    ),
                    name=f"{name}_add",
                ),
                path(
                    f"{prefix}<path:pk>/change/",
                    views.ResourceFormView.as_view(
                        site=self,
                        resource=resource,
                        mode="update",
                    ),
                    name=f"{name}_change",
                ),
                path(
                    f"{prefix}<path:pk>/delete/",
                    views.ResourceDeleteView.as_view(
                        site=self,
                        resource=resource,
                        model=resource.model,
                    ),
                    name=f"{name}_delete",
                ),
                # Spreadsheets read into records, where declared.
                *(
                    [
                        path(
                            f"{prefix}import/",
                            views.ResourceImportView.as_view(
                                site=self, resource=resource
                            ),
                            name=f"{name}_import",
                        )
                    ]
                    if declaration_of(resource) is not None
                    else []
                ),
                # The project's own pages of the resource and of each
                # record (generic.sites.pages).
                *resource.get_page_urlpatterns(prefix),
                # Last: "<path:pk>/" would take ".../change/" otherwise.
                path(
                    f"{prefix}<path:pk>/",
                    views.ResourceDetailView.as_view(
                        site=self,
                        resource=resource,
                    ),
                    name=f"{name}_detail",
                ),
            ]

            router.register(
                f"api/{resource.app_label}/{resource.model_name}",
                resource.get_viewset_class(),
                basename=f"api_{name}",
            )

        # Rows that are not a model's: a list and a page per row, read
        # only, under data/.
        for resource in self._data.values():
            # Every resource is registered by now: the ones it names too.
            resource.check()
            prefix = f"data/{resource.name}/"
            name = resource.url_prefix

            urlpatterns += [
                path(
                    prefix,
                    views.DataListView.as_view(site=self, resource=resource),
                    name=f"{name}_list",
                ),
                # Before the row's own route, which would take a page's
                # name for a key.
                *resource.get_page_urlpatterns(prefix),
                path(
                    f"{prefix}<str:key>/",
                    views.DataDetailView.as_view(site=self, resource=resource),
                    name=f"{name}_detail",
                ),
            ]

            router.register(
                f"api/data/{resource.name}",
                resource.get_viewset_class(),
                basename=f"api_{name}",
            )

        return urlpatterns + router.urls

    @property
    def urls(self) -> tuple[list[Any], str, str]:
        return self.get_urls(), "generic_site", self.name

    def get_url(self, name: str, **kwargs: Any) -> str:
        try:
            return reverse(f"{self.name}:{name}", kwargs=kwargs or None)
        except NoReverseMatch:
            return ""

    def get_login_url(self) -> str:
        return self.get_url("login") or force_str(settings.LOGIN_URL)

    # -- identity ------------------------------------------------------------

    def get_title(self) -> str:
        return force_str(self._title or generic_settings.SITE_TITLE)

    def get_header(self) -> str:
        return force_str(
            self._header or generic_settings.SITE_HEADER or self.get_title()
        )

    def get_icon(self) -> str:
        return self._icon or generic_settings.SITE_ICON

    def get_home_url(self) -> str:
        return (
            force_str(generic_settings.SITE_URL or "")
            or self.get_url("index")
            or "/"
        )

    # -- navigation -----------------------------------------------------------

    def get_settings_links(self) -> list[NavigationLink]:
        links = []

        for group in generic_settings.NAVIGATION or ():
            for item in group.get("items", ()):
                links.append(
                    NavigationLink(
                        label=item.get("title") or item.get("label", ""),
                        url=item.get("url") or item.get("link", ""),
                        route=item.get("route", ""),
                        icon=item.get("icon", "link"),
                        group=group.get("title", ""),
                        order=item.get("order", 0),
                        permission=item.get("permission"),
                        target=item.get("target", ""),
                    )
                )

        return links

    def get_navigation(self, request: Any) -> list[dict[str, Any]]:
        """Groups of links, filtered on the user's permissions."""
        user = getattr(request, "user", None)

        if user is None or not user.is_authenticated:
            return []

        groups: dict[str, dict[str, Any]] = {}

        def group(label: Any) -> list[dict[str, Any]]:
            key = force_str(label or "")

            return groups.setdefault(key, {"label": key, "items": []})["items"]

        index = self.get_url("index")

        if index:
            group("").append(
                {
                    "label": gettext("Dashboard"),
                    "url": index,
                    "icon": "dashboard",
                    "order": -1,
                    "exact": True,
                }
            )

        for resource in self.get_resources():
            if not resource.show_in_navigation:
                continue

            if not resource.has_module_permission(request):
                continue

            url = (
                resource.get_list_url()
                if resource.has_view_permission(request)
                else resource.get_add_url()
            )

            if url:
                group(resource.get_group()).append(
                    {
                        "label": resource.get_label_plural(),
                        "url": url,
                        "icon": resource.get_icon(),
                        "order": resource.order,
                    }
                )

        for resource in self.get_data_resources():
            if not resource.show_in_navigation:
                continue

            url = resource.get_list_url()

            if url and resource.has_view_permission(request):
                group(resource.get_group()).append(
                    {
                        "label": resource.get_label_plural(),
                        "url": url,
                        "icon": resource.get_icon(),
                        "order": resource.order,
                    }
                )

        # A resource's own pages declared navigation=True, after it: the
        # sort below keeps the order they were added in.
        for resource in [*self.get_resources(), *self.get_data_resources()]:
            for entry in resource.get_page_navigation(request):
                group(resource.get_group()).append(entry)

        for link in [*self._links, *self.get_settings_links()]:
            if not link.is_visible(user):
                continue

            url = link.resolve_url()

            if url:
                group(link.group).append(
                    {
                        "label": force_str(link.label),
                        "url": url,
                        "icon": link.icon,
                        "order": link.order,
                        "target": link.target,
                    }
                )

        result = []

        for entry in groups.values():
            entry["items"].sort(key=lambda item: item["order"])
            result.append(entry)

        self.mark_current(result, request.path)

        return [entry for entry in result if entry["items"]]

    @staticmethod
    def mark_current(groups: list[dict[str, Any]], current: str) -> None:
        """Highlight the one entry the page belongs to.

        The longest matching prefix wins, so a change page highlights its
        list rather than both the list and the dashboard.
        """
        best: dict[str, Any] | None = None
        best_length = -1

        for entry in groups:
            for item in entry["items"]:
                item_path = urlparse(item["url"]).path

                if item.get("exact") or item_path == "/":
                    matched = current == item_path
                else:
                    matched = current.startswith(item_path)

                if matched and len(item_path) > best_length:
                    best, best_length = item, len(item_path)

        if best is not None:
            best["is_current"] = True

    def get_app_list(self, request: Any) -> list[dict[str, Any]]:
        """The resources, by group, for the dashboard."""
        groups: dict[str, dict[str, Any]] = {}

        for resource in self.get_resources():
            if not resource.has_module_permission(request):
                continue

            entry = groups.setdefault(
                resource.get_group(),
                {"label": resource.get_group(), "resources": []},
            )
            entry["resources"].append(
                {
                    "label": resource.get_label_plural(),
                    "icon": resource.get_icon(),
                    "description": force_str(resource.description),
                    "list_url": (
                        resource.get_list_url()
                        if resource.has_view_permission(request)
                        else ""
                    ),
                    "add_url": (
                        resource.get_add_url()
                        if resource.has_add_permission(request)
                        else ""
                    ),
                }
            )

        for resource in self.get_data_resources():
            if not resource.has_view_permission(request):
                continue

            entry = groups.setdefault(
                resource.get_group(),
                {"label": resource.get_group(), "resources": []},
            )
            entry["resources"].append(
                {
                    "label": resource.get_label_plural(),
                    "icon": resource.get_icon(),
                    "description": force_str(resource.description),
                    "list_url": resource.get_list_url(),
                    "add_url": "",
                }
            )

        return list(groups.values())

    def index_context(
        self,
        function: Callable[[Any], dict[str, Any]],
    ) -> Callable[[Any], dict[str, Any]]:
        """Register a function adding context to the dashboard.

        ::

            @site.index_context
            def shortcuts(request):
                return {"open_tickets": Ticket.objects.open().count()}
        """
        self._index_context.append(function)

        return function

    def get_index_context(self, request: Any) -> dict[str, Any]:
        """Extra context for the dashboard, from ``index_context``."""
        context: dict[str, Any] = {}

        for function in self._index_context:
            context.update(function(request) or {})

        return context

    # -- search ------------------------------------------------------------

    def search(self, request: Any, term: str) -> list[dict[str, Any]]:
        """Pages and records matching ``term``, for the command palette."""
        term = (term or "").strip()[:100]

        if not term:
            return []

        lowered = term.lower()
        groups: list[dict[str, Any]] = []

        pages = [
            {
                "label": item["label"],
                "url": item["url"],
                "icon": item.get("icon", ""),
                "description": entry["label"],
            }
            for entry in self.get_navigation(request)
            for item in entry["items"]
            if lowered in item["label"].lower()
        ]

        if pages:
            groups.append(
                {
                    "label": gettext("Pages"),
                    "icon": "arrow_forward",
                    "items": pages[:8],
                }
            )

        limit = generic_settings.SEARCH_RESULTS_PER_RESOURCE

        for resource in self.get_resources():
            if not resource.get_search_fields(request):
                continue

            if not resource.has_view_permission(request):
                continue

            items = [
                {
                    "label": resource.get_object_label(obj),
                    "description": (
                        resource.get_object_description(obj)
                        or resource.get_label()
                    ),
                    "url": resource.get_object_url(obj.pk),
                    "icon": resource.get_icon(),
                }
                for obj in resource.get_search_results(request, term, limit)
            ]

            if items:
                groups.append(
                    {
                        "label": resource.get_label_plural(),
                        "icon": resource.get_icon(),
                        "items": items,
                    }
                )

        # Whatever else the application offers: wiki pages, for one.
        for provider in self.__dict__.get("_search_providers", ()):
            groups.extend(provider(request, term) or ())

        return groups

    def search_provider(
        self,
        function: Callable[[Any, str], list[dict[str, Any]]],
    ) -> Callable[[Any, str], list[dict[str, Any]]]:
        """Add results to the command palette.

        ``function(request, term)`` returns groups shaped like the
        resources' ones - ``{"label", "icon", "items": [{"label",
        "url", "icon", "description"}]}`` - or nothing::

            @site.search_provider
            def reports(request, term):
                ...
        """
        self.__dict__.setdefault("_search_providers", []).append(function)

        return function

    # -- the frame ------------------------------------------------------------

    def get_theme_css(self) -> str:
        declarations = [
            f"{name}: {value};"
            for name, value in (generic_settings.THEME or {}).items()
            if _TOKEN_NAME.match(str(name)) and _TOKEN_VALUE.match(str(value))
        ]

        if not declarations:
            return ""

        # Both names and values were matched against strict patterns
        # above, so nothing reaching this string can close the element.
        css = ":root { " + " ".join(declarations) + " }"

        return mark_safe(css)  # nosec B308 B703 - matched above

    def get_framework_api(self) -> dict[str, str]:
        """The framework's own endpoints, where they are mounted."""
        names = {
            "notifications": "generic:notification-list",
            "notificationsUnread": "generic:notification-unread-count",
            "notificationsReadAll": "generic:notification-read-all",
            "preferences": "generic:preferences",
            "profile": "generic:profile",
            "savedViews": "generic:saved-view-list",
            "restart": "generic:restart",
            "watches": "generic:watch-list",
            "watchToggle": "generic:watch-toggle",
            "watchStatus": "generic:watch-status",
        }
        api = {}

        for key, name in names.items():
            try:
                api[key] = reverse(name)
            except NoReverseMatch:
                api[key] = ""

        return api

    def get_admin_url(self, user: Any) -> str:
        if not generic_settings.SHOW_ADMIN_LINK:
            return ""

        if user is None or not getattr(user, "is_staff", False):
            return ""

        try:
            return reverse("admin:index")
        except NoReverseMatch:
            return ""

    def get_client_assets(self) -> dict[str, Any]:
        """Scripts the client loads only when a page needs them.

        ECharts weighs a megabyte: a page without a chart never fetches
        it. Override to serve another build.
        """
        from django.templatetags.static import static

        return {
            "echarts": static("generic/vendor/echarts/echarts.min.js"),
            "echartsLocales": {
                "fr": static("generic/vendor/echarts/langFR.js"),
            },
        }

    def get_resource_by_label(self, label: str) -> ModelResource | None:
        """The resource of ``<app>.<model>``, or None."""
        label = str(label).lower()

        for resource in self._registry.values():
            if resource.label_lower == label:
                return resource

        return None

    def get_account_links(self, request: Any) -> list[dict[str, Any]]:
        """Extra entries for the account menu. Override to add some."""
        return []

    def get_chrome(self, request: Any) -> dict[str, Any]:
        """Everything ``generic/base.html`` draws the frame from."""
        user = getattr(request, "user", None)
        authenticated = bool(user is not None and user.is_authenticated)

        urls = {
            name: self.get_url(name)
            for name in (
                "index",
                "search",
                "account",
                "password_change",
                "logout",
                "login",
                "notifications",
                "set_language",
                "restart",
                "help",
                "changelog",
                "watches",
            )
        }
        urls["admin"] = self.get_admin_url(user) if authenticated else ""

        api = self.get_framework_api()
        preferences = None
        display_name = ""
        initials = ""

        if authenticated:
            from generic.accounts.models import UserPreferences

            preferences = getattr(request, "_generic_preferences", None)

            if preferences is None:
                preferences = UserPreferences.for_user(user)
                request._generic_preferences = preferences

            display_name = user_display_name(user)
            initials = user_initials(user)

        can_change_password = bool(
            authenticated and user.has_usable_password()
        )

        return {
            "title": self.get_title(),
            "header": self.get_header(),
            "icon": self.get_icon(),
            "home_url": self.get_home_url(),
            "navigation": self.get_navigation(request) if request else [],
            "urls": urls,
            "api": api,
            "user": {
                "authenticated": authenticated,
                "display_name": display_name,
                "initials": initials,
                "can_change_password": can_change_password,
            },
            "account_links": self.get_account_links(request),
            # Empty unless the project offers more than one language.
            "languages": language_menu(),
            "can_announce_restart": self.may_announce_restart(user),
            "theme_css": self.get_theme_css(),
            "theme_preference": (
                preferences.theme if preferences is not None else ""
            ),
            # Where this user keeps the navigation. A browser that has
            # been told otherwise wins; this is the default it follows.
            "navigation_preference": (
                preferences.navigation if preferences is not None else ""
            ),
            "appearance_style": (
                preferences.appearance_style()
                if preferences is not None
                else ""
            ),
            # Shown at the foot of the navigation and on the help page.
            "version": str(generic_settings.VERSION or ""),
            "client": {
                "site": self.name,
                "urls": urls,
                "api": api,
                "websocketUrl": (
                    generic_settings.EVENTS_WEBSOCKET_URL or ""
                    if authenticated and events_installed()
                    else ""
                ),
                "csrfCookieName": settings.CSRF_COOKIE_NAME,
                # Loaded on demand, the first time a page draws a chart.
                "assets": self.get_client_assets(),
                "user": {
                    "authenticated": authenticated,
                    "id": user.pk if authenticated else None,
                    "name": display_name,
                },
                "preferences": (
                    preferences.as_client() if preferences is not None else {}
                ),
                # A restart announced before this page was opened: the
                # banner has to be there on arrival, not only for the
                # people who were connected when it was announced.
                "maintenance": (
                    self.get_planned_restart() if authenticated else None
                ),
            },
        }

    def may_announce_restart(self, user: Any) -> bool:
        """Whether this user is offered the restart page at all."""
        from generic.maintenance.api import may_announce

        return may_announce(user)

    def get_planned_restart(self) -> dict[str, Any] | None:
        """The restart everyone should know about, if there is one."""
        from generic.maintenance.models import RestartAnnouncement

        try:
            announcement = RestartAnnouncement.objects.current()
        except Exception:  # pragma: no cover - before the first migrate
            return None

        return announcement.as_client() if announcement else None


@functools.lru_cache(maxsize=1)
def events_installed() -> bool:
    """Whether Channels is there to answer the pages' socket.

    Without the ``events`` extra nothing serves ``/ws/events/``, and a
    page opening it anyway only fills the console with failed attempts:
    the client is not told of a socket that cannot exist. A project with
    Channels but served over WSGI sets ``EVENTS_WEBSOCKET_URL = None``.
    """
    return importlib.util.find_spec("channels") is not None


def user_display_name(user: Any) -> str:
    full_name = getattr(user, "get_full_name", lambda: "")()

    return force_str(full_name or user.get_username())


def user_initials(user: Any) -> str:
    """Two letters for the avatar: first and last name, or the login."""
    first = force_str(getattr(user, "first_name", "") or "")
    last = force_str(getattr(user, "last_name", "") or "")

    if first or last:
        return (first[:1] + last[:1]).upper()

    return force_str(user.get_username())[:2].upper()


site = GenericSite()


def register(
    *models: Any,
    site: GenericSite | None = None,
) -> Callable[[type[ModelResource]], type[ModelResource]]:
    """Register models with the decorated resource class.

    ::

        @register(Ticket)
        class TicketResource(ModelResource):
            ...
    """
    target = site or globals()["site"]

    def decorate(resource_class: type[ModelResource]) -> type[ModelResource]:
        if not issubclass(resource_class, ModelResource):
            raise ValueError("A registered class must subclass ModelResource.")

        target.register(models, resource_class)

        return resource_class

    return decorate


def register_data(
    resource_class: Any = None,
    *,
    site: GenericSite | None = None,
) -> Any:
    """Register a ``DataResource``: rows that are not a model's.

    ::

        @register_data
        class ServiceResource(DataResource):
            ...
    """
    target = site or globals()["site"]

    def decorate(klass: Any) -> Any:
        target.register_data(klass)

        return klass

    return decorate(resource_class) if resource_class is not None else decorate


def _models(value: Iterable[Any] | Any) -> Sequence[Any]:
    return [value] if isinstance(value, ModelBase) else list(value)
