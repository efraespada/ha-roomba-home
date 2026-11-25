"""Room edits use the geometry and identity of the current revision."""

from dataclasses import replace

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind
from custom_components.roomba_home.core.point_maps import read_floor_plan, with_archive_destinations
from custom_components.roomba_home.core.room_edits import edited_revision, prepare_room_edit

FLOOR = PersistentMap(
    "map-a",
    "version.42",
    "Example floor",
    (
        CleaningRegion("room-a", RegionKind.ROOM, "Office"),
        CleaningRegion("zone-a", RegionKind.ZONE, "Desk"),
    ),
)


def test_split_requires_exactly_two_boundary_crossings(picea_archive):
    plan = read_floor_plan(picea_archive(), FLOOR)
    edit = prepare_room_edit(plan, "split", ["room-a"], [-1, 4, 11, 4])
    assert edit.request_body() == {
        "edit_cmd": {
            "command": "split_room",
            "params": {"room_id": "room-a", "split_points": [-1, 4, 11, 4]},
        },
        "response_type": "binary",
    }
    changed = picea_archive(split=True, version="version.43")
    assert edited_revision(changed, FLOOR, plan, edit) == "version.43"
    # The app sends handles inside the room and the provider extends their line.
    assert prepare_room_edit(plan, "split", ["room-a"], [1, 4, 9, 4]).divider == ((1, 4), (9, 4))


@pytest.mark.parametrize(
    "points",
    [
        None,
        [-1, 7.5, 6, 7.5],
        [-5, 4, -3, 4],
        [-1, 15, 11, 15],
        [-1, 4, 11, float("nan")],
        [-1, 4, True, 4],
        [-1, 4, -1, 4],
        [-1, 0, 11, 0],
    ],
)
def test_room_split_rejects_invalid_dividers(picea_archive, points):
    plan = read_floor_plan(picea_archive(), FLOOR)
    with pytest.raises(ValueError):
        prepare_room_edit(plan, "split", ["room-a"], points)


def test_merge_requires_mutual_adjacency_and_reconciles_the_active_archive(picea_archive):
    plan = read_floor_plan(picea_archive(split=True), FLOOR)
    merged = prepare_room_edit(plan, "merge", ["room-a", "room-b"], None)
    assert merged.request_body() == {
        "edit_cmd": {"command": "arrange_room", "params": {"room_ids": ["room-a", "room-b"]}},
        "response_type": "binary",
    }
    changed = picea_archive(version="version.43")
    assert edited_revision(changed, FLOOR, plan, merged) == "version.43"

    floor_with_stale_inventory = with_archive_destinations(FLOOR, plan)
    assert floor_with_stale_inventory.regions == (
        CleaningRegion("room-a", RegionKind.ROOM, "Office north"),
        FLOOR.regions[1],
        CleaningRegion("room-b", RegionKind.ROOM, "Office south"),
    )
    current_floor = replace(floor_with_stale_inventory, version_id="version.43")
    assert (
        with_archive_destinations(current_floor, read_floor_plan(changed, current_floor)).regions
        == FLOOR.regions
    )

    one_way = replace(plan, rooms=(plan.rooms[0], replace(plan.rooms[1], adjacent=frozenset())))
    with pytest.raises(ValueError, match="adjacent"):
        prepare_room_edit(one_way, "merge", ["room-a", "room-b"], None)
    with pytest.raises(ValueError, match="Select visible"):
        prepare_room_edit(plan, "merge", ["room-a", "missing"], None)
    with pytest.raises(ValueError, match="map format"):
        prepare_room_edit(replace(plan, source_format=None), "merge", ["room-a", "room-b"], None)

    with pytest.raises(ValueError, match="one room"):
        prepare_room_edit(plan, "split", ["room-a", "room-b"], [-1, 4, 11, 4])


def test_inventory_is_preserved_without_visible_picea_rooms(picea_archive):
    plan = read_floor_plan(picea_archive(), FLOOR)
    unavailable = replace(plan, rooms=(replace(plan.rooms[0], visible=False),))
    assert with_archive_destinations(FLOOR, unavailable) is FLOOR


