"""Map the native SDK protocol to semantic cleaning profiles and capabilities."""

from .cleaning import CleaningCapabilities, CleaningMode, CleaningProfile

MODE_CODES = {
    CleaningMode.VACUUM: 2,
    CleaningMode.MOP: 4,
    CleaningMode.VACUUM_MOP: 6,
    CleaningMode.VACUUM_THEN_MOP: 512,
}

# Simultaneous support is bit 32; its command value is 6, not 32.
SUPPORT_BITS = {
    CleaningMode.VACUUM: 2,
    CleaningMode.MOP: 4,
    CleaningMode.VACUUM_MOP: 32,
    CleaningMode.VACUUM_THEN_MOP: 512,
}


def reported_cleaning_mode(value: object) -> CleaningMode | None:
    if type(value) is not int:
        return None
    return next((mode for mode, code in MODE_CODES.items() if value == code), None)


def requested_region_mode(value: object) -> CleaningMode | None:
    """Read the documented semantic variants used by native regional commands."""
    return CleaningMode.VACUUM_MOP if value == 32 else reported_cleaning_mode(value)


def cleaning_capabilities(raw: object) -> CleaningCapabilities:
    """Untrusted or missing capability values never enable writes."""
    data = raw if isinstance(raw, dict) else {}

    def number(key):
        value = data.get(key)
        return value if type(value) is int and value >= 0 else None

    def support(key, known, supported):
        value = number(key)
        return value in supported if value in known else None

    mask = number("oMode")
    suction = number("suctionLvl")
    wetness = number("ppWetLvl")
    return CleaningCapabilities(
        modes=(
            frozenset(mode for mode, bit in SUPPORT_BITS.items() if mask & bit == bit)
            if mask is not None
            else None
        ),
        suction_levels=suction if suction is not None and suction <= 99 else None,
        wetness_levels=wetness if wetness is not None and wetness <= 99 else None,
        smart_scrub=support("scrub", {0, 1, 2, 3}, {2, 3}),
        two_pass=support("multiPass", {0, 1, 2, 3}, {1, 2}),
        carpet_boost=support("carpetBoost", {0, 1, 2, 3}, {1, 2, 3}),
        auto_evacuation_area={0: False, 2: True}.get(number("autoevac")),
    )


def cleaning_parameters(profile: CleaningProfile) -> dict:
    """Keep inactive preferences, but omit their fields from this mission."""
    value = {"operatingMode": MODE_CODES[profile.mode]}
    if profile.mode.vacuums:
        if profile.suction_level is not None:
            value["suctionLevel"] = profile.suction_level
        if profile.carpet_boost is not None:
            value["carpetBoost"] = profile.carpet_boost
    if profile.mode.mops:
        if profile.wetness_level is not None:
            value["padWetness"] = {"padPlate": profile.wetness_level}
        if profile.smart_scrub is not None:
            value["swScrub"] = int(profile.smart_scrub)
    if profile.two_pass is not None:
        value["twoPass"] = profile.two_pass
    return value


def regional_cleaning_parameters(profile: CleaningProfile) -> dict:
    """Serialize the profile for a saved routine or weekly schedule."""
    params = cleaning_parameters(profile)
    if profile.mode is CleaningMode.VACUUM_MOP:
        params["operatingMode"] = 32
    if profile.mode is CleaningMode.VACUUM_THEN_MOP:
        params["routine_modified"] = True
    return params


def parse_regional_profile(params: object, *, inactive_mop=False) -> CleaningProfile | None:
    """Validate regional preferences and preserve omitted robot defaults."""
    if not isinstance(params, dict):
        return None
    code = params.get("operatingMode")
    mode = requested_region_mode(code)
    wetness = params.get("padWetness")
    scrub = params.get("swScrub")
    try:
        profile = CleaningProfile(
            mode=mode,
            suction_level=params.get("suctionLevel"),
            wetness_level=wetness.get("padPlate") if isinstance(wetness, dict) else None,
            two_pass=params.get("twoPass"),
            smart_scrub=bool(scrub) if type(scrub) is int and scrub in (0, 1) else None,
            carpet_boost=params.get("carpetBoost"),
        )
    except ValueError:
        return None
    expected = regional_cleaning_parameters(profile)
    if inactive_mop and profile.mode is CleaningMode.VACUUM:
        if profile.wetness_level is not None:
            expected["padWetness"] = {"padPlate": profile.wetness_level}
        if profile.smart_scrub is not None:
            expected["swScrub"] = int(profile.smart_scrub)
    if profile.mode is CleaningMode.VACUUM_MOP and code == 6:
        expected["operatingMode"] = 6
    if profile.mode is CleaningMode.VACUUM_THEN_MOP:
        if params.get("routine_modified", True) is not True:
            return None
        if "routine_modified" not in params:
            del expected["routine_modified"]
    if expected != params or any(
        (level or 0) > 99 for level in (profile.suction_level, profile.wetness_level)
    ):
        return None
    return profile
