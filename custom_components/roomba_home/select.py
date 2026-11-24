"""The next mission's mode, independent of the currently running mission."""

from homeassistant.components.select import SelectEntity

from .core.cleaning import CleaningMode
from .entity import RoombaEntity, discover_entities


async def async_setup_entry(hass, entry, async_add_entities):
    def candidates(state):
        if state.capabilities.cleaning.modes:
            yield "next_cleaning_mode", RoombaCleaningMode

    discover_entities(entry, async_add_entities, candidates)


class RoombaCleaningMode(RoombaEntity, SelectEntity):
    _attr_translation_key = "next_cleaning_mode"
    _attr_icon = "mdi:vacuum"

    def __init__(self, coordinator, robot_id, key="next_cleaning_mode"):
        super().__init__(coordinator, robot_id, key)

    @property
    def available(self):
        return super().available and bool(self.options)

    @property
    def options(self):
        modes = (
            (self.robot.capabilities.cleaning.modes or frozenset()) if self.robot else frozenset()
        )
        return [mode.value for mode in CleaningMode if mode in modes]

    @property
    def current_option(self):
        value = self.account.profile(self.robot_id).mode.value
        return value if value in self.options else None

    async def async_select_option(self, option):
        if option not in self.options:
            from .coordinator import action_error

            raise action_error("unsupported_profile", "Cleaning mode is not supported")
        await self.account.async_set_profile(self.robot_id, mode=CleaningMode(option))
