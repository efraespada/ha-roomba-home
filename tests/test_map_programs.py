"""Capture portable programs and verify repairs to surviving map selections."""

import json
from dataclasses import replace

import pytest

from custom_components.roomba_home.core.cleaning import CleaningCapabilities, CleaningMode
from custom_components.roomba_home.core.map_programs import (
    capture_map_programs,
    matching_backup_destinations,
    review_map_program,
    saved_furniture_destinations,
)
from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind
from custom_components.roomba_home.core.point_maps import FloorPlan, FloorRoom, MapFurniture

ROOM = {"id": "map:rid:room", "mode": "vacuum", "suction_level": 1}
ZONE = {"id": "map:zid:100", "mode": "mop", "wetness_level": 2}
SAVED = {"region_settings": [ROOM, ZONE], "ordered": False}
CURRENT = {"region_settings": [ROOM], "ordered": False}
ZONES = {ZONE["id"]: FloorRoom("Entry", (), "100")}
FLOOR = PersistentMap(
    "map",
    "current",
    "Studio",
    (
        CleaningRegion("room", RegionKind.ROOM, "Kitchen"),
        CleaningRegion("100", RegionKind.ZONE, "Entry"),
    ),
)
CAPABILITIES = CleaningCapabilities(frozenset(CleaningMode), 4, 3)


def test_backup_copies_room_only_programs_and_a_one_time_schedule():
    routine = {
        "id": "routine",
        "name": "Early clean",
        "regions": [ROOM["id"]],
        "region_settings": [ROOM],
        "ordered": False,
        "icon": "🧹",
        "color": "#CBCBFB",
    }
    timing = {"frequency": "once", "weekday": 2, "time": "08:15", "enabled": True}
    schedule = routine | timing | {"id": "schedule", "ordered": True}
    sources = {"routine": [routine], "schedule": [schedule]}
    result = capture_map_programs(FLOOR, FloorPlan(()), sources, [])
    assert result["unchecked"] == []
    recorded_routine, recorded_schedule = result["items"]
    assert recorded_routine["region_settings"] == [ROOM] and recorded_routine["ordered"] is False
    assert recorded_routine["draft"] == {
        "area_names": ["Kitchen"],
        "icon": "🧹",
        "color": "#CBCBFB",
    }
    assert recorded_schedule["draft"] == timing | {"area_names": ["Kitchen"]}


def test_backup_marks_unknown_commands_and_keeps_unresolved_programs_for_relinking():
    unavailable = ROOM | {"id": "map:zid:104"}
    missing_names = {
        "id": "schedule",
        "name": "Morning",
        "regions": [unavailable["id"]],
        "region_settings": [unavailable],
        "weekdays": [2],
        "time": "08:15",
    }
    source = {
        "routine": [{"regions": None}],
        "schedule": [missing_names, missing_names | {"id": "other", "regions": ["other:rid:room"]}],
    }
    result = capture_map_programs(FLOOR, FloorPlan(()), source, [])
    assert result == {
        "items": [
            {
                "kind": "schedule",
                "id": "schedule",
                "name": "Morning",
                "ordered": True,
                "region_settings": [unavailable],
            }
        ],
        "unchecked": ["routine"],
    }


def test_weekly_schedule_backup_survives_json_storage_without_changing_value():
    schedule = {
        "id": "weekly",
        "name": "Weekly clean",
        "regions": [ROOM["id"]],
        "region_settings": [ROOM],
        "weekdays": (1, 5),
        "time": "14:30",
        "enabled": False,
    }
    saved = capture_map_programs(FLOOR, FloorPlan(()), {"schedule": [schedule]}, [])
    assert saved["items"][0]["draft"]["weekdays"] == [1, 5]
    assert json.loads(json.dumps(saved)) == saved


