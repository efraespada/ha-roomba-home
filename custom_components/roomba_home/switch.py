"""Boolean cleaning preferences and confirmed persistent robot settings."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory

from .core.settings_protocol import RobotSetting
from .entity import RoombaEntity, discover_entities

OPTIONS = {
    "smart_scrub": RobotSetting.SMART_SCRUB,
    "two_pass": RobotSetting.TWO_PASS,
    "carpet_boost": RobotSetting.CARPET_BOOST,
}
DEVICE_SWITCHES = {
    "child_pet_lock": (RobotSetting.CHILD_PET_LOCK, False, "mdi:lock-outline"),
    "automatic_mop_detergent": (RobotSetting.AUTOMATIC_DETERGENT, True, "mdi:water-plus-outline"),
}


async def async_setup_entry(hass, entry, async_add_entities):
    def candidates(state):
        for field, setting in OPTIONS.items():
            if state.capabilities.cleaning.supports_option(field):
                yield field, RoombaCleaningOption
            if setting.observed(state.telemetry, state.capabilities.cleaning) is not None:
                yield f"default_{field}", RoombaDefaultCleaningOption
        for key, (setting, _, _) in DEVICE_SWITCHES.items():
            if setting.observed_on(state.telemetry, state.capabilities) is not None:
                yield key, RoombaDeviceSwitch

    discover_entities(entry, async_add_entities, candidates)


class RoombaCleaningOption(RoombaEntity, SwitchEntity):
    _preference_prefix = "next"

    def __init__(self, coordinator, robot_id, field):
        suffix = f"{self._preference_prefix}_{field}"
        super().__init__(coordinator, robot_id, suffix)
        self.field = field
        self._attr_translation_key = suffix
        self._attr_icon = "mdi:layers" if field == "two_pass" else "mdi:vacuum"

    @property
    def available(self):
        return super().available and self.robot.capabilities.cleaning.supports_option(self.field)

    @property
    def is_on(self):
        if not self.robot:
            return None
        value = getattr(self.account.profile(self.robot_id), self.field)
        if value is not None:
            return value
        value = self.robot.telemetry.get(OPTIONS[self.field].value)
        if self.field == "smart_scrub":
            return bool(value) if type(value) is int and value in {0, 1} else None
        return value if type(value) is bool else None

    async def async_turn_on(self, **kwargs):
        await self._async_apply_option(True)

    async def async_turn_off(self, **kwargs):
        await self._async_apply_option(False)

    async def _async_apply_option(self, enabled):
        await self.account.async_set_profile(self.robot_id, **{self.field: enabled})


class RoombaDefaultCleaningOption(RoombaCleaningOption):
    _attr_entity_category = EntityCategory.CONFIG
    _preference_prefix = "default"

    def __init__(self, coordinator, robot_id, key):
        field = key.removeprefix("default_")
        super().__init__(coordinator, robot_id, field)
        self.setting = OPTIONS[field]

    @property
    def available(self):
        return super().available and self.is_on is not None

    @property
    def is_on(self):
        state = self.robot
        return (
            self.setting.observed(state.telemetry, state.capabilities.cleaning)
            if state is not None
            else None
        )

    async def _async_apply_option(self, enabled):
        await self.account.async_set_robot_setting(self.robot_id, self.setting, enabled)


class RoombaDeviceSwitch(RoombaEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, robot_id, key):
        self.setting, dock, icon = DEVICE_SWITCHES[key]
        super().__init__(coordinator, robot_id, key, dock=dock)
        self._attr_translation_key = key
        self._attr_icon = icon

    @property
    def available(self):
        return super().available and self.is_on is not None

    @property
    def is_on(self):
        state = self.robot
        return (
            self.setting.observed_on(state.telemetry, state.capabilities)
            if state is not None
            else None
        )

    async def async_turn_on(self, **kwargs):
        await self.account.async_set_robot_setting(self.robot_id, self.setting, True)

    async def async_turn_off(self, **kwargs):
        await self.account.async_set_robot_setting(self.robot_id, self.setting, False)
