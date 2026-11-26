"""Next-mission mode and persistent robot and dock choices."""

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory

from .coordinator import action_error
from .core.cleaning import CleaningMode
from .core.settings_protocol import DOCK_SETTING_OPTIONS, RobotSetting
from .entity import RoombaEntity, discover_entities

DOCK_SELECTS = {
    "auto_empty_frequency": RobotSetting.AUTO_EVACUATION_AREA,
    "mop_wash_temperature": RobotSetting.PAD_WASH_TEMPERATURE,
    "mop_wash_frequency": RobotSetting.PAD_WASH_FREQUENCY,
    "mop_drying_duration": RobotSetting.PAD_DRY_DURATION,
}
CUSTOM_EMPTY_AREA = "custom_area"


async def async_setup_entry(hass, entry, async_add_entities):
    def candidates(state):
        if state.capabilities.cleaning.modes:
            yield "next_cleaning_mode", RoombaCleaningMode
        if state.telemetry.get("voice_language") in state.telemetry.get(
            "installed_voice_languages", ()
        ):
            yield "voice_language", RoombaVoiceLanguage
        for key, setting in DOCK_SELECTS.items():
            if setting.observed_on(state.telemetry, state.capabilities) is not None:
                yield key, RoombaDockSelect

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
            raise action_error("unsupported_profile", "Cleaning mode is not supported")
        await self.account.async_set_profile(self.robot_id, mode=CleaningMode(option))


class RoombaDockSelect(RoombaEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, robot_id, key):
        super().__init__(coordinator, robot_id, key, dock=True)
        self.setting = DOCK_SELECTS[key]
        self._codes = DOCK_SETTING_OPTIONS[self.setting]
        self._choices = {code: option for option, code in self._codes.items()}
        self._attr_translation_key = key

    @property
    def available(self):
        return super().available and self.current_option is not None

    @property
    def options(self):
        options = list(self._codes)
        if self.current_option == CUSTOM_EMPTY_AREA:
            options.append(CUSTOM_EMPTY_AREA)
        return options

    @property
    def current_option(self):
        state = self.robot
        if state is None:
            return None
        code = self.setting.observed_on(state.telemetry, state.capabilities)
        if code is not None and self.setting is RobotSetting.AUTO_EVACUATION_AREA:
            return self._choices.get(code, CUSTOM_EMPTY_AREA)
        return self._choices.get(code)

    async def async_select_option(self, option):
        if option == CUSTOM_EMPTY_AREA and self.current_option == CUSTOM_EMPTY_AREA:
            return
        if option not in self._codes:
            raise action_error("unsupported_robot_setting", "This dock option is not supported")
        await self.account.async_set_robot_setting(self.robot_id, self.setting, self._codes[option])


class RoombaVoiceLanguage(RoombaEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "voice_language"

    @property
    def available(self):
        return super().available and self.current_option is not None

    @property
    def options(self):
        return list(self._installed_codes())

    def _installed_codes(self):
        codes = self.robot.telemetry.get("installed_voice_languages", ()) if self.robot else ()
        return {code.lower(): code for code in codes}

    @property
    def current_option(self):
        if self.robot is None:
            return None
        language = self.robot.telemetry.get("voice_language")
        return language.lower() if language in self._installed_codes().values() else None

    async def async_select_option(self, option):
        if (code := self._installed_codes().get(option)) is None:
            raise action_error("voice_language_not_installed", "Voice language is not installed")
        await self.account.async_set_robot_setting(self.robot_id, RobotSetting.VOICE_LANGUAGE, code)
