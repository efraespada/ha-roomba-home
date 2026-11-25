"""Only restore the missing native zones from an unchanged program selection."""

from dataclasses import replace

import pytest

from custom_components.roomba_home.core.cleaning import CleaningCapabilities, CleaningMode
from custom_components.roomba_home.core.map_programs import (
    matching_zone_destinations,
    review_zone_program,
)
from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind
from custom_components.roomba_home.core.point_maps import FloorPlan, FloorRoom

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
    assert review_zone_program(
        SAVED, current, ZONES, set(ZONES) if matching else set(), floor, CAPABILITIES
    ) == (expected, None, [])


def test_review_preserves_automatic_order_and_refuses_unsupported_cleaning_options():
    status, target, proposed = review_zone_program(
        SAVED, CURRENT, ZONES, set(ZONES), FLOOR, CAPABILITIES
    )
    assert status == "ready" and target.ordered is False
    assert proposed == [
        ROOM | {"name": "Kitchen", "restore": False},
        ZONE | {"name": "Entry", "restore": True},
    ]
    assert review_zone_program(
        SAVED, CURRENT, ZONES, set(ZONES), FLOOR, replace(CAPABILITIES, wetness_levels=1)
    ) == ("unavailable_destination", None, [])


def test_recovery_requires_the_same_boundary_and_zone_coordinates():
    plan = FloorPlan((), border_digest="same boundary")
    assert (
        matching_zone_destinations(replace(plan, border_digest=None), plan, ZONES, ZONES) == set()
    )
    assert (
        matching_zone_destinations(plan, replace(plan, border_digest="elsewhere"), ZONES, ZONES)
        == set()
    )
    assert matching_zone_destinations(plan, plan, ZONES, {}) == set()
    renamed = {key: replace(zone, name="New zone") for key, zone in ZONES.items()}
    assert matching_zone_destinations(plan, plan, ZONES, renamed) == set()
    assert matching_zone_destinations(plan, plan, ZONES, ZONES) == ZONES.keys()
