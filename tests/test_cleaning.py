"""Cleaning policy and protocol contracts, without network or a physical robot."""

from dataclasses import replace
from itertools import product

import pytest

from custom_components.roomba_home.core.cleaning import (
    CleaningCapabilities,
    CleaningMode,
    CleaningProfile,
)
from custom_components.roomba_home.core.cleaning_protocol import (
    cleaning_capabilities,
    cleaning_parameters,
)
from custom_components.roomba_home.core.settings_protocol import RobotSetting

FULL = CleaningCapabilities(frozenset(CleaningMode), 4, 3, True, True, True)
CAP = {"oMode": 550, "suctionLvl": 4, "ppWetLvl": 3, "scrub": 3, "multiPass": 1, "carpetBoost": 3}


def test_sdk_capability_contract_does_not_confuse_support_and_command_codes():
    assert cleaning_capabilities(CAP) == FULL
    assert cleaning_capabilities({"oMode": 6}).modes == {CleaningMode.VACUUM, CleaningMode.MOP}
    assert cleaning_capabilities({"oMode": 32}).modes == {CleaningMode.VACUUM_MOP}


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        "550",
        {},
        {key: True for key in CAP},
        {key: -1 for key in CAP},
        {key: "4" for key in CAP},
    ],
)
def test_malformed_capabilities_do_not_enable_controls(raw):
    assert cleaning_capabilities(raw) == CleaningCapabilities()


@pytest.mark.parametrize(
    "scrub,multipass,expected",
    [
        (0, 0, (False, False)),
        (1, 3, (False, False)),
        (2, 2, (True, True)),
        (3, 1, (True, True)),
        (99, 99, (None, None)),
    ],
)
def test_sdk_enumerated_capability_support_is_not_truthiness(scrub, multipass, expected):
    result = cleaning_capabilities({"scrub": scrub, "multiPass": multipass})
    assert (result.smart_scrub, result.two_pass) == expected


@pytest.mark.parametrize(
    ("code", "area_supported"),
    [(0, False), (1, None), (2, True), (3, None), ("2", None), (True, None), (None, None)],
)
def test_auto_evacuation_area_requires_confirmed_capability_scheme(code, area_supported):
    assert cleaning_capabilities({"autoevac": code}).auto_evacuation_area is area_supported


@pytest.mark.parametrize(
    ("value", "allowed"),
    [
        (0, True),
        (1, False),
        (2, False),
        (9, False),
        (10, True),
        (50, True),
        (1000, True),
        (1001, False),
        ("50", False),
        (50.0, False),
        (True, False),
        (False, False),
        (4, False),
    ],
)
def test_emptying_setting_validates_routine_code_and_native_area_range(value, allowed):
    setting = RobotSetting.AUTO_EVACUATION_AREA
    caps = cleaning_capabilities({"autoevac": 2})
    assert setting.accepts(value, caps) is allowed
    assert setting.observed({setting.value: value}, caps) == (value if allowed else None)
    assert not setting.accepts(value, cleaning_capabilities({"autoevac": 0}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "mop"),
        ("mode", 4),
        *product(["suction_level", "wetness_level"], [0, -1, True, 1.5, "2"]),
        *product(["smart_scrub", "two_pass", "carpet_boost"], [0, 1, "true"]),
    ],
)
def test_profiles_reject_coercions_and_invalid_types(field, value):
    with pytest.raises(ValueError):
        CleaningProfile(**{field: value})


@pytest.mark.parametrize(
    "profile,capabilities",
    [
        (CleaningProfile(), CleaningCapabilities()),
        (CleaningProfile(suction_level=5), FULL),
        (CleaningProfile(wetness_level=4), FULL),
        (CleaningProfile(smart_scrub=False), replace(FULL, smart_scrub=False)),
        (CleaningProfile(two_pass=True), replace(FULL, two_pass=False)),
        (CleaningProfile(carpet_boost=False), replace(FULL, carpet_boost=False)),
    ],
)
def test_unsupported_preferences_are_rejected_before_transport(profile, capabilities):
    with pytest.raises(ValueError):
        profile.validate(capabilities)


@pytest.mark.parametrize(
    "mode,invalid_preferences",
    [
        (CleaningMode.VACUUM, {"wetness_level": 1, "smart_scrub": True}),
        (CleaningMode.MOP, {"suction_level": 1, "carpet_boost": True}),
    ],
)
def test_mode_family_limits_even_explicitly_declared_cleaning_preferences(
    mode, invalid_preferences
):
    capabilities = replace(FULL, modes=frozenset({mode}))
    for field, value in invalid_preferences.items():
        with pytest.raises(ValueError, match="not supported"):
            CleaningProfile(mode, **{field: value}).validate(capabilities)
    CleaningProfile(mode, two_pass=True).validate(capabilities)


def test_two_pass_requires_a_supported_cleaning_mode():
    assert not replace(FULL, modes=None).supports_option("two_pass")


@pytest.mark.parametrize(
    "mode,code",
    [
        (CleaningMode.VACUUM, 2),
        (CleaningMode.MOP, 4),
        (CleaningMode.VACUUM_MOP, 6),
        (CleaningMode.VACUUM_THEN_MOP, 512),
    ],
)
def test_defaults_omit_every_optional_override(mode, code):
    profile = CleaningProfile(mode)
    profile.validate(FULL)
    assert cleaning_parameters(profile) == {"operatingMode": code}


@pytest.mark.parametrize(
    "mode,suction,wetness,scrub,two_pass,boost",
    list(
        product(CleaningMode, range(1, 5), range(1, 4), [False, True], [False, True], [False, True])
    ),
)
def test_entire_valid_preference_matrix_and_mode_specific_payload(
    mode, suction, wetness, scrub, two_pass, boost
):
    profile = CleaningProfile(mode, suction, wetness, scrub, two_pass, boost)
    profile.validate(FULL)
    parameters = cleaning_parameters(profile)
    assert parameters["twoPass"] is two_pass
    if mode is CleaningMode.MOP:
        assert "suctionLevel" not in parameters and "carpetBoost" not in parameters
    else:
        assert parameters["suctionLevel"] == suction
        assert parameters["carpetBoost"] is boost
    if mode is CleaningMode.VACUUM:
        assert "padWetness" not in parameters and "swScrub" not in parameters
    else:
        assert parameters["padWetness"] == {"padPlate": wetness}
        assert type(parameters["swScrub"]) is int and parameters["swScrub"] == int(scrub)
    # Switching modes does not destroy preferences for a later mission.
    assert replace(profile, mode=CleaningMode.VACUUM_MOP).wetness_level == wetness
