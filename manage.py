#!/usr/bin/env python
"""Management entry point for the bundled example project.

    python manage.py migrate
    python manage.py seed_example
    python manage.py runserver

Then open http://127.0.0.1:8000/ and sign in as admin / demo.

The development settings unless DJANGO_SETTINGS_MODULE says otherwise:
this is what a developer types. The servers default to production (see
example_project/asgi.py).
"""

import os
import sys


def main() -> None:
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        "example_project.settings.dev",
    )

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
