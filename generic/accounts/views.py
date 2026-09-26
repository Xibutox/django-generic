"""Account pages: sign in and out, password, settings, notifications."""

from __future__ import annotations

from typing import Any

from django.conf import global_settings, settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.http import HttpResponseRedirect
from django.shortcuts import resolve_url
from django.urls import NoReverseMatch, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext
from django.views.generic import TemplateView, View

from generic.accounts.models import UserPreferences
from generic.accounts.serializers import is_external_account
from generic.events.serializers import NotificationSerializer
from generic.i18n import is_offered
from generic.sites.views import SiteViewMixin
from generic.views.mixins import PageMixin
from generic.views.toolbar import Breadcrumb


def _reverse(name: str) -> str:
    try:
        return reverse(name)
    except NoReverseMatch:
        return ""


class SitePageMixin(PageMixin):
    """Chrome for account pages rendered by a site."""

    site: Any = None

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["generic_site"] = self.site

        return context


class LoginView(SitePageMixin, auth_views.LoginView):
    template_name = "generic/auth/login.html"
    redirect_authenticated_user = True

    def get_default_redirect_url(self) -> str:
        # Django's own default points at /accounts/profile/, which no
        # project has; the site's dashboard is a better landing page.
        configured = getattr(settings, "LOGIN_REDIRECT_URL", None)

        if configured and configured != global_settings.LOGIN_REDIRECT_URL:
            return resolve_url(configured)

        return self.site.get_home_url()

    def get_page_title(self) -> str:
        return gettext("Sign in")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """The ways in, and whether a password is still one of them.

        The destination travels with the provider's link so that
        signing in through it lands where the reader was going.
        Django has already refused a destination pointing off this
        site, so what is passed on is the empty string in that case.
        """
        context = super().get_context_data(**kwargs)
        providers = self.site.get_sso_providers(self.get_redirect_url())

        context["sso_providers"] = providers
        context["password_login"] = self.site.offers_password_login(providers)

        return context


class LogoutView(auth_views.LogoutView):
    """Signing out is a POST, as Django requires since 5.0."""

    site: Any = None

    def get_default_redirect_url(self) -> str:
        return self.site.get_login_url()


