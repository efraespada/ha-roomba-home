"""Roomba's replacement writes preserve restrictions throughout a zone's lifecycle."""

from dataclasses import replace

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.maps import PersistentMap
from custom_components.roomba_home.core.point_maps import read_floor_plan
from custom_components.roomba_home.core.restriction_edits import (
    RestrictionEdit,
    confirm_restriction_edit,
    prepare_restriction_edit,
    prepare_restriction_restore,
)

MAP = PersistentMap("map-a", "version.42", "Ground floor", ())
RECTANGLE = ((8, 1), (8, 3), (6, 3), (6, 1), (8, 1))
SMALL_RECTANGLE = ((4, 6), (4, 7), (3, 7), (3, 6), (4, 6))
BOUNDS = [6, 1, 8, 3]


def test_restriction_create_resize_and_remove_preserve_other_types(picea_archive, policy_feature):
    room = policy_feature("100", "NoMopZone", [SMALL_RECTANGLE])
    wall = policy_feature("200", "KeepOutZone", [[2, 2], [3, 2]], geometry_type="LineString")
    before = read_floor_plan(picea_archive(restrictions=[room, wall]), MAP)
    create = prepare_restriction_edit(before, "create", None, "keep_out", BOUNDS)
    assert create.request_body() == {
        "edit_cmd": {
            "command": "set_virtual_wall",
            "params": {
                "virwall": [
                    3,
                    ["101", 1, 8, 1, 8, 3, 6, 3, 6, 1],
                    ["100", 6, 4, 6, 4, 7, 3, 7, 3, 6],
                    ["200", 2, 2, 2, 2, 2, 3, 2, 3, 2],
                ]
            },
        },
        "response_type": "binary",
    }
    keep_out = policy_feature("101", "KeepOutZone", [RECTANGLE])
    archive = picea_archive(version="version.43", restrictions=[wall, room, keep_out])
    assert confirm_restriction_edit(archive, MAP, before, create) == "version.43"
    revision = replace(MAP, version_id="version.43")
    active = read_floor_plan(archive, revision)
    update = prepare_restriction_edit(active, "update", "100", None, [3, 6, 4.5, 8])
    assert update.request_body()["edit_cmd"]["params"]["virwall"][2] == [
        "100",
        6,
        4.5,
        6,
        4.5,
        8,
        3,
        8,
        3,
        6,
    ]
    delete = prepare_restriction_edit(active, "delete", "101", None, None)
    assert delete.request_body()["edit_cmd"]["params"]["virwall"][0] == 2
    archive = picea_archive(version="version.44", restrictions=[room, wall])
    assert confirm_restriction_edit(archive, revision, active, delete) == "version.44"


def test_restrictions_can_overlap_and_removing_the_last_sends_a_zero_count(
    picea_archive, policy_feature
):
    room = policy_feature("100", "NoMopZone", [RECTANGLE])
    before = read_floor_plan(picea_archive(restrictions=[room]), MAP)
    create = prepare_restriction_edit(before, "create", None, "keep_out", BOUNDS)
    assert len(create.restrictions) == 2
    delete = prepare_restriction_edit(before, "delete", "100", None, None)
    assert delete.request_body()["edit_cmd"]["params"]["virwall"] == [0]

    def remove_layer(documents):
        del documents["policyZones.geojson"]
        documents["manifest.json"]["features"] = [
            layer
            for layer in documents["manifest.json"]["features"]
            if layer["type"] != "policyZones"
        ]

    empty = picea_archive(version="version.43", mutate=remove_layer)
    assert confirm_restriction_edit(empty, MAP, before, delete) == "version.43"


def test_restore_recreates_restrictions_and_leaves_later_items(picea_archive, policy_feature):
    keep = policy_feature("100", "KeepOutZone", [RECTANGLE])
    mop = policy_feature("101", "NoMopZone", [SMALL_RECTANGLE])
    wall = policy_feature("102", "KeepOutZone", [[2, 2], [3, 2]], geometry_type="LineString")
    newer = policy_feature("103", "NoMopZone", [RECTANGLE])
    moved = policy_feature("100", "KeepOutZone", [SMALL_RECTANGLE])
    active = read_floor_plan(picea_archive(restrictions=[moved, newer]), MAP)
    saved = read_floor_plan(picea_archive(restrictions=[keep, mop, wall]), MAP)
    edit = prepare_restriction_restore(saved, active)
    assert edit.changes(active) == [
        {"id": "100", "kind": "keep_out", "missing": False},
        {"id": "101", "kind": "no_mop", "missing": True},
        {"id": "102", "kind": "wall", "missing": True},
    ]
    payload = edit.request_body()["edit_cmd"]["params"]["virwall"]
    assert payload[0] == 4
    assert [row[:2] for row in payload[1:]] == [["100", 1], ["103", 6], ["101", 6], ["102", 2]]
    assert payload[-1] == ["102", 2, 2, 2, 2, 2, 3, 2, 3, 2]
    archive = picea_archive(version="version.43", restrictions=[keep, newer, mop, wall])
    assert confirm_restriction_edit(archive, MAP, active, edit) == "version.43"
    after = read_floor_plan(archive, replace(MAP, version_id="version.43"))
    assert prepare_restriction_restore(saved, after).changes(after) == []


