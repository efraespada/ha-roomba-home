"""Expose local map backups through authenticated Home Assistant commands."""

import probatio as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
from homeassistant.components import websocket_api
from homeassistant.components.vacuum.const import DATA_COMPONENT
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, selected_robots
from .core.errors import AuthenticationError, ProtocolError
from .core.map_snapshots import MAX_SNAPSHOTS, SNAPSHOT_ID, read_snapshot, snapshot_summary
from .core.routines import ROUTINE_ID
from .core.schedules import SCHEDULE_ID
from .map_api import IDENTIFIER, map_geometry
from .map_history import map_history
from .vacuum import RoombaVacuum

_DIGEST = vol.Match(SNAPSHOT_ID.pattern + r"\Z")
_FLOOR_REVIEW = {
    vol.Required("map_id"): IDENTIFIER,
    vol.Required("version"): IDENTIFIER,
    vol.Required("inventory_id"): _DIGEST,
    vol.Required("settings_id"): _DIGEST,
}
_GEOMETRY_RECOVERY = _FLOOR_REVIEW | {
    vol.Required("entity_id"): cv.entity_id,
    vol.Required("backup_id"): _DIGEST,
    vol.Optional("confirmed", default=False): bool,
    vol.Optional("review_id"): _DIGEST,
}


def async_register_map_history(hass):
    for command in (
        list_backups,
        read_backup,
        capture_backup,
        configure_backups,
        modify_backup,
        restore_backup_settings,
        restore_backup_zones,
        restore_backup_restrictions,
        restore_backup_furniture,
        restore_backup_programs,
    ):
        websocket_api.async_register_command(hass, command)


def _owner(hass, entity_id):
    robot = er.async_get(hass).async_get(entity_id)
    if robot is None or robot.domain != "vacuum" or robot.platform != DOMAIN:
        return None
    entry = hass.config_entries.async_get_entry(robot.config_entry_id)
    if entry is None or entry.domain != DOMAIN:
        return None
    for robot_id in selected_robots(entry):
        if robot.unique_id == f"{entry.unique_id}_{robot_id}_vacuum":
            return entry.entry_id, robot_id
    return None


def _active_account(hass, entity_id, robot_id, unavailable):
    component = hass.data.get(DATA_COMPONENT)
    vacuum = component.get_entity(entity_id) if component else None
    if not isinstance(vacuum, RoombaVacuum) or vacuum.robot_id != robot_id:
        raise HomeAssistantError(unavailable)
    return vacuum.account


async def _handle(hass, connection, message, permission, operation):
    request_id, entity_id = message["id"], message["entity_id"]
    if not connection.user.permissions.check_entity(entity_id, permission):
        connection.send_error(request_id, websocket_api.ERR_UNAUTHORIZED, "Access denied.")
        return
    if (scope := _owner(hass, entity_id)) is None:
        connection.send_error(
            request_id, "map_unavailable", "This Roomba has no local map history."
        )
        return
    entry_id, robot_id = scope
    try:
        result = await operation(map_history(hass, entry_id), robot_id)
    except AuthenticationError:
        connection.send_error(request_id, "map_unavailable", "Roomba authentication is required.")
    except HomeAssistantError as error:
        connection.send_error(request_id, error.translation_key or "map_backup_failed", str(error))
    except ProtocolError as error:
        connection.send_error(request_id, "map_backup_failed", str(error))
    except OSError:
        connection.send_error(
            request_id, "map_backup_failed", "Home Assistant storage is unavailable."
        )
    else:
        connection.send_result(request_id, result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/map_backups",
        vol.Required("entity_id"): cv.entity_id,
    }
)
@websocket_api.async_response
async def list_backups(hass, connection, message):
    async def load(history, robot_id):
        overview = await history.async_list(robot_id)
        return {
            **overview,
            "can_manage": connection.user.permissions.check_entity(
                message["entity_id"],
                POLICY_CONTROL,
            ),
        }

    await _handle(hass, connection, message, POLICY_READ, load)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/read_map_backup",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("backup_id"): _DIGEST,
        vol.Optional("download", default=False): bool,
    }
)
@websocket_api.async_response
async def read_backup(hass, connection, message):
    async def load(history, robot_id):
        snapshot = await history.async_read(robot_id, message["backup_id"])
        floor, plan = await hass.async_add_executor_job(read_snapshot, snapshot)
        if message["download"]:
            fields = ("id", "captured_at", "pinned", "floor", "archive", "programs")
            return {
                "format": "roomba-home-map-backup",
                "format_version": 1,
                **{key: snapshot[key] for key in fields if key in snapshot},
            }
        return {"backup": snapshot_summary(snapshot), "geometry": map_geometry(floor, plan)}

    await _handle(hass, connection, message, POLICY_READ, load)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/capture_map_backup",
        vol.Required("entity_id"): cv.entity_id,
    }
    | _FLOOR_REVIEW
)
@websocket_api.async_response
async def capture_backup(hass, connection, message):
    async def capture(_history, robot_id):
        account = _active_account(
            hass,
            message["entity_id"],
            robot_id,
            "Load this Roomba and its floor plan to save a new backup.",
        )
        return await account.async_capture_map_backup(
            robot_id,
            message["map_id"],
            message["version"],
            message["inventory_id"],
            message["settings_id"],
        )

    await _handle(hass, connection, message, POLICY_CONTROL, capture)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/restore_map_backup_settings",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("backup_id"): _DIGEST,
        vol.Optional("confirmed", default=False): bool,
    }
    | _FLOOR_REVIEW
)
@websocket_api.async_response
async def restore_backup_settings(hass, connection, message):
    async def restore(_history, robot_id):
        account = _active_account(
            hass,
            message["entity_id"],
            robot_id,
            "Load this Roomba and its current floor to restore floor settings.",
        )
        return await account.async_restore_map_settings(
            robot_id,
            message["backup_id"],
            message["map_id"],
            message["version"],
            message["inventory_id"],
            message["settings_id"],
            confirmed=message["confirmed"],
        )

    await _handle(hass, connection, message, POLICY_CONTROL, restore)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/restore_map_backup_programs",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("backup_id"): _DIGEST,
        vol.Optional("confirmed", default=False): bool,
        vol.Optional("kind"): vol.In(("routine", "schedule")),
        vol.Optional("program_id"): vol.Any(
            vol.Match(ROUTINE_ID.pattern + r"\Z"), vol.Match(SCHEDULE_ID.pattern + r"\Z")
        ),
        vol.Optional("review_id"): _DIGEST,
    }
    | _FLOOR_REVIEW
)
@websocket_api.async_response
async def restore_backup_programs(hass, connection, message):
    async def restore(_history, robot_id):
        account = _active_account(
            hass,
            message["entity_id"],
            robot_id,
            "Load this Roomba and its current floor to restore cleaning destinations.",
        )
        return await account.async_restore_map_programs(
            robot_id,
            message["backup_id"],
            message["map_id"],
            message["version"],
            message["inventory_id"],
            message["settings_id"],
            confirmed=message["confirmed"],
            kind=message.get("kind"),
            program_id=message.get("program_id"),
            review_id=message.get("review_id"),
        )

    await _handle(hass, connection, message, POLICY_CONTROL, restore)


