"""Floor settings use the native angle without changing cleaning destinations."""

from dataclasses import replace
from math import pi, tau

import pytest

from custom_components.roomba_home.core.floor_settings import (
    prepare_floor_settings,
    prepare_floor_settings_restore,
)
from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind

FLOOR = PersistentMap(
    "map-a", "version.42", "Example floor", (CleaningRegion("room-a", RegionKind.ROOM, "Office"),)
)


def test_rename_preserves_the_exact_label_and_checks_unmodified_settings():
    edit = prepare_floor_settings(FLOOR, "rename", "Ático ", None)
    assert edit.request_body() == {"name": "Ático "}
    renamed = replace(FLOOR, name="Ático ")
    assert edit.matches(FLOOR, renamed)
    assert renamed.settings_id != FLOOR.settings_id
    assert renamed.inventory_id == FLOOR.inventory_id
    assert not edit.matches(FLOOR, replace(renamed, orientation=pi / 2))
    assert not edit.matches(FLOOR, replace(renamed, name="Another name"))
    assert not edit.matches(FLOOR, replace(renamed, regions=()))


def test_initial_floor_name_follows_the_mapping_wizards_twenty_character_limit():
    floor = replace(FLOOR, name=None)
    name = "Mapa temporal Á 0001"
    assert len(name) == 20
    assert prepare_floor_settings(floor, "rename", name, None).request_body() == {"name": name}
    with pytest.raises(ValueError, match="up to 20"):
        prepare_floor_settings(floor, "rename", name + "1", None)


def test_rotation_moves_clockwise_and_accepts_equivalent_angles():
    rotated = prepare_floor_settings(FLOOR, "rotate", None, 1)
    assert rotated.request_body() == {"user_orientation_rad": pytest.approx(-pi / 2)}
    assert not rotated.matches(FLOOR, FLOOR)
    assert rotated.matches(FLOOR, replace(FLOOR, orientation=3 * pi / 2))
    assert not rotated.matches(FLOOR, replace(FLOOR, orientation=-pi / 2 + 0.00001))
    assert not rotated.matches(FLOOR, replace(FLOOR, orientation=-pi / 2, name="Wrong floor"))

    before = replace(FLOOR, orientation=-pi + 0.0000002)
    back = prepare_floor_settings(before, "rotate", None, 3)
    assert back.orientation == pytest.approx(-pi / 2 + 0.0000002)


@pytest.mark.parametrize(
    ("operation", "name", "turns", "error"),
    [
        ("rename", "", None, "floor name"),
        ("rename", None, None, "floor name"),
        ("rename", "x" * 17, None, "floor name"),
        ("rename", "Name\n", None, "floor name"),
        ("rename", "Office", 1, "floor name"),
        ("rotate", "Office", 1, "quarter-turns"),
        ("rotate", None, True, "quarter-turns"),
        ("rotate", None, 0, "quarter-turns"),
        ("rotate", None, 4, "quarter-turns"),
        ("rename and rotate", None, 1, "quarter-turns"),
    ],
)
def test_settings_require_one_supported_value(operation, name, turns, error):
    with pytest.raises(ValueError, match=error):
        prepare_floor_settings(FLOOR, operation, name, turns)


def test_restore_combines_recorded_name_and_orientation_across_revisions():
    current = replace(FLOOR, orientation=pi / 2)
    saved = replace(FLOOR, version_id="older", name="Mapa temporal Á 0001", orientation=0)
    edit = prepare_floor_settings_restore(current, saved)
    assert edit.request_body() == {"name": saved.name, "user_orientation_rad": 0}
    assert edit.matches(current, replace(current, name=saved.name, orientation=0))
    assert not edit.matches(current, saved)


@pytest.mark.parametrize("angle", [None, pi / 2 - tau])
def test_restore_only_uses_recorded_and_changed_floor_settings(angle):
    current = replace(FLOOR, orientation=pi / 2)
    saved = replace(FLOOR, name=None, orientation=angle)
    assert prepare_floor_settings_restore(current, saved).request_body() == {}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"map_id": "different"}, "active floor"),
        ({"name": 7}, "supported name"),
        ({"name": " "}, "supported name"),
        ({"name": "Name\n"}, "supported name"),
        ({"name": "x" * 21}, "supported name"),
        ({"orientation": True}, "invalid floor orientation"),
        ({"orientation": float("inf")}, "invalid floor orientation"),
    ],
)
def test_restore_rejects_invalid_backup_settings_or_other_floor(changes, message):
    with pytest.raises(ValueError, match=message):
        prepare_floor_settings_restore(FLOOR, replace(FLOOR, **changes))
