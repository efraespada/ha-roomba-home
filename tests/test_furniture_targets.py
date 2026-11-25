"""Check temporary furniture regions, ordered profiles, and lossless routine projection."""

import json
from dataclasses import replace

import pytest

from custom_components.roomba_home.core.cleaning import CleaningMode, CleaningProfile
from custom_components.roomba_home.core.commands import Command, command_body
from custom_components.roomba_home.core.furniture_targets import furniture_links, furniture_regions
from custom_components.roomba_home.core.maps import AreaTarget, CleaningRegion, RegionKind
from custom_components.roomba_home.core.point_maps import FloorPlan, MapFurniture
from custom_components.roomba_home.core.routines import (
    CleaningRoutine,
    routine_command,
    routine_matches,
)

RING = ((0, 1), (4, 1), (4, 3), (0, 3))
PADDED = ((-0.4, 0.6), (4.4, 0.6), (4.4, 3.4), (-0.4, 3.4))
SOFA = MapFurniture("1", "sofa", "robot", 0, RING)
CHAIR = MapFurniture("2", "chair/living", "user", 0, RING)
ROOM = CleaningRegion("5", RegionKind.ROOM, "Office")
VACUUM = CleaningProfile(CleaningMode.VACUUM, suction_level=1)
COMBINED = CleaningProfile(CleaningMode.VACUUM_MOP, suction_level=3, wetness_level=2)
SEQUENTIAL = CleaningProfile(CleaningMode.VACUUM_THEN_MOP, wetness_level=2)
TARGET = AreaTarget(
    "floor",
    "revision.1",
    (
        furniture_regions(FloorPlan((), furniture=(SOFA,)))[0],
        ROOM,
        furniture_regions(FloorPlan((), furniture=(CHAIR,)))[0],
    ),
    (COMBINED, VACUUM, SEQUENTIAL),
)


def test_expands_valid_footprints_without_changing_the_current_map():
    same_type = replace(SOFA, identifier="7", points=((0, 0), (0, 2), (-1, 2), (-1, 0)))
    invalid = [
        replace(CHAIR, kind="unknown"),
        replace(CHAIR, points=((0, 0), (0, 0), (2, 3), (0, 3))),
        replace(CHAIR, points=((0, 0), (2, 0), (1, 3), (0, 3))),
        replace(CHAIR, points=((0, 0), (2, 0), (3, 3), (1, 3))),
        replace(CHAIR, points=((0, 0), (2, 0), (2, 0), (0, 0))),
    ]
    items = furniture_regions(FloorPlan((), furniture=(SOFA, *invalid, same_type)))
    assert [(r.segment_id("floor"), r.name) for r in items] == [
        ("floor:furniture:1", "Sofa"),
        ("floor:furniture:7", "Sofa 2"),
    ]
    assert items[0].outline == PADDED
    assert items[1].outline == ((0.4, -0.4), (0.4, 2.4), (-1.4, 2.4), (-1.4, -0.4))
    assert furniture_regions(FloorPlan(())) == ()


def test_routine_and_mission_preserve_mixed_order_and_profiles():
    expected_regions = [
        {
            "region_id": "160",
            "type": "tid",
            "params": {"suctionLevel": 3, "operatingMode": 6, "padWetness": {"padPlate": 2}},
        },
        {"region_id": "5", "type": "rid", "params": {"suctionLevel": 1, "operatingMode": 2}},
        {
            "region_id": "161",
            "type": "tid",
            "params": {
                "operatingMode": 512,
                "padWetness": {"padPlate": 2},
                "routine_modified": True,
            },
        },
    ]
    document = routine_command("robot", TARGET, 1100)
    assert document["regions"] == expected_regions
    assert document["id_multipolys"] == [
        {
            "id": str(160 + index),
            "metadata": {"furniture_id": str(index + 1)},
            "poly": [list(p) for p in PADDED],
        }
        for index in range(2)
    ]
    assert document["ordered"] == 1
    assert "select_all" not in document
    mission = json.loads(command_body(Command.VACUUM, 1100, target=TARGET))
    assert mission == {
        key: val for key, val in document.items() if key not in {"robot_id", "regions"}
    } | {
        "regions": [
            *expected_regions[:2],
            expected_regions[2] | {"params": {"operatingMode": 512, "padWetness": {"padPlate": 2}}},
        ]
    }
    with pytest.raises(ValueError, match="profile"):
        command_body(Command.VACUUM, 1100, target=replace(TARGET, profiles=()))
    with pytest.raises(ValueError, match="timestamp"):
        routine_command("robot", TARGET, True)
    with pytest.raises(ValueError, match="timestamp"):
        routine_command("robot", TARGET, 0)


def test_preserves_native_identifiers_and_projection_after_timestamp_changes():
    document = routine_command("robot", TARGET, 1100)
    routine = CleaningRoutine("draft", "Example", {"commanddefs": [document]})
    response = routine.action_response()
    assert response["regions"] == ["floor:furniture:1", "floor:rid:5", "floor:furniture:2"]
    assert [r["suction_level"] for r in response["region_settings"]] == [3, 1, None]
    assert routine_matches(routine, "Example", document | {"time": 1200}, regenerated=True)
    assert not routine_matches(routine, "Example", document | {"time": 1200})
    assert not routine_matches(routine, "Example", document | {"ordered": 0}, regenerated=True)


@pytest.mark.parametrize(
    "changed",
    [
        {"initiator": "cloud"},
        {"time": True},
        {"time": 0},
        {"extra": "unknown"},
        {
            "id_multipolys": [
                {"id": "162", "metadata": {"furniture_id": "9"}, "poly": [list(p) for p in PADDED]}
            ]
        },
    ],
)
def test_only_round_trips_recognized_furniture_commands(changed):
    command = routine_command("robot", TARGET, 1100)
    if "id_multipolys" in changed:
        changed = {"id_multipolys": [*command["id_multipolys"], *changed["id_multipolys"]]}
    routine = CleaningRoutine("draft", "Example", {"commanddefs": [command | changed]})
    assert routine.action_response()["region_settings"] is None


@pytest.mark.parametrize(
    "changed",
    [
        False,
        {"extra": True},
        {"id": []},
        {"metadata": []},
        {"metadata": {"furniture_id": "1", "extra": "unknown"}},
        {"metadata": {"furniture_id": "../"}},
        {"poly": False},
        {"poly": [[1, 1]]},
        {"poly": [[1, 1], [2], [3, 3], [4, 4]]},
        {"poly": [[1, 1], True, [3, 3], [4, 4]]},
        {"poly": [[1, 1], [2, 2], [3, True], [4, 4]]},
        {"poly": [[1, 1], [2, 2], [3, 3], [1, 1]]},
    ],
)
def test_invalid_polygon_metadata_remains_unresolved(changed):
    first = routine_command("robot", TARGET, 1100)["id_multipolys"][0]
    malformed = first | changed if isinstance(changed, dict) else changed
    assert furniture_links([malformed]) == {}
    assert furniture_links([first, first]) == {}
    assert furniture_links(None) == {}
    command = routine_command("robot", TARGET, 1100)
    command["regions"][0]["region_id"] = []
    routine = CleaningRoutine("draft", "Example", {"commanddefs": [command]})
    assert routine.action_response()["region_settings"] is None
