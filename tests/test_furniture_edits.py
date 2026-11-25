"""Verify furniture geometry, whole-layer edits, and read-back reconciliation."""

from dataclasses import replace
from math import pi
from unittest.mock import patch

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.furniture_edits import (
    can_edit_furniture,
    confirm_furniture_edit,
    furniture_pose,
    prepare_furniture_edit,
)
from custom_components.roomba_home.core.maps import PersistentMap
from custom_components.roomba_home.core.point_maps import read_floor_plan

MAP = PersistentMap("map-a", "version.42", "Ground floor", ())
NEXT_MAP = replace(MAP, version_id="version.43")
BASE_RING = ((1, 1), (3, 1), (3, 2), (1, 2))
POSE = [5, 4, 2, 1, 0]
PLACED = ((4, 3.5), (6, 3.5), (6, 4.5), (4, 4.5))


def test_full_lifecycle_retains_sources_and_cleans_up_the_object(picea_archive, furniture_feature):
    detected = furniture_feature(
        "1", "cabinet/tv", "robot", BASE_RING, pi, [*BASE_RING, BASE_RING[0]]
    )
    existing = furniture_feature("3", "sofa", "user", BASE_RING)
    plan = read_floor_plan(picea_archive(furniture=[detected, existing]), MAP)
    assert can_edit_furniture(plan)
    assert furniture_pose(plan.furniture[0]) == (2, 1.5, 2, 1, 180)
    assert plan.furniture[0].cleaning_area == (((*BASE_RING, BASE_RING[0]),),)
    create = prepare_furniture_edit(plan, "create", None, "chair/living", POSE)
    with patch(
        "custom_components.roomba_home.core.furniture_edits.time", return_value=1720000000.8
    ):
        assert create.request_body() == {
            "edit_cmd": {
                "command": "adjust_furniture",
                "params": {
                    "timestamp": 1720000000,
                    "furniture_list": [
                        ["1", 1520, 0, 1, 1, 3, 1, 3, 2, 1, 2],
                        ["3", 1525, 1, 1, 1, 3, 1, 3, 2, 1, 2],
                        ["2", 1528, 1, 4, 3.5, 6, 3.5, 6, 4.5, 4, 4.5],
                    ],
                    "package": [1, 1],
                },
            },
            "response_type": "binary",
        }
    chair = furniture_feature("2", "chair/living", "user", PLACED)
    data = picea_archive(version=NEXT_MAP.version_id, furniture=[chair, detected, existing])
    assert confirm_furniture_edit(data, MAP, plan, create) == NEXT_MAP.version_id
    active = read_floor_plan(data, NEXT_MAP)
    update = prepare_furniture_edit(active, "update", "2", None, [4, 5, 1, 2, 90])
    assert update.changed.kind == create.changed.kind
    assert update.changed.identifier == "2"
    assert update.changed.points == ((5, 4.5), (5, 5.5), (3, 5.5), (3, 4.5))
    assert update.changed.orientation == pi / 2
    new_version = "version.44"
    chair = furniture_feature("2", "chair/living", "user", update.changed.points, pi / 2)
    rotated = picea_archive(version=new_version, furniture=[detected, existing, chair])
    assert confirm_furniture_edit(rotated, NEXT_MAP, active, update) == new_version
    floor = replace(MAP, version_id=new_version)
    active = read_floor_plan(rotated, floor)
    removal = prepare_furniture_edit(active, "delete", "2", None, None)
    sent = removal.request_body()["edit_cmd"]["params"]["furniture_list"]
    assert sent[-1] == ["0", 1528, 1, 5, 4.5, 5, 5.5, 3, 5.5, 3, 4.5]
    assert sent[0][2] == 0
    restored = picea_archive(version="version.45", furniture=[detected, existing])
    assert confirm_furniture_edit(restored, floor, active, removal) == "version.45"


