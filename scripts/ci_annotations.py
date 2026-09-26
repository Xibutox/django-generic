"""Turn pytest's JUnit report into GitHub Actions error annotations.

    pytest --junitxml=junit.xml
    python scripts/ci_annotations.py junit.xml

Each failing test becomes one ``::error`` line, which GitHub shows on
the run's page - to anyone who can see the repository, without opening
the log - and beside the line in a pull request's diff. GitHub keeps
ten per step, so the first ten failures are the ones worth reading.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ElementTree  # nosec B405 - our own report

LIMIT = 10


def escape(text: str) -> str:
    """What an annotation's message may hold: no raw newline or %."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(path: str) -> int:
    tree = ElementTree.parse(path)  # nosec B314 - written by pytest here
    shown = 0

    for case in tree.iter("testcase"):
        problems = case.findall("failure") + case.findall("error")

        for problem in problems:
            if shown == LIMIT:
                return shown

            name = f"{case.get('classname')}::{case.get('name')}"
            message = problem.get("message") or ""
            detail = (problem.text or "").strip().splitlines()[-12:]
            body = escape("\n".join([message, "", *detail])[:2000])
            # A property also escapes what separates properties.
            title = escape(name).replace(":", "%3A").replace(",", "%2C")
            print(f"::error title={title}::{body}")
            shown += 1

    return shown


if __name__ == "__main__":
    print(f"{main(sys.argv[1])} failure(s) annotated.")
