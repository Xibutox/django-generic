"""The user guide: in the first wiki from the start, one page per
language, and put back or brought up to date by a command."""

from __future__ import annotations

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from generic.wiki.guide import (
    GUIDE_DIR,
    GUIDE_POSITION,
    GUIDE_SLUGS,
    GUIDES,
    guide_content,
    guide_languages,
    install_user_guide,
)
from generic.wiki.models import Wiki, WikiPage, WikiRevision

pytestmark = [pytest.mark.django_db, pytest.mark.user_guide]


def guide_pages():
    return WikiPage.objects.filter(slug__in=GUIDE_SLUGS)


def test_the_migration_puts_the_guide_in_the_first_wiki():
    # tests/settings.py offers English and French.
    pages = {page.slug: page for page in guide_pages()}

    assert set(pages) == {"user-guide", "guide-utilisateur"}
    assert pages["user-guide"].title == "User guide"
    assert pages["guide-utilisateur"].title == "Guide utilisateur"
    assert {page.wiki.slug for page in pages.values()} == {"main"}
    # After the pages a project writes, in the menu.
    assert pages["user-guide"].position == GUIDE_POSITION


def test_the_guide_is_a_page_like_any_other(auth_client):
    response = auth_client.get("/wiki/main/guide-utilisateur/")

    assert response.status_code == 200
    assert "Filtrer".encode() in response.content
    assert "Ctrl+K".encode() in response.content


@pytest.mark.parametrize("language", sorted(GUIDES))
def test_each_guide_survives_the_cleaning_whole(language):
    raw = (GUIDE_DIR / f"{language}.html").read_text("utf-8")
    content = guide_content(language)

    # Nothing in it is something the editor could not have written: the
    # cleaning takes nothing away.
    assert content == raw
    assert content.count("<h2>") == 14
    assert "<script" not in content


@pytest.mark.parametrize("language", sorted(GUIDES))
def test_both_guides_have_the_same_sections(language):
    other = "en" if language == "fr" else "fr"

    assert guide_content(language).count("<h3>") == guide_content(other).count(
        "<h3>"
    )


@pytest.mark.parametrize(
    "languages, expected",
    [
        (["fr-fr", "en-us"], ["fr", "en"]),
        (["de"], ["en"]),
        (["pt_BR", "fr", "FR"], ["fr"]),
    ],
)
def test_the_languages_are_those_of_the_site_the_guide_is_written_in(
    languages, expected
):
    assert guide_languages(languages) == expected


@override_settings(LANGUAGES=[("de", "German")])
def test_a_site_in_no_language_of_the_guide_gets_it_in_english():
    assert guide_languages() == ["en"]


def test_a_page_already_there_is_left_alone():
    page = WikiPage.objects.get(slug="user-guide")
    page.content = "<p>Our own words.</p>"
    page.save()

    done = install_user_guide()

    assert done["created"] == []
    assert {skipped.slug for skipped in done["skipped"]} == set(GUIDE_SLUGS)
    page.refresh_from_db()
    assert page.content == "<p>Our own words.</p>"


def test_an_update_keeps_the_replaced_text_in_the_history():
    page = WikiPage.objects.get(slug="user-guide")
    page.content = "<p>Outdated.</p>"
    page.save()

    done = install_user_guide(languages=["en"], update=True)

    assert done["updated"] == [page]
    page.refresh_from_db()
    assert page.content == guide_content("en")
    assert WikiRevision.objects.get(page=page).content == "<p>Outdated.</p>"


def test_an_update_of_an_unchanged_guide_writes_nothing():
    done = install_user_guide(update=True)

    assert done["updated"] == []
    assert not WikiRevision.objects.exists()


def test_a_deleted_guide_comes_back_with_the_command():
    guide_pages().delete()

    call_command("wiki_user_guide", "--language", "fr")

    assert list(guide_pages().values_list("slug", flat=True)) == [
        "guide-utilisateur"
    ]


def test_the_command_writes_in_the_wiki_it_is_given():
    handbook = Wiki.objects.create(name="Handbook", slug="handbook")

    call_command("wiki_user_guide", "--wiki", "handbook")

    assert handbook.pages.filter(slug__in=GUIDE_SLUGS).count() == 2


def test_the_command_refuses_an_unknown_wiki_or_language():
    with pytest.raises(CommandError, match="No wiki"):
        call_command("wiki_user_guide", "--wiki", "nowhere")

    with pytest.raises(CommandError, match="not written in de"):
        call_command("wiki_user_guide", "--language", "de")


def test_without_any_wiki_the_first_one_is_made():
    Wiki.objects.all().delete()

    done = install_user_guide(languages=["en"])

    assert done["created"][0].wiki.slug == "main"
