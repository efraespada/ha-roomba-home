import pytest

from custom_components.roomba_home.core.maintenance import (
    maintenance_parts,
    parts_catalog_url,
    project_part_references,
)

FILTER_URL = "https://directory.irobotapi.com/v1/ecom/pdp-app/ES/4849940"
GB_FILTER_URL = FILTER_URL.replace("/ES/", "/GB/")
GUIDE_URL = "https://prod-help-content.care.irobotapi.com/web/es/70517.html"


@pytest.mark.parametrize(
    ("country", "language", "suffix"),
    [
        ("ES", "es-ES", "es-es/ES/X185240/parts"),
        ("GB", "en", "en-gb/GB/X185240/parts"),
        ("../invalid", "en", "en-es/ES/X185240/parts"),
        ("US", "../invalid", "en-us/US/X185240/parts"),
    ],
)
def test_parts_catalog_uses_the_market_and_requested_language(country, language, suffix):
    assert parts_catalog_url(country, language, "X185240").endswith(suffix)


def test_catalog_only_exposes_supported_part_references_and_cleans_query_parameters():
    catalog = {
        "parts": [
            None,
            {"part_id": []},
            {"part_id": "unverified-part", "sku": "9999"},
            {
                "part_id": "72",
                "sku": "4849940",
                "buy_url": f"{FILTER_URL}?utm_source=app&locale=es-es&ignored=1#fragment",
            },
            {"part_id": "202", "guide_url": f"{GUIDE_URL}?utm_campaign=extra#fragment"},
            {"part_id": "212", "sku": "../not-an-identifier"},
        ]
    }
    assert project_part_references(catalog, "ES") == {
        "72": {
            "part_sku": "4849940",
            "replacement_url": "https://www.irobot.es/es_ES/4849940.html",
        },
        "202": {"maintenance_guide_url": GUIDE_URL},
    }
    assert project_part_references({}, "ES") == {}


@pytest.mark.parametrize(
    ("url", "market"),
    [
        (None, "ES"),
        ("https://[" + "x" * 520, "ES"),
        ("https://[", "ES"),
        (FILTER_URL.replace("https:", "http:"), "ES"),
        (FILTER_URL.replace("directory.irobotapi.com", "directory.irobotapi.com.evil.test"), "ES"),
        (
            FILTER_URL.replace(
                "directory.irobotapi.com", "@".join(("directory.irobotapi.com", "evil.test"))
            ),
            "ES",
        ),
        (FILTER_URL + "/extra", "ES"),
        (FILTER_URL.replace("4849940", "444888"), "ES"),
        (FILTER_URL, "GB"),
        (FILTER_URL, "../ES"),
    ],
)
def test_a_replacement_url_requires_the_matching_roomba_sku_and_market(url, market):
    result = project_part_references(
        {"parts": [{"part_id": "72", "sku": "4849940", "buy_url": url}]}, market
    )
    assert result == {"72": {"part_sku": "4849940"}}


@pytest.mark.parametrize(("locale", "expected_suffix"), [("en-gb", "?locale=en-gb"), ("ru", "")])
def test_localized_directory_preserves_only_a_supported_locale_and_skips_unknown_guide(
    locale, expected_suffix
):
    catalog = {
        "parts": [
            {
                "part_id": "72",
                "sku": "4849940",
                "buy_url": GB_FILTER_URL + f"?other=value&locale={locale}&utm_medium=app",
            },
            {"part_id": "202", "guide_url": GUIDE_URL.replace("70517.html", "other.html")},
        ]
    }
    assert project_part_references(catalog, "GB") == {
        "72": {"part_sku": "4849940", "replacement_url": GB_FILTER_URL + expected_suffix}
    }


@pytest.mark.parametrize("counters_available", [True, False])
def test_maintenance_rows_preserve_zero_and_include_the_uncounted_dust_bag(counters_available):
    telemetry = {
        "part_references": {"147": {"part_sku": "4849916"}},
        "part_72_usage": 0,
        "part_72_remaining": 32,
        "part_72_count_type": "minutes",
        "private_whole_catalog": {"token": "fixture"},
    }
    parts = maintenance_parts(
        telemetry, dock_recognized=True, counters_available=counters_available
    )
    assert parts == [
        {
            "part": "filter",
            "part_code": "72",
            "dock": False,
            "usage": 0 if counters_available else None,
            "remaining": 32 if counters_available else None,
            "count_type": "minutes" if counters_available else None,
        },
        {
            "part": "dust_bag",
            "part_code": "147",
            "dock": True,
            "usage": None,
            "remaining": None,
            "count_type": None,
            "part_sku": "4849916",
        },
    ]
    assert (
        maintenance_parts(telemetry, dock_recognized=False, counters_available=counters_available)
        == parts[:1]
    )
