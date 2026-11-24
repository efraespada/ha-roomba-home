"""Local preference reset and capability-gated dock actions."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .coordinator import dock_snapshot
from .core.actions import Command
from .core.dock import OPERATIONS
from .entity import RoombaEntity, discover_entities

DOCK_BUTTONS = {
    "empty_bin": Command.EMPTY_BIN,
    "refill_tank": Command.REFILL,
    "wash_mop": Command.WASH_MOP,
    "dry_mop": Command.DRY_MOP,
    "stop_drying": Command.STOP_DRYING,
}


async def async_setup_entry(hass, entry, async_add_entities):
    def candidates(state):
        if state.capabilities.cleaning.modes:
            yield "reset_cleaning_profile", RoombaResetProfile
        dock = dock_snapshot(state)
        for key, command in DOCK_BUTTONS.items():
            if dock.supports(OPERATIONS[command]):
                yield key, RoombaDockButton

    discover_entities(entry, async_add_entities, candidates)


class RoombaResetProfile(RoombaEntity, ButtonEntity):
    _attr_translation_key = "reset_cleaning_profile"
    _attr_icon = "mdi:restore"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, robot_id, key="reset_cleaning_profile"):
        super().__init__(coordinator, robot_id, key)

    @property
    def available(self):
        return super().available and bool(self.robot.capabilities.cleaning.modes)

    async def async_press(self):
        await self.account.async_reset_profile(self.robot_id)


class RoombaDockButton(RoombaEntity, ButtonEntity):
    def __init__(self, coordinator, robot_id, key):
        super().__init__(coordinator, robot_id, key, dock=True)
        self._attr_translation_key = key
        self._command = DOCK_BUTTONS[key]

    @property
    def available(self):
        if not super().available:
            return False
        dock = dock_snapshot(self.robot)
        operation = OPERATIONS[self._command]
        at_rest = self.robot.activity == "docked" and self.robot.cycle == "none"
        return (
            dock.supports(operation)
            and (self._command is Command.STOP_DRYING or at_rest)
            and dock.allows(self._command, operation)
        )

    async def async_press(self):
        await self.account.async_command(self.robot_id, self._command)
