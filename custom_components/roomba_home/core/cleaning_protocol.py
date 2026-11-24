"""Map the native SDK protocol to semantic cleaning profiles and capabilities."""

from enum import StrEnum

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
AUTO_EVACUATION_MIN_AREA = 10
AUTO_EVACUATION_MAX_AREA = 1000


class CleaningSetting(StrEnum):
    """Persistent cleaning settings verified via the native settings shadow."""

    SUCTION = "suction_level"
    WETNESS = "pad_wetness"
    SMART_SCRUB = "scrub_setting"
    TWO_PASS = "two_pass"
    CARPET_BOOST = "carpet_boost"
    AUTO_EVACUATION_AREA = "auto_evacuation_frequency"

    def accepts(self, value: object, capabilities: CleaningCapabilities) -> bool:
        if option := _SWITCH_OPTIONS.get(self):
            return type(value) is bool and capabilities.supports_option(option)
        if self is CleaningSetting.AUTO_EVACUATION_AREA:
            return (
                capabilities.auto_evacuation_area is True
                and type(value) is int
                and AUTO_EVACUATION_MIN_AREA <= value <= AUTO_EVACUATION_MAX_AREA
            )
        field = "suction_level" if self is CleaningSetting.SUCTION else "wetness_level"
        return type(value) is int and 1 <= value <= capabilities.maximum_level(field)

    def observed(self, telemetry: dict, capabilities: CleaningCapabilities) -> int | bool | None:
        value = telemetry.get(self.value)
        if self is CleaningSetting.SMART_SCRUB:
            if type(value) is not int or value not in (0, 1):
                return None
            value = bool(value)
        return value if self.accepts(value, capabilities) else None

    def desired(self, value: int | bool) -> dict:
        if self is CleaningSetting.SUCTION:
            return {"suctionLevel": value}
        if self is CleaningSetting.WETNESS:
            return {"padWetness": {"padPlate": value}}
        if self is CleaningSetting.SMART_SCRUB:
            return {"swScrub": int(value)}
        return {_WIRE_FIELDS[self]: value}


_SWITCH_OPTIONS = {
    CleaningSetting.SMART_SCRUB: "smart_scrub",
    CleaningSetting.TWO_PASS: "two_pass",
    CleaningSetting.CARPET_BOOST: "carpet_boost",
}
_WIRE_FIELDS = {
    CleaningSetting.TWO_PASS: "twoPass",
    CleaningSetting.CARPET_BOOST: "carpetBoost",
    CleaningSetting.AUTO_EVACUATION_AREA: "autoevacFreq",
}


def reported_cleaning_mode(value: object) -> CleaningMode | None:
    if type(value) is not int:
        return None
    return next((mode for mode, code in MODE_CODES.items() if value == code), None)


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