class SetLanguageView(View):
    """Answer the language menu: remember the choice, come back.

    A form post rather than an API call, so it works before any script
    has run and reads as what it is - Django's own ``set_language``, plus
    the saved preference that makes the choice follow the account.
    """

    site: Any = None

    def post(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        language = request.POST.get("language", "")
        response = HttpResponseRedirect(self.redirect_to(request))

        if not is_offered(language):
            return response

        if request.user.is_authenticated:
            UserPreferences.objects.update_or_create(
                user=request.user,
                defaults={"language": language},
            )

        # Also a cookie: it answers for the next request of a visitor
        # who is not signed in, and for the static pages of the frame.
        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME,
            language,
            max_age=settings.LANGUAGE_COOKIE_AGE,
            path=settings.LANGUAGE_COOKIE_PATH,
            domain=settings.LANGUAGE_COOKIE_DOMAIN,
            secure=settings.LANGUAGE_COOKIE_SECURE,
            httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
            samesite=settings.LANGUAGE_COOKIE_SAMESITE,
        )

        return response

    def redirect_to(self, request: Any) -> str:
        """Where the user was, as long as it is this site."""
        target = request.POST.get("next") or request.headers.get("referer", "")

        if target and url_has_allowed_host_and_scheme(
            url=target,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return target

        return (self.site.get_home_url() if self.site else "") or "/"


class PasswordChangeView(SitePageMixin, auth_views.PasswordChangeView):
    template_name = "generic/auth/password_change.html"

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        if request.user.is_authenticated and is_external_account(request.user):
            messages.warning(
                request,
                gettext(
                    "Your account is managed by an external provider "
                    "(directory or single sign-on). Change your password "
                    "there."
                ),
            )

            return HttpResponseRedirect(self.site.get_url("account") or "/")

        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self) -> str:
        return self.site.get_url("password_change_done") or "/"

    def get_page_title(self) -> str:
        return gettext("Change password")

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [
            Breadcrumb(
                label=gettext("Account"),
                url=self.site.get_url("account"),
            ),
            Breadcrumb(label=self.get_page_title()),
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = self.site.get_url("account") or "/"

        return context


class PasswordChangeDoneView(SitePageMixin, auth_views.PasswordChangeDoneView):
    template_name = "generic/auth/password_change_done.html"

    def get_page_title(self) -> str:
        return gettext("Password changed")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["account_url"] = self.site.get_url("account") or "/"

        return context


class AccountView(SiteViewMixin, TemplateView):
    """Profile, preferences, what you watch and security, on one page.

    The two forms are rendered from their API schema by the same code
    as any resource form, and save through the API.
    """

    template_name = "generic/account/settings.html"

    def get_page_title(self) -> str:
        return gettext("Account settings")

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [Breadcrumb(label=self.get_page_title())]

    @staticmethod
    def form_config(object_name: str, schema_name: str) -> dict[str, Any]:
        return {
            "mode": "update",
            "embedded": True,
            "schemaUrl": _reverse(schema_name),
            "objectUrl": _reverse(object_name),
        }

    @staticmethod
    def api_tokens(user: Any) -> dict[str, Any] | None:
        """The API tokens section, where ``generic.tokens`` is installed."""
        from django.apps import apps

        from generic.conf import generic_settings

        url = _reverse("generic:api-token-list")

        if not url or not apps.is_installed("generic.tokens"):
            return None

        return {
            "url": url,
            "canCreate": user.has_perm("generic_tokens.add_apitoken"),
            "defaultDays": generic_settings.API_TOKEN_DEFAULT_DAYS,
            "maxDays": generic_settings.API_TOKEN_MAX_DAYS,
        }

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user

        context.update(
            {
                "profile_config": self.form_config(
                    "generic:profile",
                    "generic:profile-schema",
                ),
                "preferences_config": self.form_config(
                    "generic:preferences",
                    "generic:preferences-schema",
                ),
                "is_external_account": is_external_account(user),
                "can_change_password": not is_external_account(user),
                "api_tokens": self.api_tokens(user),
            }
        )

        return context


class NotificationsView(SiteViewMixin, TemplateView):
    """Every notification the user received, as a table."""

    template_name = "generic/account/notifications.html"

    def get_page_title(self) -> str:
        return gettext("Notifications")

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [Breadcrumb(label=self.get_page_title())]

    def get_columns(self) -> list[dict[str, Any]]:
        columns = NotificationSerializer.get_datatable_columns()

        for column in columns:
            # The title opens whatever the notification is about.
            if column["data"] == "title":
                column.update({"type": "link", "linkField": "url"})

        return columns

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        columns = self.get_columns()
        names = [column["data"] for column in columns]
        order = (
            [[names.index("created_at"), "desc"]]
            if "created_at" in names
            else []
        )

        context["table_config"] = {
            "url": _reverse("generic:notification-list"),
            "columns": columns,
            "options": {
                "pageLength": 25,
                "stateKey": f"{self.site.name}.notifications",
                "order": order,
                "excel": False,
                "csv": False,
                "realtimeEvents": [
                    "notification.created",
                    "notification.updated",
                    "notification.deleted",
                    "notification.read_all",
                ],
            },
        }
        context["read_all_url"] = _reverse("generic:notification-read-all")
        context["write_url"] = self.get_write_url()

        return context

    def get_write_url(self) -> str:
        """Where to write a message, for whoever may send one."""
        from generic.events.models import Message

        resource = self.site.get_resource(Message)

        if resource is None or not resource.has_add_permission(self.request):
            return ""

        return resource.get_add_url()
