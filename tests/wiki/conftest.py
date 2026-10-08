"""The wiki's tests start from wikis without the user guide.

The migration writes the guide into the first wiki; the tests here
count pages and read menus, so it is taken out again - except for the
tests marked ``user_guide`` (test_guide.py), which are about it.
"""

import pytest


@pytest.fixture(autouse=True)
def no_user_guide(request):
    uses_the_database = request.node.get_closest_marker("django_db") or (
        {"db", "transactional_db"} & set(request.fixturenames)
    )

    if request.node.get_closest_marker("user_guide") or not uses_the_database:
        return

    from generic.wiki.guide import GUIDE_SLUGS
    from generic.wiki.models import WikiPage

    request.getfixturevalue("db")
    WikiPage.objects.filter(slug__in=GUIDE_SLUGS).delete()
