# Sessions, pages and passwords

Five settings that protect what the framework cannot protect alone,
each turned on by the project. The example, the document manager and
every project written by `scripts/new_project.py` turn all of them on.

| Protection | What it stops | Turned on by |
| --- | --- | --- |
| [Idle sign-out](#idle-sign-out) | A screen left signed in with nobody in front of it | `SessionIdleMiddleware`, `GENERIC["SESSION_IDLE_MINUTES"]` |
| [Content-Security-Policy](#content-security-policy) | A script injected into a page running there | `CSPMiddleware`, `GENERIC["CONTENT_SECURITY_POLICY"]` |
| [API rate limits](#api-rate-limits) | A script looping on the API taking the server with it | DRF's throttles in `REST_FRAMEWORK` |
| [Argon2](#argon2) | Passwords guessed from a stolen database | `PASSWORD_HASHERS`, the `argon2` extra |
| [Password rules](#password-rules) | `1234` set as somebody's password | `AUTH_PASSWORD_VALIDATORS` |

The [sign-in lock](sso.md#locking-out-guessers) and the
[security events](security-log.md) are on by default.

## Idle sign-out

`SESSION_COOKIE_AGE` bounds a session's whole life - two weeks in
Django, a working day in the examples. `SESSION_IDLE_MINUTES` bounds
the time a session stays signed in while nobody uses it (ISO/IEC 27002
8.5, OWASP ASVS 3.3):

```python
MIDDLEWARE = [
    ...
    "django.contrib.messages.middleware.MessageMiddleware",
    "generic.middleware.SessionIdleMiddleware",  # after the messages
    ...
]

SESSION_COOKIE_AGE = 8 * 60 * 60   # a working day at most

GENERIC = {"SESSION_IDLE_MINUTES": 60}
```

What counts as using it: a page opened, a form sent - any request -
except the ones a page sends by itself. A live table redrawn by an
event, a figure refreshed: those carry `X-Generic-Idle`, how long ago
the reader last clicked, typed or scrolled (the pages' `core.js` sends
it on every request it makes), so a list left open all night keeps
nobody signed in. Another tab in use keeps the session for every tab.

Once the limit has passed, the next request signs the session out with
Django's `logout()` - the [security log](security-log.md) records the
sign-out - and the sign-in page says why. A page whose own request was
refused reloads onto the sign-in page by itself rather than showing
errors (`X-Generic-Signed-Out: idle`). The time is written to the
session at most once a minute.

`None`, the default, keeps a session for `SESSION_COOKIE_AGE`
whatever happens.

## Content-Security-Policy

The policy a browser applies to a page: where scripts, styles, images
and connections may come from. A script injected into a page - a value
shown unescaped somewhere, a library's bug - is refused unless the
policy allows its source, which the recommended one does not:

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "generic.middleware.CSPMiddleware",
    ...
]

GENERIC = {"CONTENT_SECURITY_POLICY": "recommended"}
```

`"recommended"` is `generic.middleware.RECOMMENDED_CSP`:

| Directive | Allows | Why |
| --- | --- | --- |
| `default-src` | `'self'` | Everything is served by the site itself: no CDN |
| `script-src` | `'self' 'unsafe-eval' 'nonce-…'` | The site's files; Alpine's standard build reads `x-` attributes with `Function()`; the page's own inline scripts, by their nonce |
| `style-src` | `'self' 'unsafe-inline'` | The pages and the libraries set `style` attributes |
| `img-src` | `'self' data: blob:` | Icons drawn inline, images previewed before upload |
| `font-src` | `'self' data:` | |
| `connect-src` | `'self'`, `ws://` and `wss://` this host | The API and the events' WebSocket |
| `frame-src`, `worker-src` | `'self'` (and `blob:` for workers) | A file previewed in a frame |
| `object-src` | `'none'` | |
| `base-uri`, `form-action` | `'self'` | |
| `frame-ancestors` | `'self'` | No other site frames these pages |

A dict of your own replaces it; `"'nonce'"` in a list stands for the
request's nonce:

```python
GENERIC = {
    "CONTENT_SECURITY_POLICY": {
        **RECOMMENDED_CSP,  # from generic.middleware
        "img-src": ["'self'", "data:", "https://tiles.example.com"],
    },
}
```

**Inline scripts.** The framework's templates have three, each with
the request's nonce. A project's template that needs one does the
same:

```django
{% load generic_ui %}
<script nonce="{% csp_nonce %}">...</script>
```

Without a policy the attribute does nothing. An `onclick="..."`
attribute never runs under the policy: Alpine's `@click` does.

**Trying it first.** `CONTENT_SECURITY_POLICY_REPORT_ONLY = True` sends
the policy as `Content-Security-Policy-Report-Only`: the browser
blocks nothing and writes in its console what it would have refused.
The example reads it from `DJANGO_CSP_REPORT_ONLY=1`.

An answer that sets a policy of its own keeps it - a file served for
download carries `sandbox`. Django 6's `SECURE_CSP` does the same job;
this one also runs on Django 5.2, and is the one the browser tests run
under, so a page that breaks under it fails CI.

## API rate limits

Django REST framework's throttles, in the project's settings: requests
a minute per signed-in person, and per address for the signed out.

```python
REST_FRAMEWORK = {
    ...
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"user": "600/min", "anon": "60/min"},
}
```

A page asks for its rows, a column's values and its charts - a few
dozen requests - so 600 a minute is never reached by a person; a script
looping on the API with a [token](api.md) slows down (`429 Too Many
Requests`, with `Retry-After`) instead of taking the server with it.
The example reads the rates from `DJANGO_API_RATE_USER` and
`DJANGO_API_RATE_ANON`. The counts live in the cache: a production
with several processes needs a shared one (Redis), as the sign-in lock
does.

## Argon2

Django hashes passwords with PBKDF2 by default; OWASP recommends
Argon2, which a stolen database's hashes resist far better. It needs
`argon2-cffi` - the `argon2` extra - and to be listed first:

```python
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]
```

The others stay listed so the hashes made before still sign in; each
is rehashed with Argon2 at its owner's next sign-in.

## Password rules

`AUTH_PASSWORD_VALIDATORS` is what the People screens and the account
page check a new password against. A project that lists none accepts
anything. The examples list Django's four, twelve characters at least
in the minimal example, the document manager and new projects.
