"""Personal API tokens: a script calls the endpoints a page calls.

An optional app, built on django-rest-knox, which stores only a hash of
each token and its expiry. This app adds what a person needs to manage
them - a name, a scope (read only, or read and write), when it was last
used - an *API tokens* section on the account page, and a People screen
where an administrator sees and revokes anyone's::

    INSTALLED_APPS = [..., "knox", "generic.tokens"]
    REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] = [
        "rest_framework.authentication.SessionAuthentication",
        "generic.tokens.authentication.TokenAuthentication",
    ]

A token acts with exactly its owner's permissions: every resource
decides as it always does. Nothing about who may do what is new.
"""
