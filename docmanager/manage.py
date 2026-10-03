#!/usr/bin/env python
"""The document manager's command line: run it from this folder."""

import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docsite.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
