"""Persistent robot name backed by Roomba's reported settings."""

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory

from .core.settings_protocol import RobotSetting
from .core.telemetry import MAX_ROBOT_NAME_LENGTH
from .entity import RoombaEntity, discover_entities


async def async_setup_entry(hass, entry, async_add_entities):
    def candidates(state):
        if state.reported_name is not None:
            yield "robot_name", RoombaRobotName

    discover_entities(entry, async_add_entities, candidates)


class RoombaRobotName(RoombaEntity, TextEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "robot_name"
    _attr_native_min = 1
    _attr_native_max = MAX_ROBOT_NAME_LENGTH

    @property
    def available(self):
        return super().available and self.native_value is not None

    @property
    def native_value(self):
        return self.robot.reported_name if self.robot else None

    async def async_set_value(self, value):
        await self.account.async_set_robot_setting(self.robot_id, RobotSetting.NAME, value)
