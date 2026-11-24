"""Capability-bounded cleaning levels for the next mission and the robot defaults."""

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfArea

from .coordinator import action_error
from .core.cleaning_protocol import (
    AUTO_EVACUATION_MAX_AREA,
    AUTO_EVACUATION_MIN_AREA,
    CleaningSetting,
)
from .entity import RoombaEntity, discover_entities

LEVELS = {
    "suction_level": "suction_level",
    "wetness_level": "pad_wetness",
}
DEFAULT_LEVELS = {
    "suction_level": CleaningSetting.SUCTION,
    "wetness_level": CleaningSetting.WETNESS,
}
AUTO_EVACUATION_AREA = CleaningSetting.AUTO_EVACUATION_AREA


def _integer_level(value, *, round_converted=False):
    try:
        if type(value) not in {int, float}:
            raise ValueError
        if round_converted:
            return round(value)
        level = int(value)
        if level != value:
            raise ValueError
        return level
    except TypeError, ValueError, OverflowError:
        raise action_error("unsupported_profile", "Cleaning level is not supported") from None


async def async_setup_entry(hass, entry, async_add_entities):
    def candidates(state):
        for field in LEVELS:
            if state.capabilities.cleaning.maximum_level(field) > 0:
                yield field, RoombaCleaningLevel
        for field, setting in DEFAULT_LEVELS.items():
            if setting.observed(state.telemetry, state.capabilities.cleaning) is not None:
                yield f"default_{field}", RoombaDefaultCleaningLevel
        if _auto_evacuation_area(state) is not None:
            yield "auto_evacuation_area", RoombaAutoEvacuationArea

    discover_entities(entry, async_add_entities, candidates)


class RoombaCleaningLevel(RoombaEntity, NumberEntity):
    _attr_native_min_value = 1
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _preference_prefix = "next"

    def __init__(self, coordinator, robot_id, field):
        suffix = f"{self._preference_prefix}_{field}"
        super().__init__(coordinator, robot_id, suffix)
        self.field = field
        self.metric = LEVELS[field]
        self._attr_translation_key = suffix
        self._attr_icon = "mdi:fan" if field == "suction_level" else "mdi:water-percent"

    @property
    def available(self):
        return super().available and self.robot.capabilities.cleaning.maximum_level(self.field) > 0

    @property
    def native_max_value(self):
        return (
            (self.robot.capabilities.cleaning.maximum_level(self.field) or 1) if self.robot else 1
        )

    @property
    def native_value(self):
        if not self.robot:
            return None
        value = getattr(self.account.profile(self.robot_id), self.field)
        if value is None:
            value = self.robot.telemetry.get(self.metric)
        return value if type(value) is int and 1 <= value <= self.native_max_value else None

    async def async_set_native_value(self, value):
        await self._async_apply_level(_integer_level(value))

    async def _async_apply_level(self, level):
        await self.account.async_set_profile(self.robot_id, **{self.field: level})


class RoombaDefaultCleaningLevel(RoombaCleaningLevel):
    _attr_entity_category = EntityCategory.CONFIG
    _preference_prefix = "default"

    def __init__(self, coordinator, robot_id, key):
        field = key.removeprefix("default_")
        super().__init__(coordinator, robot_id, field)
        self.setting = DEFAULT_LEVELS[field]

    @property
    def available(self):
        return super().available and self.native_value is not None

    @property
    def native_value(self):
        state = self.robot
        return (
            self.setting.observed(state.telemetry, state.capabilities.cleaning)
            if state is not None
            else None
        )

    async def _async_apply_level(self, level):
        await self.account.async_set_cleaning_setting(self.robot_id, self.setting, level)


def _auto_evacuation_area(state):
    if state is None or not state.capabilities.supports_auto_evacuation_area:
        return None
    return AUTO_EVACUATION_AREA.observed(state.telemetry, state.capabilities.cleaning)


class RoombaAutoEvacuationArea(RoombaEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.AREA
    _attr_native_unit_of_measurement = UnitOfArea.SQUARE_METERS
    _attr_native_min_value = AUTO_EVACUATION_MIN_AREA
    _attr_native_max_value = AUTO_EVACUATION_MAX_AREA
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, robot_id, key):
        super().__init__(coordinator, robot_id, key, dock=True)
        self._attr_translation_key = key

    @property
    def available(self):
        return super().available and self.native_value is not None

    @property
    def native_value(self):
        return _auto_evacuation_area(self.robot)

    async def async_set_native_value(self, value):
        level = _integer_level(
            value, round_converted=self.unit_of_measurement != self.native_unit_of_measurement
        )
        await self.account.async_set_cleaning_setting(self.robot_id, AUTO_EVACUATION_AREA, level)
