"""Typed capabilities used by the robot and dock surfaces."""

from dataclasses import dataclass, field
from enum import StrEnum

from .cleaning import CleaningCapabilities


class DigitalSpotCapability(StrEnum):
    UNSUPPORTED = "unsupported"
    SUPPORTED = "supported"
    HEATED_WATER = "heated_water"


def supports_point_clean(capability: DigitalSpotCapability | None) -> bool:
    return capability in (DigitalSpotCapability.SUPPORTED, DigitalSpotCapability.HEATED_WATER)


@dataclass(frozen=True)
class DockCapabilities:
    recognized: bool | None = None
    evacuation: bool | None = None
    wash: bool | None = None
    dry: bool | None = None
    refill: bool | None = None
    manual_refill: bool | None = None


@dataclass(frozen=True)
class DeviceCapabilities:
    cleaning: CleaningCapabilities = field(default_factory=CleaningCapabilities)
    dock: DockCapabilities = field(default_factory=DockCapabilities)
    docking: bool | None = None
    persistent_maps: bool | None = None
    map_selection: bool | None = None
    room_regions: bool | None = None
    zone_regions: bool | None = None
    room_cleaning: bool | None = None
    zone_cleaning: bool | None = None
    schedules: bool | None = None
    history: bool | None = None
    maintenance: bool | None = None
    statistics: bool | None = None
    firmware: bool | None = None
    connectivity: bool | None = None
    water_tank: bool | None = None
    diagnostics: bool | None = None
    locate: bool | None = None
    digital_spot: DigitalSpotCapability | None = None

    @property
    def supports_auto_evacuation_area(self) -> bool:
        return (
            self.cleaning.auto_evacuation_area is True
            and self.dock.recognized is True
            and self.dock.evacuation is True
        )
