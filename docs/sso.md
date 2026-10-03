# Signing in through somebody else

The framework speaks no OIDC and no SAML, and should not: a project
picks a library — `mozilla-django-oidc`, `django-allauth`,
`djangosaml2`, a reverse proxy — and that library owns the protocol,
the keys and the callback.

What the framework owns is the **door**. Declare a provider and the
sign-in page leads with it:

```python
# myapp/resources.py, or anywhere imported at start-up
from generic.sites import site

site.add_sso_provider(
    _("Microsoft Entra ID"),
    route="oidc_authentication_init",       # mozilla-django-oidc
    icon="corporate_fare",
    description=_("Use your work account."),
)
```

```
┌──────────────────────────────────────┐
│  Sign in                             │
│  Continue with your organisation's   │
│  account.                            │
│                                      │
│  ┌────────────────────────────────┐  │
│  │  🏢  Microsoft Entra ID        │  │   ← first, and primary
│  └────────────────────────────────┘  │
│       Use your work account.         │
│  ──────────────────────────────────  │
│      🔑 Sign in with a password      │   ← folded away
│  ▸                        instead    │
└──────────────────────────────────────┘
```

With no provider declared the page is exactly what it always was: the
username and password form, nothing folded.

## Declaring one

| Option | Means |
| --- | --- |
| `route` | a URL name the library serves — resolved when the page is drawn |
| `url` | a literal address instead, for a proxy or another host |
| `icon`, `description` | what the button shows, and the line under it |
| `order` | which provider comes first |
| `next_param` | what the provider's view calls the page to come back to; `"next"` by default, `""` for a library that keeps its own state |

The same thing from settings, for a project that would rather
configure than declare:

```python
GENERIC = {
    "SSO_PROVIDERS": [
        {"label": "Entra ID", "route": "oidc_authentication_init",
         "icon": "corporate_fare"},
    ],
}
```

The two add up, and several providers are fine — each gets its own
button, in `order`.

## Where it sends people

The destination travels with the link: somebody who was opening
`/example/ticket/42/` when they were asked to sign in comes back to it,
because the button carries `?next=/example/ticket/42/`.

Django validates that destination before the page is rendered, so an
address pointing off this site is dropped rather than passed on — the
button is not a way around a check the form already makes.

## Forbidding local passwords

```python
GENERIC = {"SSO_PASSWORD_LOGIN": False}
```

The form goes entirely and the page says the application keeps no
passwords of its own.

**One exception, deliberately**: when no provider is declared, the form
comes back whatever the setting says. A sign-in page offering no way in
is a locked door, not a security measure — and the likeliest cause is a
provider whose library is not installed in this environment.

For the same reason, a provider whose `route` does not resolve is left
out quietly instead of raising: the one page nobody can sign in without
should not be the page that breaks when a dependency is missing.

## Locking out guessers

The password form counts failures. After `LOGIN_MAX_ATTEMPTS` (5) in a
row on one account, that account is refused for
`LOGIN_LOCKOUT_MINUTES` (15) - without the password even being checked,
so the right one does not get through either, and the page says to try
again later. One address failing on any accounts is locked after four
times as many. A successful sign-in clears the account's count.

```python
GENERIC = {"LOGIN_MAX_ATTEMPTS": 10, "LOGIN_LOCKOUT_MINUTES": 30}
GENERIC = {"LOGIN_MAX_ATTEMPTS": None}   # no lock
```

- The counts live in Django's cache. The default local-memory cache is
  per process: give a production with several workers a shared one
  (Redis, the database).
- The address is `REMOTE_ADDR`. Behind a proxy that is the proxy's, so
  every visitor shares it: set `REMOTE_ADDR` from the proxy's header
  in a middleware of your own if you rely on the address count.
- Only the local password form is counted: a provider's sign-in is its
  own (and so is its second factor).
- Reaching the limit writes a warning in the `generic` log.

## Wiring a real provider

The framework needs nothing beyond the declaration. For
`mozilla-django-oidc`, the rest is that library's own setup:

```python
INSTALLED_APPS += ["mozilla_django_oidc"]
AUTHENTICATION_BACKENDS = [
    "myproject.auth.MyOIDCBackend",          # subclasses OIDCAuthenticationBackend
    "django.contrib.auth.backends.ModelBackend",   # keep for local accounts
]
urlpatterns += [path("oidc/", include("mozilla_django_oidc.urls"))]
```

```python
site.add_sso_provider(_("Entra ID"), route="oidc_authentication_init")
```

Two things worth deciding while you are there, neither of which the
framework decides for you:

- **Whether a new account is created on first sign-in**, and with what
  permissions. The library's backend hook is where that happens; give
  it a group rather than a list of permissions, so the answer is in one
  place ([People](people.md)).
- **What the accounts look like afterwards.** An account created by a
  provider has no usable password, which the framework already reads as
  *externally managed*: its name and address are shown read-only on the
  account page, since the provider would overwrite them at the next
  sign-in.

## Signing out

Django's `LOGOUT_REDIRECT_URL` decides where signing out lands. Sending
people to the provider's own end-session endpoint — so they are signed
out *there* as well — is the library's business; point that setting at
whatever URL it documents.

## In the example

The example declares one provider so the page can be seen doing what it
does. It points at a page of the example that explains what a real
provider would do next — it signs nobody in, because a demo that let
people in without a password would be teaching the wrong thing.

Open `/login/` signed out: the button first, the password form folded
underneath, and `admin` / `demo` still works through it.

The minimal example does it for real, with django-allauth and
Microsoft Entra ID: given an app registration in its environment, its
sign-in page leads with *Microsoft* and signs people in. The settings,
the URLs and the Azure side are in
[its README](../minimal/README.md#signing-in-with-microsoft).