@pytest.mark.parametrize(
    ("map_id", "version", "split"),
    [
        ("other-map", "version.43", True),
        ("map-a", "version.42", True),
        ("map-a", "version.43", False),
    ],
)
def test_acknowledgement_must_have_expected_map_revision_and_room_count(
    picea_archive, map_id, version, split
):
    plan = read_floor_plan(picea_archive(), FLOOR)
    edit = prepare_room_edit(plan, "split", ["room-a"], [-1, 4, 11, 4])
    invalid = picea_archive(split=split, map_id=map_id, version=version)
    with pytest.raises(ProtocolError):
        edited_revision(invalid, FLOOR, plan, edit)


def test_rename_preserves_room_ids_and_confirms_name_and_type(picea_archive):
    archive = picea_archive(split=True)
    plan = read_floor_plan(archive, FLOOR)
    edit = prepare_room_edit(plan, "rename", ["room-b"], None, "Comedor", "diningRoom")
    assert edit.request_body() == {
        "edit_cmd": {
            "command": "set_room_metadata",
            "params": {
                "room_id": "room-b",
                "room_metadata": {"name": "Comedor", "type": "diningRoom"},
            },
        },
        "response_type": "binary",
    }
    custom = prepare_room_edit(plan, "rename", ["room-b"], None, "Estudio Ático ")
    assert custom.name == "Estudio Ático "
    assert custom.room_type == "other"

    def rename(documents):
        properties = documents["rooms.geojson"]["features"][1]["properties"]
        properties.update(name=edit.name, type={"value": "diningRoom", "source": "user"})

    renamed = picea_archive(split=True, version="version.43", mutate=rename)
    assert edited_revision(renamed, FLOOR, plan, edit) == "version.43"


@pytest.mark.parametrize(
    ("operation", "room_ids", "points", "name", "room_type", "error"),
    [
        ("rename", ["room-a", "room-b"], None, "Office", None, "one room"),
        ("rename", ["room-a"], [1, 2, 3, 4], "Office", None, "one room"),
        ("rename", ["room-a"], None, None, None, "room name"),
        ("rename", ["room-a"], None, "   ", None, "room name"),
        ("rename", ["room-a"], None, "x" * 32, None, "room name"),
        ("rename", ["room-a"], None, "Room\nname", None, "room name"),
        ("rename", ["room-a"], None, "Office", [], "room type"),
        ("rename", ["room-a"], None, "Office", "unknown", "room type"),
        ("merge", ["room-a", "room-b"], None, "Office", None, "only"),
        ("split", ["room-a"], None, None, "other", "only"),
    ],
)
def test_room_rename_requires_a_name_type_and_one_visible_room(
    picea_archive, operation, room_ids, points, name, room_type, error
):
    plan = read_floor_plan(picea_archive(split=True), FLOOR)
    with pytest.raises(ValueError, match=error):
        prepare_room_edit(plan, operation, room_ids, points, name, room_type)


@pytest.mark.parametrize("unconfirmed", ["name", "type", "room", "zone", "border"])
def test_rename_rejects_changed_geometry_or_wrong_metadata(picea_archive, unconfirmed):
    before = read_floor_plan(picea_archive(split=True), FLOOR)
    edit = prepare_room_edit(before, "rename", ["room-b"], None, "Bedroom", "bedroom")

    def change(documents):
        other, target = documents["rooms.geojson"]["features"]
        target["properties"]["name"] = "Other name" if unconfirmed == "name" else edit.name
        target["properties"]["type"] = {"value": 0 if unconfirmed == "type" else "bedroom"}
        if unconfirmed == "room":
            other["properties"]["name"] = "Unexpected name"
        if unconfirmed == "border":
            documents["borders.geojson"]["geometry"]["coordinates"][0][0][1][0] -= 1

    options = {}
    if unconfirmed == "zone":
        ring = ((8, 1), (8, 2), (7, 2), (7, 1), (8, 1))
        options["zones"] = [("101", "Desk", ring)]
    invalid = picea_archive(split=True, version="version.43", mutate=change, **options)
    with pytest.raises(ProtocolError, match="name and type"):
        edited_revision(invalid, FLOOR, before, edit)