@websocket_api.websocket_command(
    {vol.Required("type"): "roomba_home/restore_map_backup_zones"} | _GEOMETRY_RECOVERY
)
@websocket_api.async_response
async def restore_backup_zones(hass, connection, message):
    async def restore(_history, robot_id):
        account = _active_account(
            hass,
            message["entity_id"],
            robot_id,
            "Load this Roomba and its current floor to restore cleaning zones.",
        )
        return await account.async_restore_map_zones(
            robot_id,
            message["backup_id"],
            message["map_id"],
            message["version"],
            message["inventory_id"],
            message["settings_id"],
            confirmed=message["confirmed"],
            review_id=message.get("review_id"),
        )

    await _handle(hass, connection, message, POLICY_CONTROL, restore)


@websocket_api.websocket_command(
    {vol.Required("type"): "roomba_home/restore_map_backup_restrictions"} | _GEOMETRY_RECOVERY
)
@websocket_api.async_response
async def restore_backup_restrictions(hass, connection, message):
    async def restore(_history, robot_id):
        account = _active_account(
            hass,
            message["entity_id"],
            robot_id,
            "Load this Roomba and its current floor to restore restrictions.",
        )
        return await account.async_restore_map_restrictions(
            robot_id,
            message["backup_id"],
            message["map_id"],
            message["version"],
            message["inventory_id"],
            message["settings_id"],
            confirmed=message["confirmed"],
            review_id=message.get("review_id"),
        )

    await _handle(hass, connection, message, POLICY_CONTROL, restore)


@websocket_api.websocket_command(
    {vol.Required("type"): "roomba_home/restore_map_backup_furniture"} | _GEOMETRY_RECOVERY
)
@websocket_api.async_response
async def restore_backup_furniture(hass, connection, message):
    async def restore(_history, robot_id):
        account = _active_account(
            hass,
            message["entity_id"],
            robot_id,
            "Load this Roomba and its current floor to restore furniture.",
        )
        return await account.async_restore_map_furniture(
            robot_id,
            message["backup_id"],
            message["map_id"],
            message["version"],
            message["inventory_id"],
            message["settings_id"],
            confirmed=message["confirmed"],
            review_id=message.get("review_id"),
        )

    await _handle(hass, connection, message, POLICY_CONTROL, restore)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/configure_map_backups",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("retention"): vol.All(int, vol.Range(min=1, max=MAX_SNAPSHOTS)),
        vol.Required("automatic"): bool,
    }
)
@websocket_api.async_response
async def configure_backups(hass, connection, message):
    await _handle(
        hass,
        connection,
        message,
        POLICY_CONTROL,
        lambda history, robot_id: history.async_configure(
            robot_id, message["retention"], message["automatic"]
        ),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/modify_map_backup",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("backup_id"): _DIGEST,
        vol.Required("operation"): vol.In(("pin", "unpin", "delete")),
    }
)
@websocket_api.async_response
async def modify_backup(hass, connection, message):
    await _handle(
        hass,
        connection,
        message,
        POLICY_CONTROL,
        lambda history, robot_id: history.async_modify(
            robot_id, message["backup_id"], message["operation"]
        ),
    )
