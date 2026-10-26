"""scripts/ci_report.py: the test statistics and coverage CI summarises.

The reports are written here the way pytest and coverage.py write them,
and the Markdown and JSON read back as the run's summary shows them.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parent.parent
SCRIPT = REPOSITORY / "scripts" / "ci_report.py"

spec = importlib.util.spec_from_file_location("ci_report", SCRIPT)
ci_report = importlib.util.module_from_spec(spec)
# Its dataclasses look their module up by name.
sys.modules["ci_report"] = ci_report
spec.loader.exec_module(ci_report)

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="1" skipped="1"
 tests="5" time="12.5">
<testcase classname="tests.test_access" name="test_open" time="0.5"/>
<testcase classname="tests.api.test_rows.TestRows" name="test_draw"
 time="3.0"/>
<testcase classname="tests.api.test_rows.TestRows" name="test_filter"
 time="1.0"><failure message="assert 1 == 2">boom</failure></testcase>
<testcase classname="tests.wiki.test_pages" name="test_guide" time="0.1">
<skipped message="no wiki"/></testcase>
<testcase classname="tests.wiki.test_pages" name="test_save" time="0.2">
<error message="fixture">broken</error></testcase>
</testsuite></testsuites>
"""

COVERAGE = """<?xml version="1.0" ?>
<coverage line-rate="0.8512" branch-rate="0" lines-valid="200"
 lines-covered="170" branches-valid="0" branches-covered="0">
<packages>
<package name="generic" line-rate="0.9">
<classes>
<class name="views.py" filename="generic/views.py" line-rate="0.95">
<lines><line number="1" hits="1"/><line number="2" hits="1"/></lines>
</class>
<class name="export.py" filename="generic/export.py" line-rate="0.5">
<lines><line number="1" hits="1"/><line number="2" hits="0"/></lines>
</class>
</classes>
</package>
<package name="generic.wiki" line-rate="0.7"><classes/></package>
</packages>
</coverage>
"""


def write(tmp_path: Path) -> tuple[Path, Path]:
    junit = tmp_path / "junit.xml"
    junit.write_text(JUNIT)
    coverage = tmp_path / "coverage.xml"
    coverage.write_text(COVERAGE)
    return junit, coverage


def test_counts_each_outcome_and_the_suites_time(tmp_path):
    junit, _ = write(tmp_path)

    run = ci_report.read_junit(f"Python 3.13={junit}")

    assert run.label == "Python 3.13"
    assert (run.counts.passed, run.counts.failed) == (2, 1)
    assert (run.counts.errors, run.counts.skipped) == (1, 1)
    assert run.counts.seconds == 12.5


def test_groups_tests_by_folder_or_module(tmp_path):
    junit, _ = write(tmp_path)

    run = ci_report.read_junit(str(junit))

    assert sorted(run.areas) == [
        "tests/api",
        "tests/test_access.py",
        "tests/wiki",
    ]
    assert run.areas["tests/api"].total == 2


def test_lists_the_slowest_tests_first(tmp_path):
    junit, _ = write(tmp_path)

    run = ci_report.read_junit(str(junit))

    assert run.slowest[0] == (3.0, "tests.api.test_rows.TestRows::test_draw")


def test_reads_the_coverage_per_package_and_least_covered_file(tmp_path):
    _, coverage = write(tmp_path)

    figures = ci_report.read_coverage(str(coverage))

    assert figures["lines"] == 85.1
    assert [p["name"] for p in figures["packages"]] == [
        "generic",
        "generic.wiki",
    ]
    assert figures["least_covered"][0]["file"] == "generic/export.py"


def test_the_markdown_says_the_totals_and_the_coverage(tmp_path, capsys):
    junit, coverage = write(tmp_path)

    ci_report.main(
        ["--junit", f"A={junit}", "--junit", f"B={junit}"]
        + ["--coverage", str(coverage), "--title", "Report"]
    )
    out = capsys.readouterr().out

    assert out.startswith("## Report")
    assert "**10 tests**: 4 passed, 2 failed, 2 errors, 2 skipped" in out
    assert "| :x: **All** | 10 | 4 | 2 | 2 | 2 | 25.0 s |" in out
    assert "**Coverage**: 85.1% of lines (170 of 200)." in out


def test_a_missing_report_is_said_not_raised(tmp_path, capsys):
    ci_report.main(
        ["--junit", f"Browser={tmp_path / 'none.xml'}"]
        + ["--coverage", str(tmp_path / "none.xml")]
    )

    assert "No test report for *Browser*" in capsys.readouterr().out


def test_writes_the_figures_as_json(tmp_path, capsys):
    junit, coverage = write(tmp_path)
    target = tmp_path / "report.json"

    ci_report.main(
        ["--junit", str(junit), "--coverage", str(coverage)]
        + ["--json", str(target)]
    )

    figures = json.loads(target.read_text())
    assert figures["runs"][0]["total"] == 5
    assert figures["runs"][0]["areas"]["tests/wiki"]["errors"] == 1
    assert figures["coverage"]["lines_covered"] == 170
