"""Pure cleaning preferences and capability policy; no provider or HA types."""

from dataclasses import dataclass
from enum import StrEnum


class CleaningMode(StrEnum):
    VACUUM = "vacuum"
    MOP = "mop"
    VACUUM_MOP = "vacuum_mop"
    VACUUM_THEN_MOP = "vacuum_then_mop"

    @property
    def vacuums(self) -> bool:
        return self is not CleaningMode.MOP

    @property
    def mops(self) -> bool:
        return self is not CleaningMode.VACUUM


@dataclass(frozen=True)
class CleaningCapabilities:
    modes: frozenset[CleaningMode] | None = None
    suction_levels: int | None = None
    wetness_levels: int | None = None
    smart_scrub: bool | None = None
    two_pass: bool | None = None
    carpet_boost: bool | None = None
    auto_evacuation_area: bool | None = None

    def maximum_level(self, field: str) -> int:
        modes = self.modes or ()
        if field == "suction_level":
            return (self.suction_levels or 0) if any(mode.vacuums for mode in modes) else 0
        return (self.wetness_levels or 0) if any(mode.mops for mode in modes) else 0

    def supports_option(self, field: str) -> bool:
        if getattr(self, field) is not True:
            return False
        modes = self.modes or ()
        if field == "smart_scrub":
            return any(mode.mops for mode in modes)
        if field == "carpet_boost":
            return any(mode.vacuums for mode in modes)
        return bool(modes)


@dataclass(frozen=True)
class CleaningProfile:
    """Preferences for the next start; None leaves that setting to the robot."""

    mode: CleaningMode = CleaningMode.VACUUM
    suction_level: int | None = None
    wetness_level: int | None = None
    smart_scrub: bool | None = None
    two_pass: bool | None = None
    carpet_boost: bool | None = None

    def __post_init__(self):
        if not isinstance(self.mode, CleaningMode):
            raise ValueError("A supported cleaning mode is required.")
        for value in (self.suction_level, self.wetness_level):
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError("Cleaning levels must be positive integers.")
        for value in (self.smart_scrub, self.two_pass, self.carpet_boost):
            if value is not None and type(value) is not bool:
                raise ValueError("Cleaning switches must be booleans.")

    def validate(self, capabilities: CleaningCapabilities) -> None:
        if self.mode not in (capabilities.modes or ()):
            raise ValueError("This cleaning mode is not supported by the robot.")
        for field in ("suction_level", "wetness_level"):
            value = getattr(self, field)
            if value is not None and value > capabilities.maximum_level(field):
                raise ValueError("This cleaning level is not supported by the robot.")
        for field in ("smart_scrub", "two_pass", "carpet_boost"):
            if getattr(self, field) is not None and not capabilities.supports_option(field):
                raise ValueError("This cleaning option is not supported by the robot.")
