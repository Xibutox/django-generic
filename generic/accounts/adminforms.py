"""The Django admin's sign-in form, behind the site's lock.

The admin has a password form of its own. Left as Django ships it, an
account locked on the site's sign-in page could still be guessed
through ``/admin/login/``. ``GenericConfig.ready()`` gives this form to
the default admin site; a project that built another ``AdminSite`` sets
it there itself::

    from generic.accounts.adminforms import (
        ThrottledAdminAuthenticationForm,
    )

    my_admin = MyAdminSite()
    my_admin.login_form = ThrottledAdminAuthenticationForm

Imported only where ``django.contrib.admin`` is installed.
"""

from __future__ import annotations

from django.contrib.admin.forms import AdminAuthenticationForm

from generic.accounts.views import ThrottledSignInMixin


class ThrottledAdminAuthenticationForm(
    ThrottledSignInMixin, AdminAuthenticationForm
):
    """Counts failed passwords, refuses a locked account or address."""


__all__ = ["ThrottledAdminAuthenticationForm"]
