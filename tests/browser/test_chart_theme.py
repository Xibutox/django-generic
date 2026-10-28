"""A chart's text and the colours its options give follow the theme -
the dark one, and *system* on a dark operating system."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

LIST = "/example/ticket/"

#: A payload whose options give colours as tokens and name points
#: beside them - the minimal example's timeline, in small.
PAYLOAD = {
    "name": "timeline",
    "type": "line",
    "categories": ["Concept"],
    "series": [{"name": "Days", "data": [1]}],
    "value": {"label": "Days", "format": "integer"},
    "options": {
        "series": [
            {
                "name": "Timeline",
                "type": "line",
                "data": [],
                "lineStyle": {"color": "var(--border-strong)"},
                "markLine": {
                    "data": [{"xAxis": 0}],
                    "label": {
                        "formatter": "Today",
                        "color": "var(--color-danger)",
                    },
                },
            },
            {
                "name": "Milestones",
                "type": "scatter",
                "label": {"show": True},
                "data": [{"value": [0, 0], "label": {"position": "top"}}],
            },
        ]
    },
}

BUILD = """payload => {
    const theme = Generic.charts.readTheme();
    const option = Generic.charts.buildOption(payload, theme);
    const resolve = Generic.colors.resolve;
    const [line, points] = option.series;
    return {
        dark: theme.dark,
        secondary: theme.secondary,
        track: line.lineStyle.color,
        border: resolve("var(--border-strong)"),
        today: line.markLine.label.color,
        danger: resolve("var(--color-danger)"),
        halo: line.markLine.label.textBorderWidth,
        label: points.label.color,
        labelHalo: points.label.textBorderWidth,
        point: points.data[0].label.color,
        given: payload.options.series[0].lineStyle.color,
    };
}"""


@pytest.fixture
def signed_in(page, desk, admin, sign_in):
    sign_in(admin)

    return page


@pytest.mark.parametrize(
    "scheme, theme",
    [("dark", None), ("light", "dark"), ("light", None)],
    ids=["system-on-dark", "dark", "light"],
)
def test_text_and_tokens_follow_the_theme(signed_in, scheme, theme):
    page = signed_in
    page.emulate_media(color_scheme=scheme)

    if theme:
        page.add_init_script(
            f"localStorage.setItem('generic.theme', '{theme}')"
        )

    page.goto(LIST)
    expect(page.locator("#datatable tbody tr").first).to_be_visible()

    built = page.evaluate(BUILD, PAYLOAD)

    assert built["dark"] is (scheme == "dark" or theme == "dark"), built
    # The tokens, resolved for the scheme in force.
    assert built["track"] == built["border"], built
    assert built["today"] == built["danger"], built
    # The payload is left as it came: a theme change draws it again.
    assert built["given"] == "var(--border-strong)", built
    # Names beside their marks, in the theme's text, with no halo.
    assert built["label"] == built["secondary"], built
    assert built["point"] == built["secondary"], built
    assert built["labelHalo"] == 0, built
    assert built["halo"] == 0, built
