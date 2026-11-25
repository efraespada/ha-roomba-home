"""Cleaning zone writes use the verified rectangle protocol and active revision."""

from dataclasses import replace

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind
from custom_components.roomba_home.core.point_maps import read_floor_plan, with_archive_destinations
from custom_components.roomba_home.core.zone_edits import (
    confirm_zone_edit,
    confirm_zone_restore,
    prepare_zone_edit,
    prepare_zone_restore,
    zone_corners,
)

FLOOR = PersistentMap("map-a", "version.42", "Ground floor", ())
RECTANGLE = ((8, 1), (8, 3), (6, 3), (6, 1), (8, 1))
NORTH = ((8, 4), (8, 5), (6, 5), (6, 4), (8, 4))
ROTATED = ((9, 2), (8, 3), (7, 2), (8, 1), (9, 2))


def test_picea_zone_destinations_use_named_rectangles_and_ignore_removed_native_ids(picea_archive):
    floor = replace(
        FLOOR,
        regions=(
            CleaningRegion("100", RegionKind.ZONE, None),
            CleaningRegion("102", RegionKind.ZONE, "Listed name"),
            CleaningRegion("legacy-zone", RegionKind.ZONE, "Legacy"),
        ),
    )
    triangle = ((1, 1), (3, 1), (2, 4), (1, 1))
    archive = picea_archive(
        zones=[
            ("101", "New zone", RECTANGLE),
            ("102", None, RECTANGLE),
            ("103", "Odd shape", triangle),
            ("104", None, RECTANGLE),
            ("third-party", "Unverified ID", RECTANGLE),
        ]
    )
    plan = read_floor_plan(archive, floor)
    result = with_archive_destinations(floor, plan)
    assert [zone for zone in result.regions if zone.kind is RegionKind.ZONE] == [
        floor.regions[1],
        floor.regions[2],
        CleaningRegion("101", RegionKind.ZONE, "New zone"),
    ]


def test_zone_lifecycle_preserves_name_and_shape_until_removed(picea_archive):
    plan = read_floor_plan(picea_archive(), FLOOR)
    add = prepare_zone_edit(FLOOR, plan, "create", None, "  Desk  ", [8, 3, 6, 1])
    assert add.request_body() == {
        "edit_cmd": {
            "command": "set_permanent_area",
            "params": {"area_points": [["100", "Desk", [8, 1, 8, 3, 6, 3, 6, 1]]]},
        },
        "response_type": "binary",
    }
    updated_archive = picea_archive(version="version.43", zones=[("100", "Desk", RECTANGLE)])
    version = confirm_zone_edit(updated_archive, FLOOR, plan, add)
    assert version == "version.43"
    floor = replace(FLOOR, version_id=version)
    plan = read_floor_plan(updated_archive, floor)
    assert plan.unlinked_zone_count == 1
    rename = prepare_zone_edit(floor, plan, "update", "100", "Désk", None)
    assert rename.name == "Désk" and rename.corners == RECTANGLE[:-1]
    move = prepare_zone_edit(floor, plan, "update", "100", "Desk", [5, 1, 7, 3])
    assert move.corners == ((7, 1), (7, 3), (5, 3), (5, 1))
    delete = prepare_zone_edit(floor, plan, "delete", "100", None, None)
    assert delete.request_body() == {
        "edit_cmd": {"command": "del_permanent_area", "params": {"area_ids": ["100"]}},
        "response_type": "binary",
    }
    assert (
        confirm_zone_edit(picea_archive(version="version.44"), floor, plan, delete) == "version.44"
    )


@pytest.mark.parametrize(
    ("bounds", "message"),
    [
        ([5, 1, 7], "finite corners"),
        ([True, 1, 7, 3], "finite corners"),
        ([6, 1, 6, 3], "positive width"),
        ([1, 1, 1.5, 1], "positive width"),
        ([7, 6, 9, 7], "on a visible room"),
        ([1.1, 7.1, 1.9, 7.9], "on a visible room"),
        ([2.1, 2.1, 2.4, 2.4], "restricted areas"),
        ([1, 1, 4.5, 4.5], "restricted areas"),
    ],
)
def test_invalid_zone_outlines_are_rejected(picea_archive, bounds, message):
    plan = read_floor_plan(picea_archive(), FLOOR)
    with pytest.raises(ValueError, match=message):
        prepare_zone_edit(FLOOR, plan, "create", None, "Desk", bounds)


def test_zone_cannot_cross_a_virtual_wall(picea_archive):
    plan = read_floor_plan(picea_archive(), FLOOR)
    plan = replace(plan, virtual_walls=(((7, 0), (7, 4)),))
    with pytest.raises(ValueError, match="virtual walls"):
        prepare_zone_edit(FLOOR, plan, "create", None, "Desk", [6, 1, 8, 3])