@pytest.mark.parametrize(
    ("current", "matching", "floor", "expected"),
    [
        (None, True, FLOOR, "missing_program"),
        (CURRENT | {"editable": False}, True, FLOOR, "unsupported_selection"),
        (CURRENT | {"region_settings": None}, True, FLOOR, "unsupported_selection"),
        (CURRENT | {"ordered": True}, True, FLOOR, "changed_selection"),
        (CURRENT | {"region_settings": [ZONE]}, True, FLOOR, "changed_selection"),
        (
            CURRENT | {"region_settings": [ROOM | {"suction_level": 3}]},
            True,
            FLOOR,
            "changed_selection",
        ),
        (CURRENT | {"region_settings": [ZONE, ROOM]}, True, FLOOR, "changed_selection"),
        (
            CURRENT | {"region_settings": [ROOM, ZONE | {"id": "map:zid:102"}]},
            True,
            FLOOR,
            "changed_selection",
        ),
        (SAVED, True, FLOOR, "unchanged"),
        (CURRENT, False, FLOOR, "restore_zones_first"),
        (CURRENT, True, replace(FLOOR, regions=FLOOR.regions[1:]), "unavailable_destination"),
    ],
)
def test_review_leaves_other_edits_and_unavailable_destinations_intact(
    current, matching, floor, expected
):
    assert review_map_program(
        SAVED, current, ZONES, set(ZONES) if matching else set(), floor, CAPABILITIES
    ) == (expected, None, [])


def test_review_preserves_automatic_order_and_refuses_unsupported_cleaning_options():
    status, target, proposed = review_map_program(
        SAVED, CURRENT, ZONES, set(ZONES), FLOOR, CAPABILITIES
    )
    assert status == "ready" and target.ordered is False
    assert proposed == [
        ROOM | {"name": "Kitchen", "restore": False},
        ZONE | {"name": "Entry", "restore": True},
    ]
    assert review_map_program(
        SAVED, CURRENT, ZONES, set(ZONES), FLOOR, replace(CAPABILITIES, wetness_levels=1)
    ) == ("unavailable_destination", None, [])


def test_recovery_requires_the_same_boundary_and_zone_coordinates():
    plan = FloorPlan((), border_digest="same boundary")
    assert (
        matching_backup_destinations(replace(plan, border_digest=None), plan, ZONES, ZONES) == set()
    )
    assert (
        matching_backup_destinations(plan, replace(plan, border_digest="elsewhere"), ZONES, ZONES)
        == set()
    )
    assert matching_backup_destinations(plan, plan, ZONES, {}) == set()
    renamed = {key: replace(zone, name="New zone") for key, zone in ZONES.items()}
    assert matching_backup_destinations(plan, plan, ZONES, renamed) == set()
    assert matching_backup_destinations(plan, plan, ZONES, ZONES) == ZONES.keys()


def test_furniture_must_be_recovered_with_its_original_placement_before_relinking():
    outline = ((1, 1), (3, 1), (3, 2), (1, 2))
    chair = MapFurniture("1", "chair/living", "robot", 0, outline)
    unsuitable = replace(chair, identifier="2", kind="unknown")
    archived = FloorPlan((), border_digest="boundary", furniture=(chair, unsuitable))
    identifier = "map:furniture:1"
    original = saved_furniture_destinations("map", archived)
    assert original == {identifier: chair}
    incompatible = replace(chair, source="user")
    active = replace(archived, furniture=(incompatible, unsuitable))
    live_areas = saved_furniture_destinations("map", active)
    assert matching_backup_destinations(archived, active, original, live_areas) == set()
    settings = {"id": identifier, "mode": "mop", "wetness_level": 2}
    saved = {"region_settings": [ROOM, settings], "ordered": True}
    current = {"region_settings": [ROOM]}
    assert review_map_program(saved, current, original, set(), FLOOR, CAPABILITIES) == (
        "restore_areas_first",
        None,
        [],
    )
    assert matching_backup_destinations(archived, archived, original, original) == {identifier}
