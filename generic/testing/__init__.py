"""Testing a project built on django-generic.

:class:`PageSweep` opens every page of the project three ways and every
generated endpoint behind them, from about ten lines::

    # tests/test_pages.py
    import pytest
    from generic.testing import PageSweep


    class TestEveryPage(PageSweep):
        @pytest.fixture
        def records(self, db):
            return {"library.book": Book.objects.create(title="Dune")}

It needs pytest and pytest-django, which the application itself never
does: importing this module is the only place they are asked for.
"""

from __future__ import annotations

try:
    import pytest  # noqa: F401
    import pytest_django  # noqa: F401
except ImportError as error:  # pragma: no cover - an environment's
    raise ImportError(
        "generic.testing needs pytest and pytest-django: "
        "pip install pytest pytest-django."
    ) from error

from generic.testing.pages import PageSweep, discover, is_api, walk

__all__ = ["PageSweep", "discover", "is_api", "walk"]