@pytest.mark.parametrize("bounds", [[8, 3, 11, 6], [-1, 8, 6, 9]])
def test_app_style_zones_can_extend_past_room_boundaries(picea_archive, bounds):
    plan = read_floor_plan(picea_archive(), FLOOR)
    assert prepare_zone_edit(FLOOR, plan, "create", None, "Desk", bounds).corners[0] == (
        bounds[2],
        bounds[1],
    )


def test_zone_ids_do_not_reuse_active_outlines_or_listed_destinations(picea_archive):
    floor = replace(FLOOR, regions=(CleaningRegion("101", RegionKind.ZONE, "Listed"),))
    plan = read_floor_plan(picea_archive(zones=[("100", None, RECTANGLE)]), floor)
    assert plan.zone_outlines[0].name is None
    assert prepare_zone_edit(floor, plan, "create", None, "Desk", [6, 1, 8, 3]).zone_id == "102"
    full = replace(
        floor, regions=tuple(CleaningRegion(str(i), RegionKind.ZONE, None) for i in range(100, 140))
    )
    with pytest.raises(ValueError, match="no available"):
        prepare_zone_edit(full, plan, "create", None, "Desk", [6, 1, 8, 3])


@pytest.mark.parametrize(
    ("operation", "zone_id", "name", "bounds", "message"),
    [
        ("update", "missing", "Desk", None, "Select a saved"),
        ("unknown", "100", "Desk", None, "Select a saved"),
        ("create", "100", "Desk", [6, 1, 8, 3], "Draw a rectangle"),
        ("create", None, "Desk", None, "Draw a rectangle"),
        ("delete", "100", "Desk", None, "Remove the zone"),
        ("delete", "100", None, [6, 1, 8, 3], "Remove the zone"),
        ("update", "100", None, None, "Enter a cleaning zone name"),
        ("update", "100", " ", None, "Enter a cleaning zone name"),
        ("update", "100", "Excessive-length-name", None, "Enter a cleaning zone name"),
        ("update", "100", "Desk\nname", None, "Enter a cleaning zone name"),
    ],
)
def test_zone_edit_requires_an_explicit_target_and_valid_input(
    picea_archive, operation, zone_id, name, bounds, message
):
    plan = read_floor_plan(picea_archive(zones=[("100", "Desk", RECTANGLE)]), FLOOR)
    with pytest.raises(ValueError, match=message):
        prepare_zone_edit(FLOOR, plan, operation, zone_id, name, bounds)


def test_invalid_zone_shapes_can_be_removed_without_rewriting_their_geometry(picea_archive):
    triangle = ((6, 1), (6, 3), (8, 1), (6, 1))
    plan = read_floor_plan(picea_archive(zones=[("100", "Desk", triangle)]), FLOOR)
    assert not zone_corners(plan.zone_outlines[0])
    assert not zone_corners(replace(plan.zone_outlines[0], polygons=()))
    with pytest.raises(ValueError, match="rectangular outline"):
        prepare_zone_edit(FLOOR, plan, "update", "100", "Shore", None)
    assert prepare_zone_edit(FLOOR, plan, "delete", "100", None, None).zone_id == "100"
    with pytest.raises(ValueError, match="map format"):
        prepare_zone_edit(FLOOR, replace(plan, source_format=None), "delete", "100", None, None)


def test_zone_acknowledgment_rejects_changes_to_other_map_layers(picea_archive):
    plan = read_floor_plan(picea_archive(), FLOOR)
    edit = prepare_zone_edit(FLOOR, plan, "create", None, "Desk", [6, 1, 8, 3])
    with pytest.raises(ProtocolError, match="unexpected changes"):
        confirm_zone_edit(picea_archive(split=True, version="version.43"), FLOOR, plan, edit)
    with pytest.raises(ProtocolError, match="zone name and outline"):
        confirm_zone_edit(picea_archive(version="version.43"), FLOOR, plan, edit)
    with pytest.raises(ProtocolError, match="zone name and outline"):
        confirm_zone_edit(
            picea_archive(
                version="version.43",
                zones=[("100", "Desk", tuple((x, y + 1) for x, y in RECTANGLE))],
            ),
            FLOOR,
            plan,
            edit,
        )
    existing = read_floor_plan(picea_archive(zones=[("100", "Desk", RECTANGLE)]), FLOOR)
    delete = prepare_zone_edit(FLOOR, existing, "delete", "100", None, None)
    with pytest.raises(ProtocolError, match="still shows"):
        confirm_zone_edit(
            picea_archive(version="version.43", zones=[("100", "Desk", RECTANGLE)]),
            FLOOR,
            existing,
            delete,
        )


def test_duplicate_zone_ids_cannot_be_edited(picea_archive):
    with pytest.raises(ProtocolError, match="unique cleaning zone"):
        read_floor_plan(
            picea_archive(zones=[("100", "First", RECTANGLE), ("100", "Second", RECTANGLE)]), FLOOR
        )


