"""Validated writes to the native Roomba settings shadow."""

from enum import StrEnum

from .capabilities import DeviceCapabilities
from .cleaning import CleaningCapabilities
from .telemetry import convert

AUTO_EVACUATION_MIN_AREA = 10
AUTO_EVACUATION_MAX_AREA = 1000
MIN_VOICE_VOLUME = 0
MAX_VOICE_VOLUME = 100


class RobotSetting(StrEnum):
    """Persistent robot settings verified via the native settings shadow."""

    SUCTION = "suction_level"
    WETNESS = "pad_wetness"
    SMART_SCRUB = "scrub_setting"
    TWO_PASS = "two_pass"
    CARPET_BOOST = "carpet_boost"
    AUTO_EVACUATION_AREA = "auto_evacuation_frequency"
    NAME = "robot_name"
    VOICE_VOLUME = "audio_volume"
    VOICE_LANGUAGE = "voice_language"
    CHILD_PET_LOCK = "child_lock"
    PAD_WASH_TEMPERATURE = "pad_wash_heat"
    PAD_WASH_FREQUENCY = "pad_wash_return"
    AUTOMATIC_DETERGENT = "detergent_setting"
    PAD_DRY_DURATION = "pad_dry_duration"

    def accepts(self, value: object, capabilities: CleaningCapabilities) -> bool:
        if self is RobotSetting.VOICE_VOLUME:
            return type(value) is int and MIN_VOICE_VOLUME <= value <= MAX_VOICE_VOLUME
        if self is RobotSetting.VOICE_LANGUAGE:
            return convert("language", value) is not None
        if self is RobotSetting.NAME:
            return convert("robot_name", value) is not None
        if self in (RobotSetting.CHILD_PET_LOCK, RobotSetting.AUTOMATIC_DETERGENT):
            return type(value) is bool
        if options := DOCK_SETTING_OPTIONS.get(self):
            return type(value) is int and value in options.values()
        if option := _SWITCH_OPTIONS.get(self):
            return type(value) is bool and capabilities.supports_option(option)
        if self is RobotSetting.AUTO_EVACUATION_AREA:
            return (
                capabilities.auto_evacuation_area is True
                and type(value) is int
                and AUTO_EVACUATION_MIN_AREA <= value <= AUTO_EVACUATION_MAX_AREA
            )
        field = "suction_level" if self is RobotSetting.SUCTION else "wetness_level"
        return type(value) is int and 1 <= value <= capabilities.maximum_level(field)

    def observed(
        self, telemetry: dict, capabilities: CleaningCapabilities
    ) -> int | bool | str | None:
        value = telemetry.get(self.value)
        if self in _INTEGER_SWITCHES:
            if type(value) is not int or value not in (0, 1):
                return None
            value = bool(value)
        return value if self.accepts(value, capabilities) else None

    def supported_on(self, capabilities: DeviceCapabilities) -> bool:
        if self is RobotSetting.AUTO_EVACUATION_AREA:
            return capabilities.supports_auto_evacuation_area
        if support := _DOCK_CAPABILITIES.get(self):
            return (
                capabilities.dock.recognized is True and getattr(capabilities.dock, support) is True
            )
        return True

    def observed_on(
        self, telemetry: dict, capabilities: DeviceCapabilities
    ) -> int | bool | str | None:
        if not self.supported_on(capabilities):
            return None
        return self.observed(telemetry, capabilities.cleaning)

    def desired(self, value: int | bool | str) -> dict:
        if self is RobotSetting.SUCTION:
            return {"suctionLevel": value}
        if self is RobotSetting.WETNESS:
            return {"padWetness": {"padPlate": value}}
        if self is RobotSetting.VOICE_VOLUME:
            return {"audio": {"volume": value}}
        if self is RobotSetting.VOICE_LANGUAGE:
            return {"langs2": {"sLang": value}}
        return {_WIRE_FIELDS[self]: int(value) if self in _INTEGER_SWITCHES else value}


DOCK_SETTING_OPTIONS = {
    RobotSetting.PAD_WASH_TEMPERATURE: {"room_temperature": 0, "hot": 1, "very_hot": 2},
    RobotSetting.PAD_WASH_FREQUENCY: {"standard": 100, "medium": 101, "high": 102},
    RobotSetting.PAD_DRY_DURATION: {"three_hours": 3, "four_hours": 4, "five_hours": 5},
}
DEVICE_CONFIGURATION_SETTINGS = frozenset(
    {
        RobotSetting.VOICE_VOLUME,
        RobotSetting.VOICE_LANGUAGE,
        RobotSetting.NAME,
        RobotSetting.CHILD_PET_LOCK,
        RobotSetting.AUTOMATIC_DETERGENT,
        *DOCK_SETTING_OPTIONS,
    }
)
_DOCK_CAPABILITIES = {
    RobotSetting.PAD_WASH_TEMPERATURE: "wash",
    RobotSetting.PAD_WASH_FREQUENCY: "wash",
    RobotSetting.AUTOMATIC_DETERGENT: "wash",
    RobotSetting.PAD_DRY_DURATION: "dry",
}
_INTEGER_SWITCHES = {RobotSetting.SMART_SCRUB, RobotSetting.AUTOMATIC_DETERGENT}
_SWITCH_OPTIONS = {
    RobotSetting.SMART_SCRUB: "smart_scrub",
    RobotSetting.TWO_PASS: "two_pass",
    RobotSetting.CARPET_BOOST: "carpet_boost",
}
_WIRE_FIELDS = {
    RobotSetting.NAME: "name",
    RobotSetting.SMART_SCRUB: "swScrub",
    RobotSetting.TWO_PASS: "twoPass",
    RobotSetting.CARPET_BOOST: "carpetBoost",
    RobotSetting.AUTO_EVACUATION_AREA: "autoevacFreq",
    RobotSetting.CHILD_PET_LOCK: "childLock",
    RobotSetting.PAD_WASH_TEMPERATURE: "pwHeat",
    RobotSetting.PAD_WASH_FREQUENCY: "pwReturn",
    RobotSetting.AUTOMATIC_DETERGENT: "detergent",
    RobotSetting.PAD_DRY_DURATION: "padDryDur",
}