@pytest.mark.parametrize(
    ("problem", "error"),
    [
        ("saved format", "fully supported"),
        ("current format", "fully supported"),
        ("missing border", "boundary has changed"),
        ("changed border", "boundary has changed"),
        ("incompatible type", "identifier is in use"),
        ("no visible room", "no longer overlaps"),
    ],
)
def test_restore_rejects_unsafe_coordinate_or_identifier_changes(
    picea_archive, policy_feature, problem, error
):
    keep = policy_feature("100", "KeepOutZone", [RECTANGLE])
    saved = read_floor_plan(picea_archive(restrictions=[keep]), MAP)
    current = read_floor_plan(picea_archive(restrictions=[]), MAP)
    if problem == "saved format":
        saved = replace(saved, policy_shapes=None)
    elif problem == "current format":
        current = replace(current, policy_shapes=None)
    elif problem == "missing border":
        saved = replace(saved, border_digest=None)
    elif problem == "changed border":
        current = replace(current, border_digest="another frame")
    elif problem == "incompatible type":
        other = policy_feature("100", "NoMopZone", [RECTANGLE])
        current = read_floor_plan(picea_archive(restrictions=[other]), MAP)
    else:
        current = replace(current, rooms=())
    with pytest.raises(ValueError, match=error):
        prepare_restriction_restore(saved, current)


@pytest.mark.parametrize(
    "problem",
    [
        "duplicate",
        "missing ID",
        "extra fields",
        "no geometry",
        "unknown",
        "triple wall",
        "empty wall",
        "triangle",
        "malformed",
    ],
)
def test_maps_with_non_round_trippable_restrictions_remain_read_only(
    picea_archive, policy_feature, problem
):
    shape = policy_feature("100", "NoMopZone", [RECTANGLE])
    features = [shape]
    if problem == "duplicate":
        features.append(shape)
    if problem == "missing ID":
        del shape["id"]
    if problem == "extra fields":
        shape["properties"]["name"] = "Cannot overwrite this metadata"
    if problem == "no geometry":
        del shape["geometry"]
    if problem == "unknown":
        shape["properties"]["type"] = "FutureZone"
    if problem in {"triple wall", "empty wall"}:
        points = [[0, 0], [0, 0]] if problem == "empty wall" else [[0, 0], [1, 1], [2, 0]]
        features = [policy_feature("100", "KeepOutZone", points, geometry_type="LineString")]
    if problem == "triangle":
        shape["geometry"]["coordinates"] = [[(0, 0), (2, 0), (2, 2), (0, 0)]]
    if problem == "malformed":
        shape["geometry"]["coordinates"] = [[(0, 0)]]
    plan = read_floor_plan(picea_archive(restrictions=features), MAP)
    assert plan.policy_shapes is None
    with pytest.raises(ValueError, match="cannot preserve"):
        prepare_restriction_edit(plan, "create", None, "keep_out", BOUNDS)


@pytest.mark.parametrize(
    ("operation", "identifier", "kind", "bounds", "error"),
    [
        ("create", "100", "keep_out", BOUNDS, "Choose a restriction type"),
        ("create", None, "wall", BOUNDS, "Choose a restriction type"),
        ("create", None, "keep_out", None, "Choose a restriction type"),
        ("update", "missing", None, BOUNDS, "Select an editable"),
        ("update", "200", None, BOUNDS, "Select an editable"),
        ("update", "100", "keep_out", BOUNDS, "Select an editable"),
        ("update", "100", None, None, "move or resize"),
        ("delete", "100", None, BOUNDS, "move or resize"),
        ("rename", "100", None, None, "move or resize"),
        ("create", None, "keep_out", [0, 4, 0, 5], "positive width"),
    ],
)
def test_restriction_edits_require_a_valid_operation_and_target(
    picea_archive, policy_feature, operation, identifier, kind, bounds, error
):
    plan = read_floor_plan(
        picea_archive(
            restrictions=[
                policy_feature("100", "NoMopZone", [RECTANGLE]),
                policy_feature("200", "KeepOutZone", [[2, 2], [3, 2]], geometry_type="LineString"),
            ]
        ),
        MAP,
    )
    with pytest.raises(ValueError, match=error):
        prepare_restriction_edit(plan, operation, identifier, kind, bounds)


@pytest.mark.parametrize(
    "change", ["id", "kind", "point", "order", "room", "unsupported", "length"]
)
def test_restriction_confirmation_rejects_unexpected_changes(picea_archive, policy_feature, change):
    before = read_floor_plan(picea_archive(restrictions=[]), MAP)
    edit = prepare_restriction_edit(before, "create", None, "keep_out", BOUNDS)
    ring = RECTANGLE
    if change == "order":
        ring = (ring[0], ring[2], ring[1], ring[3], ring[0])
    if change == "point":
        ring = tuple((x + 0.2, y) for x, y in ring)
    shape = policy_feature("101" if change == "id" else "100", "KeepOutZone", [ring])
    if change == "kind":
        shape["properties"]["type"] = "NoMopZone"
    if change == "unsupported":
        shape["properties"]["type"] = "Unknown"
    if change == "length":
        (restriction,) = edit.restrictions
        edit = RestrictionEdit((replace(restriction, points=restriction.points[:-1]),))
    archive = picea_archive(split=change == "room", version="version.43", restrictions=[shape])
    with pytest.raises(ProtocolError):
        confirm_restriction_edit(archive, MAP, before, edit)
