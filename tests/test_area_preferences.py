import pytest

from custom_components.roomba_home.core.area_preferences import read_area_defaults
from custom_components.roomba_home.core.cleaning import CleaningCapabilities, CleaningMode
from custom_components.roomba_home.core.maps import parse_maps

CAPS = CleaningCapabilities(frozenset(CleaningMode), 4, 3, True, True, True)
FIXTURE = {
    "2": {"suctionLevel": 1, "twoPass": False, "profile": "normal"},
    "4": {"padWetness": {"padPlate": 2}, "swScrub": 0, "twoPass": True},
    "6": {"suctionLevel": 1, "padWetness": {"padPlate": 1}, "updated_at": 1700100000},
    "32": {
        "suctionLevel": 3,
        "padWetness": {"padPlate": 2},
        "routine_modified": True,
        "updated_at": 1700000000,
    },
    "512": {"suctionLevel": 2, "padWetness": {"padPlate": 2}, "swScrub": 1},
}


@pytest.mark.parametrize(
    ("last", "expected"),
    [(2, 6), (32, 32), (6, 6)],
)
def test_area_defaults_preserve_both_combined_variants_and_choose_a_known_profile(last, expected):
    defaults = read_area_defaults({"last_operating_mode": last, "operating_mode_defaults": FIXTURE})
    response = defaults.action_response(CAPS)
    profiles = {row["mode_code"]: row for row in response["profiles"]}
    assert response["last_mode_code"] == last
    assert response["last_mode"] == ("vacuum" if last == 2 else "vacuum_mop")
    assert response["preferred"] == {
        "vacuum": 2,
        "mop": 4,
        "vacuum_mop": expected,
        "vacuum_then_mop": 512,
    }
    assert profiles[2]["settings"] == {"mode": "vacuum", "suction_level": 1, "two_pass": False}
    assert profiles[2]["preset"] == "normal"
    assert profiles[2]["updated_at"] is None
    assert profiles[4]["settings"]["smart_scrub"] is False
    assert profiles[6]["settings"]["wetness_level"] == 1
    assert profiles[32]["settings"]["wetness_level"] == 2
    assert profiles[32]["updated_at"] == "2023-11-14T22:13:20+00:00"
    assert profiles[512]["settings"]["mode"] == "vacuum_then_mop"


@pytest.mark.parametrize(
    "entry",
    [
        None,
        6,
        {"operatingMode": 4, "suctionLevel": 3},
        {"profile": "normal"},
        {"unexpected": True},
        {"twoPass": "true"},
    ],
)
def test_invalid_profiles_leave_the_reported_last_mode_available(entry):
    defaults = read_area_defaults(
        {"last_operating_mode": 32, "operating_mode_defaults": {"6": entry, "0": {}}}
    )
    assert defaults.action_response(CAPS) == {
        "last_mode": "vacuum_mop",
        "last_mode_code": 32,
        "profiles": [],
        "preferred": {},
    }


@pytest.mark.parametrize("last", [None, 32.0, "2", True, 3])
def test_absent_or_unrecognized_modes_and_missing_settings_remain_unknown(last):
    assert read_area_defaults({"last_operating_mode": last, "operating_mode_defaults": []}) is None


@pytest.mark.parametrize("stamp", [None, 1700000000])
def test_equally_dated_combined_variants_stay_visible_without_an_inferred_preference(stamp):
    saved = read_area_defaults(
        {
            "operating_mode_defaults": {
                "6": {"suctionLevel": 1, "updated_at": stamp},
                "32": {"suctionLevel": 3, "updated_at": stamp},
            }
        }
    )
    public = saved.action_response(CAPS)
    assert public["last_mode"] is None
    assert public["preferred"] == {}
    assert {item["mode_code"] for item in public["profiles"]} == {6, 32}


def test_one_dated_combined_variant_is_preferred_over_an_undated_variant():
    saved = read_area_defaults(
        {"operating_mode_defaults": {"6": {"suctionLevel": 1}, "32": FIXTURE["32"]}}
    )
    assert saved.action_response(CAPS)["preferred"] == {"vacuum_mop": 32}


def test_profiles_can_be_inspected_when_the_robot_no_longer_advertises_the_settings():
    saved = read_area_defaults({"operating_mode_defaults": FIXTURE})
    public = saved.action_response(CleaningCapabilities(frozenset({CleaningMode.VACUUM}), 4))
    assert len(public["profiles"]) == 5
    assert public["preferred"] == {}


def test_updating_remembered_preferences_does_not_change_map_or_selection_identity():
    def floor(defaults):
        [result] = parse_maps(
            [
                {
                    "p2map_id": "floor",
                    "active_p2mapv_id": "revision",
                    "robot_id": "example",
                    "state": "active",
                    "visible": True,
                    "rooms_metadata": [
                        {
                            "room_id": "room-a",
                            "room_metadata": {
                                "region_type": "rid",
                                "operating_mode_defaults": defaults,
                            },
                        }
                    ],
                }
            ],
            "example",
        )
        return result

    before = floor({"2": FIXTURE["2"]})
    after = floor(FIXTURE)
    assert before.geometry_key == after.geometry_key
    assert before.selection_id == after.selection_id
    assert before.inventory_id == after.inventory_id
    assert before.regions[0].remembered != after.regions[0].remembered
