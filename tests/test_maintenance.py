import pytest

from custom_components.roomba_home.core.maintenance import (
    maintenance_parts,
    maintenance_reminders,
    parts_catalog_url,
    project_part_references,
)

FILTER_URL = "https://directory.irobotapi.com/v1/ecom/pdp-app/ES/4849940"
GB_FILTER_URL = FILTER_URL.replace("/ES/", "/GB/")
GUIDE_URL = "https://prod-help-content.care.irobotapi.com/web/es/70517.html"
MODEL = "X185240"
FILTER_DESCRIPTION_ID = "robot_health_filter_dmc"


@pytest.mark.parametrize("dock_recognized", [True, False])
def test_maintenance_reminders_use_only_supported_part_counters(dock_recognized):
    telemetry = {
        "part_67_usage": 99,
        "part_67_remaining": 2,
        "part_72_usage": 100,
        "part_72_category": "replacement",
        "part_148_remaining": 0,
        "part_148_count_type": "combo_missions",
        "part_202_usage": 100,
        "part_202_count_type": "pad_washes_used",
        "part_202_category": "maintenance",
        "part_999_usage": 100,
        "part_references": {"147": {"part_sku": "fixture"}},
    }
    expected = [
        {"part": "filter", "remaining": None, "count_type": None, "category": "replacement"},
        {"part": "mop_roller", "remaining": 0, "count_type": "combo_missions", "category": None},
    ]
    if dock_recognized:
        expected.append(
            {
                "part": "dock_washing_system",
                "remaining": None,
                "count_type": "pad_washes_used",
                "category": "maintenance",
            }
        )
    assert maintenance_reminders(telemetry, dock_recognized=dock_recognized) == expected


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
    assert parts_catalog_url(country, language, MODEL).endswith(suffix)


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
    assert project_part_references(catalog, "ES", model=MODEL) == {
        "72": {
            "part_sku": "4849940",
            "replacement_url": "https://www.irobot.es/es_ES/4849940.html",
        },
        "202": {"maintenance_guide_url": GUIDE_URL},
    }
    assert project_part_references({}, "ES", model=MODEL) == {}


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
        {"parts": [{"part_id": "72", "sku": "4849940", "buy_url": url}]}, market, model=MODEL
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
    assert project_part_references(catalog, "GB", model=MODEL) == {
        "72": {"part_sku": "4849940", "replacement_url": GB_FILTER_URL + expected_suffix}
    }


@pytest.mark.parametrize(
    ("code", "description_id", "article"),
    [
        ("147", "robot_health_bag_dmc", "40350"),
        ("71", "robot_health_main_brushes_description_705_dmc", "70507"),
        ("72", FILTER_DESCRIPTION_ID, "70505"),
        ("67", "robot_health_side_brush_dmc", "31044"),
        ("148", "robot_health_roller_description_705_dmc", "70508"),
        ("212", "robot_health_roller_mop_washing_system_description_705_dmc", None),
        ("202", "robot_health_dock_washing_system_description_705_dmc", None),
    ],
)
def test_catalog_projects_verified_part_guidance(code, description_id, article):
    row = {"part_id": code, "robot_health_description_id": description_id}
    result = project_part_references({"parts": [row]}, "ES", model=MODEL)[code]
    assert result["part_description"]
    if article is None:
        assert "maintenance_guide_url" not in result
    else:
        assert result["maintenance_guide_url"] == (
            f"https://homesupport.irobot.com/articles/en_US/Knowledge/{article}"
        )


@pytest.mark.parametrize(
    ("model", "description_id"),
    [("another-model", FILTER_DESCRIPTION_ID), (MODEL, "other_description"), (MODEL, ["fixture"])],
)
def test_catalog_guidance_requires_the_verified_model_and_description_id(model, description_id):
    row = {"part_id": "72", "robot_health_description_id": description_id, "guide_url": GUIDE_URL}
    assert project_part_references({"parts": [row]}, "ES", model=model) == {
        "72": {"maintenance_guide_url": GUIDE_URL}
    }


def test_catalog_guidance_keeps_the_models_regional_guide_when_one_is_available():
    row = {
        "part_id": "72",
        "robot_health_description_id": FILTER_DESCRIPTION_ID,
        "guide_url": GUIDE_URL,
    }
    result = project_part_references({"parts": [row]}, "ES", model=MODEL)["72"]
    assert result["part_description"].startswith("The filter traps fine debris")
    assert result["maintenance_guide_url"] == GUIDE_URL


@pytest.mark.parametrize("counters_available", [True, False])
@pytest.mark.parametrize("allow_reset", [True, False])
def test_maintenance_rows_preserve_zero_and_include_the_uncounted_dust_bag(
    counters_available, allow_reset
):
    telemetry = {
        "part_references": {"147": {"part_sku": "4849916"}},
        "part_72_usage": 0,
        "part_72_remaining": 32,
        "part_72_count_type": "minutes",
        "private_whole_catalog": {"token": "fixture"},
    }
    parts = maintenance_parts(
        telemetry,
        dock_recognized=True,
        counters_available=counters_available,
        allow_reset=allow_reset,
    )
    assert parts == [
        {
            "part": "filter",
            "part_code": "72",
            "dock": False,
            "usage": 0 if counters_available else None,
            "remaining": 32 if counters_available else None,
            "count_type": "minutes" if counters_available else None,
            "can_reset": counters_available and allow_reset,
        },
        {
            "part": "dust_bag",
            "part_code": "147",
            "dock": True,
            "usage": None,
            "remaining": None,
            "count_type": None,
            "can_reset": False,
            "part_sku": "4849916",
        },
    ]
    assert (
        maintenance_parts(
            telemetry,
            dock_recognized=False,
            counters_available=counters_available,
            allow_reset=allow_reset,
        )
        == parts[:1]
    )
