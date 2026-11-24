"""Roomba Home integration; core imports remain usable without Home Assistant."""

from typing import TYPE_CHECKING

from .const import DOMAIN, PLATFORMS

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


def _config_schema(config):
    from homeassistant.helpers.config_validation import config_entry_only_config_schema

    return config_entry_only_config_schema(DOMAIN)(config)


CONFIG_SCHEMA = _config_schema


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    from .map_api import async_setup_map_api
    from .services import async_setup_services

    async_setup_services(hass)
    await async_setup_map_api(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .coordinator import RoombaCoordinator

    coordinator = RoombaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_close)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_close()
        return True
    return False
