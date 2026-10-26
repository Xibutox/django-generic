"""Test statistics and coverage, as a Markdown report for CI.

    pytest --junitxml=junit.xml --cov-report=xml
    python scripts/ci_report.py --junit junit.xml --coverage coverage.xml
    python scripts/ci_report.py --junit "Postgres 16=pg16/junit.xml" \\
        --junit "Browser=browser/junit.xml" --json report.json

Reads pytest's JUnit reports (one per run, each optionally labelled
``LABEL=PATH``) and coverage.py's XML (Cobertura) report, and prints
Markdown: how many tests passed, failed, errored and were skipped, and
in how long; the same per run and per area of the suite (``tests/api``,
``tests/test_access.py``...); the slowest tests; the coverage, in
total, per package and for the least covered files. CI appends it to
the job's summary (``$GITHUB_STEP_SUMMARY``), shown on the run's page.

``--json`` also writes the figures, for a script or a trend to read.
A missing report is said in the output rather than failing: the step
runs after a failure too, when pytest may not have written one.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ElementTree  # nosec B405 - our own reports
from dataclasses import asdict, dataclass, field
from pathlib import Path

OUTCOMES = ("passed", "failed", "errors", "skipped")
SLOWEST = 10
LEAST_COVERED = 10


@dataclass
class Counts:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    seconds: float = 0.0

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors + self.skipped

    def add(self, outcome: str, seconds: float) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)
        self.seconds += seconds

    def merge(self, other: Counts) -> None:
        for outcome in OUTCOMES:
            setattr(
                self, outcome, getattr(self, outcome) + getattr(other, outcome)
            )
        self.seconds += other.seconds


@dataclass
class Run:
    label: str
    found: bool = True
    counts: Counts = field(default_factory=Counts)
    areas: dict[str, Counts] = field(default_factory=dict)
    # (seconds, test id), slowest first.
    slowest: list[tuple[float, str]] = field(default_factory=list)


def outcome_of(case: ElementTree.Element) -> str:
    if case.find("failure") is not None:
        return "failed"
    if case.find("error") is not None:
        return "errors"
    if case.find("skipped") is not None:
        return "skipped"
    return "passed"


def area_of(classname: str) -> str:
    """``tests.api.test_rows.TestX`` -> ``tests/api``;
    ``tests.test_access`` -> ``tests/test_access.py``."""
    parts = [part for part in classname.split(".") if part]
    if not parts:
        return "(unknown)"
    if len(parts) == 1:
        return parts[0]
    root, second = parts[0], parts[1]
    if second.startswith("test_"):
        return f"{root}/{second}.py"
    return f"{root}/{second}"


def read_junit(spec: str) -> Run:
    label, _, path = spec.rpartition("=")
    report = Path(path)
    run = Run(label=label or report.parent.name or report.stem)
    if not report.is_file():
        run.found = False
        return run

    tree = ElementTree.parse(report)  # nosec B314 - written by pytest here
    timings = []
    for case in tree.iter("testcase"):
        seconds = float(case.get("time") or 0)
        classname = case.get("classname") or ""
        outcome = outcome_of(case)
        run.counts.add(outcome, seconds)
        run.areas.setdefault(area_of(classname), Counts()).add(
            outcome, seconds
        )
        timings.append((seconds, f"{classname}::{case.get('name')}"))

    # The suite's own time includes the set-up the cases do not.
    suites = list(tree.iter("testsuite"))
    if suites:
        run.counts.seconds = sum(float(s.get("time") or 0) for s in suites)
    run.slowest = sorted(timings, reverse=True)[:SLOWEST]
    return run


def read_coverage(path: str) -> dict | None:
    report = Path(path)
    if not report.is_file():
        return None
    root = ElementTree.parse(report).getroot()  # nosec B314 - ours

    def rate(element: ElementTree.Element, name: str) -> float:
        return round(float(element.get(name) or 0) * 100, 1)

    packages = []
    files = []
    for package in root.iter("package"):
        packages.append(
            {"name": package.get("name"), "lines": rate(package, "line-rate")}
        )
        for cls in package.iter("class"):
            lines = cls.find("lines")
            count = 0 if lines is None else len(lines.findall("line"))
            if count:
                files.append(
                    {
                        "file": cls.get("filename"),
                        "lines": rate(cls, "line-rate"),
                        "statements": count,
                    }
                )

    packages.sort(key=lambda p: p["name"] or "")
    files.sort(key=lambda f: (f["lines"], -f["statements"]))
    return {
        "lines": rate(root, "line-rate"),
        "branches": rate(root, "branch-rate"),
        "lines_valid": int(root.get("lines-valid") or 0),
        "lines_covered": int(root.get("lines-covered") or 0),
        "branches_valid": int(root.get("branches-valid") or 0),
        "packages": packages,
        "least_covered": files[:LEAST_COVERED],
    }


def duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} min {rest:02d} s"


def status(counts: Counts) -> str:
    return ":x:" if counts.failed or counts.errors else ":white_check_mark:"


def counts_row(name: str, counts: Counts) -> str:
    cells = [str(getattr(counts, outcome)) for outcome in OUTCOMES]
    return (
        f"| {status(counts)} {name} | {counts.total} | "
        + " | ".join(cells)
        + f" | {duration(counts.seconds)} |"
    )


COUNTS_HEADER = [
    "| | Tests | Passed | Failed | Errors | Skipped | Time |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
]


def markdown(runs: list[Run], coverage: dict | None, title: str) -> str:
    out = [f"## {title}", ""]
    found = [run for run in runs if run.found]
    total = Counts()
    for run in found:
        total.merge(run.counts)

    for run in runs:
        if not run.found:
            out.append(f"> :warning: No test report for *{run.label}*.")
            out.append("")

    if found:
        out.append(
            f"**{total.total} tests**: {total.passed} passed, "
            f"{total.failed} failed, {total.errors} errors, "
            f"{total.skipped} skipped, in {duration(total.seconds)}."
        )
        out += ["", *COUNTS_HEADER]
        for run in found:
            out.append(counts_row(run.label, run.counts))
        if len(found) > 1:
            out.append(counts_row("**All**", total))
        out.append("")

        areas: dict[str, Counts] = {}
        for run in found:
            for name, counts in run.areas.items():
                areas.setdefault(name, Counts()).merge(counts)
        out += ["<details><summary>Per area</summary>", "", *COUNTS_HEADER]
        for name in sorted(areas):
            out.append(counts_row(f"`{name}`", areas[name]))
        out += ["", "</details>", ""]

        slowest = sorted(
            (item for run in found for item in run.slowest), reverse=True
        )[:SLOWEST]
        out += [
            f"<details><summary>The {len(slowest)} slowest tests" "</summary>",
            "",
            "| Time | Test |",
            "| ---: | --- |",
        ]
        for seconds, name in slowest:
            out.append(f"| {seconds:.2f} s | `{name}` |")
        out += ["", "</details>", ""]

    if coverage:
        out.append(
            f"**Coverage**: {coverage['lines']}% of lines "
            f"({coverage['lines_covered']} of {coverage['lines_valid']})"
            + (
                f", {coverage['branches']}% of branches."
                if coverage["branches_valid"]
                else "."
            )
        )
        out += [
            "",
            "<details><summary>Per package</summary>",
            "",
            "| Package | Lines |",
            "| --- | ---: |",
        ]
        for package in coverage["packages"]:
            out.append(f"| `{package['name']}` | {package['lines']}% |")
        out += [
            "",
            "</details>",
            "",
            "<details><summary>Least covered files</summary>",
            "",
            "| File | Lines | Statements |",
            "| --- | ---: | ---: |",
        ]
        for item in coverage["least_covered"]:
            out.append(
                f"| `{item['file']}` | {item['lines']}% "
                f"| {item['statements']} |"
            )
        out += ["", "</details>", ""]

    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--junit",
        action="append",
        default=[],
        metavar="[LABEL=]PATH",
        help="a pytest JUnit report; repeat for several runs",
    )
    parser.add_argument("--coverage", help="coverage.py's XML report")
    parser.add_argument("--title", default="Tests")
    parser.add_argument("--json", help="also write the figures here")
    args = parser.parse_args(argv)

    runs = [read_junit(spec) for spec in args.junit]
    coverage = read_coverage(args.coverage) if args.coverage else None
    print(markdown(runs, coverage, args.title))

    if args.json:
        figures = {
            "runs": [
                {
                    "label": run.label,
                    "found": run.found,
                    **asdict(run.counts),
                    "total": run.counts.total,
                    "areas": {
                        name: asdict(counts)
                        for name, counts in sorted(run.areas.items())
                    },
                    "slowest": [
                        {"seconds": seconds, "test": name}
                        for seconds, name in run.slowest
                    ],
                }
                for run in runs
            ],
            "coverage": coverage,
        }
        Path(args.json).write_text(json.dumps(figures, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
