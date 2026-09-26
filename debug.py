#!/usr/bin/env python
"""Run the project under a debugger - VS Code's F5, or any other.

``manage.py runserver`` serves the requests from a child process it
restarts on every change, and a debugger that started the parent never
sees them: its breakpoints are never hit. This runs the same server in
one process, so a breakpoint in a view, a resource, a serializer, a
template or a task stops where it should::

    python debug.py                  runserver on 127.0.0.1:8000
    python debug.py 0.0.0.0:8001     on another address
    python debug.py --reload         with the reloader: the debugger
                                     follows the child (VS Code:
                                     "subProcess": true)
    python debug.py seed_example     any manage.py command, under the
                                     debugger
    python debug.py --listen 0.0.0.0:5678 --wait 0.0.0.0:8000
                                     no debugger started it: one
                                     attaches to port 5678 - in
                                     Docker, from the host; --wait
                                     holds the start until it has

With ``--listen``, run Python with ``-Xfrozen_modules=off`` (3.11 and
later), as a debugger that starts the process does by itself: debugpy
warns otherwise, and would miss a breakpoint in the standard library.

``.vscode/launch.json`` starts each of these. The development settings,
as for manage.py; without a Celery broker a task runs in the request
that sends it, so its breakpoints are hit here too.
"""

from __future__ import annotations

import os
import re
import shlex
import sys

DEFAULT_ADDRESS = "127.0.0.1:8000"
DEFAULT_LISTEN = "5678"

#: ``8000``, ``0.0.0.0:8000``, ``[::1]:8000``: an address for runserver
#: rather than the name of a command.
ADDRESS = re.compile(r"^(\d+|(\[[0-9a-fA-F:]+\]|[\w.\-]+):\d+)$")


def split(line: str, windows: bool = os.name == "nt") -> list[str]:
    """A typed command line as arguments, Windows paths intact."""
    if not windows:
        return shlex.split(line)

    # POSIX rules would read C:\data as an escaped "d": quotes group,
    # backslashes stay.
    return [
        word[1:-1] if len(word) > 1 and word[0] == word[-1] == '"' else word
        for word in shlex.split(line, posix=False)
    ]


def parse(argv: list[str]) -> dict:
    """What was asked: the debugger's options, then the command."""
    arguments = list(argv)

    # VS Code's prompt hands the whole answer over as one argument.
    if len(arguments) == 1 and " " in arguments[0].strip():
        arguments = split(arguments[0])

    options = {"listen": None, "wait": False, "reload": False, "rest": []}
    index = 0

    while index < len(arguments):
        argument = arguments[index]
        index += 1

        if argument == "--listen":
            # Its value when one follows, port 5678 otherwise.
            following = arguments[index] if index < len(arguments) else ""

            if ADDRESS.match(following):
                options["listen"] = following
                index += 1
            else:
                options["listen"] = DEFAULT_LISTEN
        elif argument.startswith("--listen="):
            options["listen"] = argument.split("=", 1)[1]
        elif argument == "--wait":
            options["wait"] = True
        elif argument == "--reload":
            options["reload"] = True
        else:
            options["rest"].append(argument)

    return options


def command_line(rest: list[str], reload: bool) -> list[str]:
    """The manage.py arguments to run."""
    serving = (
        not rest
        or rest[0] == "runserver"
        or rest[0].startswith("-")
        or bool(ADDRESS.match(rest[0]))
    )

    if not serving:
        return list(rest)

    arguments = rest[1:] if rest and rest[0] == "runserver" else list(rest)

    if not any(not argument.startswith("-") for argument in arguments):
        arguments.append(DEFAULT_ADDRESS)

    if not reload and "--noreload" not in arguments:
        arguments.insert(0, "--noreload")

    return ["runserver", *arguments]


def listen_address(value: str) -> tuple[str, int]:
    """``5678``, ``0.0.0.0:5678`` or ``[::]:5678``: where debugpy waits."""
    host, _, port = value.rpartition(":")

    return (host.strip("[]") or "127.0.0.1", int(port))


def attach_point(value: str, wait: bool) -> None:
    """Open a port a debugger attaches to - from the host, into Docker."""
    try:
        import debugpy
    except ImportError:
        sys.exit(
            "debug.py --listen needs debugpy: pip install debugpy "
            "(part of the 'dev' extra)."
        )

    host, port = listen_address(value)
    debugpy.listen((host, port))
    print(f"debugpy listening on {host}:{port}", flush=True)

    if wait:
        print("waiting for a debugger to attach...", flush=True)
        debugpy.wait_for_client()


def main(argv: list[str] | None = None) -> None:
    options = parse(sys.argv[1:] if argv is None else argv)

    if options["listen"] and options["reload"]:
        # The reloader serves from a child it replaces on every change:
        # each would open the port again, and the debugger would lose
        # its process at the first save.
        sys.exit("debug.py: --listen and --reload do not go together.")

    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        "example_project.settings.dev",
    )

    if options["listen"]:
        attach_point(options["listen"], options["wait"])

    arguments = command_line(options["rest"], options["reload"])
    print(
        f"debug.py: manage.py {' '.join(arguments)} "
        f"({os.environ['DJANGO_SETTINGS_MODULE']})",
        flush=True,
    )

    from django.core.management import execute_from_command_line

    execute_from_command_line([sys.argv[0], *arguments])


if __name__ == "__main__":
    main()
