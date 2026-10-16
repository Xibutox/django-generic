#!/usr/bin/env python
"""{{ title }}: the management entry point.

The development settings unless DJANGO_SETTINGS_MODULE says otherwise;
the servers default to production ({{ project }}/asgi.py).
"""

import os
import sys


def main() -> None:
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        "{{ project }}.settings.dev",
    )

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
