"""Verify application presets against the reported Max 700 controls."""

from dataclasses import replace

from custom_components.roomba_home.compatibility import VALIDATED_MODEL
from custom_components.roomba_home.core.capabilities import DeviceCapabilities
from custom_components.roomba_home.core.cleaning import CleaningCapabilities, CleaningMode
from custom_components.roomba_home.core.routine_presets import (
    routine_presets,
    smart_routine_presets,
)


def supported():
    return DeviceCapabilities(
        routine_presets=True,
        cleaning=CleaningCapabilities(
            modes=frozenset(CleaningMode),
            suction_levels=4,
            wetness_levels=3,
            smart_scrub=True,
            two_pass=True,
            carpet_boost=True,
        ),
    )


def test_fixed_routine_presets_match_the_app_for_each_mode():
    actual = routine_presets(VALIDATED_MODEL, supported())
    assert actual.keys() == {value.value for value in CleaningMode}
    for mode in CleaningMode:
        assert actual[mode.value] == {
            name: {
                "mode": mode.value,
                "suction_level": suction if mode.vacuums else None,
                "wetness_level": water if mode.mops else None,
                "two_pass": two_pass,
                "smart_scrub": False if mode.mops else None,
                "carpet_boost": None,
            }
            for name, suction, water, two_pass in (
                ("light", 1, 1, False),
                ("normal", 2, 2, False),
                ("deep", 4, 3, True),
            )
        }


def test_fixed_routine_presets_require_the_known_model_and_capability():
    caps = supported()
    assert routine_presets("unverified-model", caps) == {}
    assert routine_presets(VALIDATED_MODEL, replace(caps, routine_presets=False)) == {}


def test_fixed_routine_presets_omit_instead_of_modifying_incompatible_recipes():
    caps = supported()
    caps = replace(caps, cleaning=replace(caps.cleaning, suction_levels=2, smart_scrub=False))
    result = routine_presets(VALIDATED_MODEL, caps)
    assert result.keys() == {"vacuum"}
    assert result["vacuum"].keys() == {"light", "normal"}


def test_smart_recommendations_keep_room_differences_and_only_apply_compatible_fields():
    rooms = [
        {
            "id": "floor:rid:one",
            "preferences": {
                "mode": "vacuum_mop",
                "suction_level": 3,
                "wetness_level": 2,
                "smart_scrub": True,
                "carpet_boost": True,
                "two_pass": True,
            },
        },
        {
            "id": "floor:rid:two",
            "preferences": {
                "mode": "vacuum_mop",
                "suction_level": 1,
                "wetness_level": 1,
                "two_pass": False,
            },
        },
        {"id": "floor:rid:three", "preferences": {"mode": "mop", "wetness_level": 2}},
        {"id": "floor:rid:four", "preferences": {"mode": "vacuum", "suction_level": 9}},
        {"id": "floor:rid:five", "preferences": {"mode": "vacuum"}},
        {"id": "floor:rid:six", "preferences": None},
    ]
    caps = supported()
    recipes = smart_routine_presets(VALIDATED_MODEL, caps, rooms)
    assert set(recipes) == {"floor:rid:one", "floor:rid:two", "floor:rid:three"}
    assert recipes["floor:rid:one"]["vacuum"] == {
        "suction_level": 3,
        "two_pass": True,
        "carpet_boost": True,
    }
    assert recipes["floor:rid:one"]["mop"] == {
        "wetness_level": 2,
        "two_pass": True,
        "smart_scrub": True,
    }
    assert recipes["floor:rid:two"]["vacuum_then_mop"] == {
        "suction_level": 1,
        "wetness_level": 1,
        "two_pass": False,
    }
    assert recipes["floor:rid:three"] == {"mop": {"wetness_level": 2}}
    assert smart_routine_presets("unverified-model", caps, rooms) == {}
    unknown = replace(caps, cleaning=replace(caps.cleaning, modes=None))
    assert smart_routine_presets(VALIDATED_MODEL, unknown, rooms) == {}