@pytest.mark.parametrize(
    ("operation", "identifier", "kind", "pose"),
    [
        ("create", "1", "chair/living", POSE),
        ("create", None, "alien", POSE),
        ("create", None, "chair/living", None),
        ("create", None, "chair/living", [1, 2, 3]),
        ("create", None, "chair/living", [True, 4, 2, 1, 0]),
        ("create", None, "chair/living", [5, 4, -1, 2, 0]),
        ("create", None, "chair/living", [5, 4, 2, 0, 0]),
        ("create", None, "chair/living", [5, 4, 1, 2, 361]),
        ("create", None, "chair/living", [7, 4, 1e-20, 2, 0]),
        ("create", None, "chair/living", [1e9, 4, 5, 2, 0]),
        ("create", None, "chair/living", [50, 40, 1, 2, 0]),
        ("update", "missing", None, POSE),
        ("update", "1", "sofa", POSE),
        ("update", "1", None, None),
        ("delete", "1", None, POSE),
        ("other", "1", None, POSE),
    ],
)
def test_rejects_invalid_edits(picea_archive, furniture_feature, operation, identifier, kind, pose):
    item = furniture_feature("1", "cabinet/tv", "robot", BASE_RING)
    plan = read_floor_plan(picea_archive(furniture=[item]), MAP)
    with pytest.raises(ValueError):
        prepare_furniture_edit(plan, operation, identifier, kind, pose)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("id", 3),
        ("id", "0"),
        ("properties", None),
        ("properties", {"type": "sofa", "source": "robot", "orientation": 0, "extra": 0}),
        ("properties", {"type": " ", "source": "robot", "orientation": 0}),
        ("properties", {"type": "sofa", "source": "inferred", "orientation": 0}),
        ("properties", {"type": "sofa", "source": "robot", "orientation": True}),
        ("properties", {"type": "sofa", "source": "robot"}),
        ("geometry", {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}),
        ("geometry", {"type": "Polygon", "coordinates": [[[1, 1], [2, 2], [3, 1], [1, 1]]]}),
    ],
)
def test_unpreservable_objects_disable_edits(picea_archive, furniture_feature, key, value):
    item = furniture_feature("1", "sofa", "robot", BASE_RING)
    plan = read_floor_plan(picea_archive(furniture=[item | {key: value}]), MAP)
    assert plan.furniture is None
    assert not can_edit_furniture(plan)
    with pytest.raises(ValueError, match="preserve"):
        prepare_furniture_edit(plan, "delete", "1", None, None)


def test_duplicate_is_unreadable_and_unknown_catalog_type_is_read_only(
    picea_archive, furniture_feature
):
    item = furniture_feature("1", "unknown", "robot", BASE_RING)
    assert read_floor_plan(picea_archive(furniture=[item, item]), MAP).furniture is None
    plan = read_floor_plan(picea_archive(furniture=[item]), MAP)
    assert len(plan.furniture) == 1
    assert not can_edit_furniture(plan)


def test_allows_roomba_to_recompute_a_retained_objects_cleaning_area(
    picea_archive, furniture_feature
):
    original = furniture_feature("1", "sofa", "robot", BASE_RING)
    plan = read_floor_plan(picea_archive(furniture=[original]), MAP)
    create = prepare_furniture_edit(plan, "create", None, "chair/living", POSE)
    with_derived_area = furniture_feature(
        "1", "sofa", "robot", BASE_RING, area=[*PLACED, PLACED[0]]
    )
    created = furniture_feature("2", "chair/living", "user", PLACED)
    data = picea_archive(version=NEXT_MAP.version_id, furniture=[with_derived_area, created])
    assert confirm_furniture_edit(data, MAP, plan, create) == NEXT_MAP.version_id


@pytest.mark.parametrize(
    "problem", ["missing", "type", "heading", "shifted", "edited source", "geometry", "malformed"]
)
def test_requires_expected_new_pose_and_preserved_layer(picea_archive, furniture_feature, problem):
    original = furniture_feature("1", "sofa", "robot", BASE_RING)
    plan = read_floor_plan(picea_archive(furniture=[original]), MAP)
    changed = prepare_furniture_edit(plan, "create", None, "chair/living", POSE)
    item = furniture_feature(
        "2",
        "table/dining" if problem == "type" else "chair/living",
        "user",
        BASE_RING if problem == "shifted" else PLACED,
        0.3 if problem == "heading" else 0,
    )
    if problem == "edited source":
        original["properties"]["source"] = "user"
    if problem == "malformed":
        original["properties"] = None
    archive = picea_archive(
        version=NEXT_MAP.version_id,
        furniture=[original] if problem == "missing" else [original, item],
        split=problem == "geometry",
    )
    with pytest.raises(ProtocolError):
        confirm_furniture_edit(archive, MAP, plan, changed)
