"""Read the card's robot and dock settings from their existing HA entities."""

import probatio as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
from homeassistant.components import websocket_api
from homeassistant.components.vacuum.const import DATA_COMPONENT
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry

from .const import DOMAIN
from .coordinator import robot_settings_idle
from .entity import entity_unique_id
from .select import DOCK_SELECTS
from .vacuum import RoombaVacuum

SETTING_ENTITIES = {
    "robot_name": "text",
    "voice_language": "select",
    "voice_volume": "number",
    "child_pet_lock": "switch",
    **dict.fromkeys(DOCK_SELECTS, "select"),
    "auto_evacuation_area": "number",
    "automatic_mop_detergent": "switch",
}
SETTING_ATTRIBUTES = {
    "text": ("min", "max"),
    "select": ("options",),
    "number": ("min", "max", "step", "unit_of_measurement"),
    "switch": (),
}


@callback
def async_register_device_settings(hass):
    websocket_api.async_register_command(hass, websocket_device_settings)


@websocket_api.websocket_command(
    {"type": "roomba_home/device_settings", vol.Required("entity_id"): cv.entity_id}
)
@callback
def websocket_device_settings(hass, connection, message):
    entity_id = message["entity_id"]
    permissions = connection.user.permissions
    if not permissions.check_entity(entity_id, POLICY_READ):
        connection.send_error(message["id"], websocket_api.ERR_UNAUTHORIZED, "Access denied.")
        return
    component = hass.data.get(DATA_COMPONENT)
    vacuum = component.get_entity(entity_id) if component else None
    if not isinstance(vacuum, RoombaVacuum) or (robot := vacuum.robot) is None:
        connection.send_error(
            message["id"], "device_settings_unavailable", "Device settings are unavailable."
        )
        return

    registry = entity_registry.async_get(hass)
    entry_id = vacuum.account.config_entry.unique_id
    connected = vacuum.account.last_update_success and robot.connected is True
    ready = connected and robot_settings_idle(robot)
    settings = {}
    for key, domain in SETTING_ENTITIES.items():
        unique_id = entity_unique_id(entry_id, vacuum.robot_id, key)
        setting_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
        if setting_id is None or not permissions.check_entity(setting_id, POLICY_READ):
            continue
        if (state := hass.states.get(setting_id)) is None:
            continue
        available = state.state != STATE_UNAVAILABLE
        value = None if state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN} else state.state
        if domain == "text" and connected:
            # The reported name may itself equal a reserved Home Assistant state string.
            value = robot.reported_name
            available = value is not None
        settings[key] = {
            "entity_id": setting_id,
            "value": value,
            "editable": ready
            and available
            and permissions.check_entity(setting_id, POLICY_CONTROL),
            "attributes": {
                name: state.attributes[name]
                for name in SETTING_ATTRIBUTES[domain]
                if name in state.attributes
            },
        }
    connection.send_result(
        message["id"], {"robot": robot.name, "ready": ready, "settings": settings}
    )
