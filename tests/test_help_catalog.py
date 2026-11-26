"""Validate model help links and provider error families."""

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.help_catalog import (
    MEDIA_HOST,
    current_help_articles,
    project_help_catalog,
)

MEDIA = f"https://{MEDIA_HOST}"
MANUAL = f"{MEDIA}/files/2025/OGs/NewSeries/Max700C/example.pdf"
ARTICLE = f"{MEDIA}/web/es/10548.html"


def test_verified_catalog_projects_families_and_setup_links():
    result = project_help_catalog(
        {
            "ownersManual": f"{MANUAL}?tracking=example#ignored",
            "customerCareWeb": "https://answers.irobot.com/appanswers",
            "customerCareEmail": "unrequested service contact",
            "otherContent": [
                {"id": "Error 756", "content": f"{MEDIA}/web/es/10756.html"},
                {"id": "Error 48", "content": ARTICLE + "#ignored"},
                {"id": "Charging Error 101", "content": f"{MEDIA}/web/es/10601.html"},
                {"id": "Start-Refuse 48", "content": f"{MEDIA}/web/es/10511.html"},
                {"id": "Provisioning_help", "content": f"{MEDIA}/web/es/10503.html"},
                {"id": "Other", "content": ARTICLE},
                {"id": "Error 9", "content": f"{MEDIA}/wrong"},
                {"id": 353, "content": ARTICLE},
                None,
            ],
        }
    )
    assert result == {
        "manual_url": MANUAL,
        "support_url": "https://answers.irobot.com/appanswers",
        "device_guides": {"wifi_setup": f"{MEDIA}/web/es/10503.html"},
        "articles": [
            {"family": "charging_error", "code": 101, "url": f"{MEDIA}/web/es/10601.html"},
            {"family": "error", "code": 48, "url": ARTICLE},
            {"family": "error", "code": 756, "url": f"{MEDIA}/web/es/10756.html"},
            {"family": "start_refusal", "code": 48, "url": f"{MEDIA}/web/es/10511.html"},
        ],
    }
    assert (
        current_help_articles(
            result["articles"], {"mission": 48, "dock": 756, "readiness": 48, "refill": 756}
        )
        == result["articles"][1:3]
    )
    assert current_help_articles(result["articles"], {"mission": 101}) == result["articles"][:1]
    assert not current_help_articles(result["articles"], {"readiness": 48, "pad_dry": 48})
    ambiguous = result["articles"] + [{"family": "charging_error", "code": 48, "url": ARTICLE}]
    assert not current_help_articles(ambiguous, {"mission": 48})


@pytest.mark.parametrize("locale", ["es", "en-GB", "en-US"])
def test_regional_article_paths_deduplicate_identical_provider_entries(locale):
    url = f"{MEDIA}/web/{locale}/40510.html"
    article = {"id": "Error 510", "content": url}
    result = project_help_catalog({"otherContent": [article, article]})
    assert result["articles"] == [{"family": "error", "code": 510, "url": url}]


@pytest.mark.parametrize("catalog", [None, {}, {"otherContent": None}])
def test_invalid_catalog_is_distinct_from_a_valid_empty_catalog(catalog):
    with pytest.raises(ProtocolError, match="Roomba help catalog"):
        project_help_catalog(catalog)


@pytest.mark.parametrize(
    "url",
    [
        None,
        "x" * 513,
        f"{MEDIA}/files/example.pdf\n",
        "https://[",
        f"http://{MEDIA_HOST}/files/example.pdf",
        "https://example.invalid/files/example.pdf",
        f"https://example.invalid@{MEDIA_HOST}/files/example.pdf",
        f"{MEDIA}/files/../example.pdf",
        f"{MEDIA}/files/%2e%2e/example.pdf",
    ],
)
def test_links_keep_only_verified_https_destinations(url):
    result = project_help_catalog(
        {
            "ownersManual": url,
            "customerCareWeb": "https://answers.irobot.com/another-route",
            "otherContent": [{"id": "Error 48", "content": url}],
        }
    )
    assert result == {
        "manual_url": None,
        "support_url": None,
        "device_guides": {},
        "articles": [],
    }
