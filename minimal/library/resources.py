"""The screens: one line, and the model says the rest (docs/auto.md).

The list, the summary page, the forms, the REST endpoint and the
place in the navigation. Replace it with a ``ModelResource`` to say
the columns, the search and the form by hand.
"""

from generic.sites import auto
from library.models import Book

auto(Book)