def test_restore_replays_changed_and_missing_zones_under_their_original_ids(picea_archive):
    untouched = ("102", "Current zone", NORTH)
    saved_zones = [("100", "Lectúra", RECTANGLE), ("101", "Hall", ROTATED)]
    saved = read_floor_plan(picea_archive(zones=saved_zones), FLOOR)
    current = read_floor_plan(picea_archive(zones=[("100", "Moved", NORTH), untouched]), FLOOR)
    edit = prepare_zone_restore(saved, current)
    assert edit.changes(current) == [
        {
            "id": "100",
            "name": "Lectúra",
            "current_name": "Moved",
            "missing": False,
            "outline_changed": True,
        },
        {
            "id": "101",
            "name": "Hall",
            "current_name": None,
            "missing": True,
            "outline_changed": True,
        },
    ]
    assert edit.request_body()["edit_cmd"]["params"]["area_points"] == [
        [identity, name, [coordinate for point in ring[:-1] for coordinate in point]]
        for identity, name, ring in saved_zones
    ]
    archive = picea_archive(version="version.43", zones=[*saved_zones, untouched])
    assert confirm_zone_restore(archive, FLOOR, current, edit) == "version.43"


def test_zone_restore_leaves_matching_geometry_and_compares_names_independently(picea_archive):
    saved = read_floor_plan(picea_archive(zones=[("100", "Desk", RECTANGLE)]), FLOOR)
    reversed_outline = RECTANGLE[::-1]
    rotated_vertices = read_floor_plan(
        picea_archive(zones=[("100", "Desk", reversed_outline)]), FLOOR
    )
    assert prepare_zone_restore(saved, saved).zones == ()
    assert prepare_zone_restore(saved, rotated_vertices).zones == ()
    rename = read_floor_plan(picea_archive(zones=[("100", "Table", reversed_outline)]), FLOOR)
    [change] = prepare_zone_restore(saved, rename).changes(rename)
    assert change["outline_changed"] is False and change["current_name"] == "Table"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("region_id", "legacy", "supported identifier"),
        ("name", None, "supported identifier"),
        ("name", " ", "supported identifier"),
        ("name", "x" * 17, "supported identifier"),
        ("name", "Bad\nname", "supported identifier"),
        ("polygons", (), "supported identifier"),
        ("polygons", ((((30, 30), (31, 30), (31, 31), (30, 31), (30, 30)),),), "visible room"),
    ],
)
def test_zone_restore_rejects_unsupported_or_outside_archived_zones(
    picea_archive, field, value, message
):
    saved = read_floor_plan(picea_archive(zones=[("100", "Desk", RECTANGLE)]), FLOOR)
    [zone] = saved.zone_outlines
    current = replace(saved, zone_outlines=())
    with pytest.raises(ValueError, match=message):
        prepare_zone_restore(
            replace(saved, zone_outlines=(replace(zone, **{field: value}),)), current
        )


def test_zone_restore_requires_the_original_coordinate_frame_and_active_restrictions(picea_archive):
    saved = read_floor_plan(picea_archive(zones=[("100", "Desk", RECTANGLE)]), FLOOR)
    current = replace(saved, zone_outlines=())
    for archived, active in ((saved, current), (current, saved)):
        with pytest.raises(ValueError, match="map format"):
            prepare_zone_restore(replace(archived, source_format=None), active)
        with pytest.raises(ValueError, match="map format"):
            prepare_zone_restore(archived, replace(active, source_format=None))
    with pytest.raises(ValueError, match="floor boundary"):
        prepare_zone_restore(replace(saved, border_digest=None), current)
    with pytest.raises(ValueError, match="floor boundary"):
        prepare_zone_restore(saved, replace(current, border_digest="different"))
    with pytest.raises(ValueError, match="restricted areas and virtual walls"):
        prepare_zone_restore(saved, replace(current, virtual_walls=(((7, 0), (7, 4)),)))


@pytest.mark.parametrize(
    ("zones", "split", "message"),
    [
        ([], False, "recorded cleaning zone"),
        ([("100", "Wrong name", RECTANGLE)], False, "recorded cleaning zone"),
        ([("100", "Desk", NORTH)], False, "recorded cleaning zone"),
        (
            [("100", "Desk", RECTANGLE), ("102", "Extra zone", NORTH)],
            False,
            "unexpected map changes",
        ),
        ([("100", "Desk", RECTANGLE)], True, "unexpected map changes"),
    ],
)
def test_zone_restore_verifies_every_zone_and_rejects_unrelated_changes(
    picea_archive, zones, split, message
):
    current = read_floor_plan(picea_archive(), FLOOR)
    saved = read_floor_plan(picea_archive(zones=[("100", "Desk", RECTANGLE)]), FLOOR)
    edit = prepare_zone_restore(saved, current)
    with pytest.raises(ProtocolError, match=message):
        confirm_zone_restore(
            picea_archive(version="version.43", zones=zones, split=split), FLOOR, current, edit
        )
