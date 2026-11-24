"""Authenticated floor-plan snapshots for the optional dashboard card."""

from datetime import UTC, datetime
from pathlib import Path

import probatio as vol
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components import websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.vacuum.const import DATA_COMPONENT
from homeassistant.helpers import config_validation as cv

from .core.maps import RegionKind
from .vacuum import RoombaVacuum

CARD_URL = "/roomba_home/roomba-home-map-card.js"
IDENTIFIER = vol.All(str, vol.Length(min=1, max=128))


async def async_setup_map_api(hass):
    path = Path(__file__).with_name("frontend") / "roomba-home-map-card.js"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), False)])
    websocket_api.async_register_command(hass, websocket_floor_plan)


def map_geometry(floor, plan):
    polygons = {
        (kind, region.region_id): region.polygons
        for kind, regions in ((RegionKind.ROOM, plan.rooms), (RegionKind.ZONE, plan.zones))
        for region in regions
    }
    shapes = [
        {
            "id": region.segment_id(floor.map_id),
            "kind": "room" if region.kind is RegionKind.ROOM else "zone",
            "name": region.name or f"Area {index}",
            "polygons": polygons.get((region.kind, region.region_id), ()),
        }
        for index, region in enumerate(floor.regions, 1)
    ]
    # Keep outlines for rooms that have geometry but no selectable inventory entry.
    shape_ids = {region.region_id for region in floor.regions if region.kind is RegionKind.ROOM}
    shapes.extend(
        {"id": None, "kind": "room", "name": None, "polygons": room.polygons}
        for room in plan.rooms
        if room.region_id not in shape_ids
    )
    return {
        "regions": shapes,
        "keep_out": plan.keep_out,
        "virtual_walls": plan.virtual_walls,
        "no_mop": plan.no_mop,
        "unlinked_zone_count": plan.unlinked_zone_count,
    }


def live_geometry(path, floor, now):
    if path is None or path.map_version != (floor.map_id, floor.version_id):
        return {"trail": [], "position": None}
    position = None
    if path.latest.expires > now.timestamp():
        latest = path.latest.positions[-1]
        position = {
            "x": latest.x,
            "y": latest.y,
            "orientation": latest.orientation,
            "expires_at": path.latest.expires,
        }
    return {
        "trail": [(index, point.x, point.y) for index, point in path.points],
        "position": position,
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/floor_plan",
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("map_id"): IDENTIFIER,
        vol.Optional("known_version"): IDENTIFIER,
        vol.Optional("known_inventory"): IDENTIFIER,
    }
)
@websocket_api.async_response
async def websocket_floor_plan(hass, connection, message):
    entity_id = message["entity_id"]
    if not connection.user.permissions.check_entity(entity_id, POLICY_READ):
        connection.send_error(message["id"], websocket_api.ERR_UNAUTHORIZED, "Access denied.")
        return
    component = hass.data.get(DATA_COMPONENT)
    vacuum = component.get_entity(entity_id) if component else None
    if not isinstance(vacuum, RoombaVacuum) or not vacuum.account.show_maps:
        connection.send_error(message["id"], "map_unavailable", "Floor maps are unavailable.")
        return

    account, robot_id = vacuum.account, vacuum.robot_id
    state = vacuum.robot
    maps = account.maps_for_robot(robot_id)
    requested = message.get("map_id")
    if (
        not account.last_update_success
        or state is None
        or state.telemetry.get("maps_available") is not True
        or not maps
    ):
        connection.send_error(message["id"], "map_unavailable", "Floor maps are unavailable.")
        return
    floor = next((item for item in maps if item.map_id == requested), maps[0])
    # The archive revision and the associated region inventory can change independently.
    inventory_id = floor.inventory_id
    cleaning = state.capabilities.cleaning
    response = {
        "robot": state.name,
        "map": {"id": floor.map_id, "version": floor.version_id},
        "inventory_id": inventory_id,
        "cleaning": {
            "modes": sorted(cleaning.modes or ()),
            "suction_level": cleaning.maximum_level("suction_level"),
            "wetness_level": cleaning.maximum_level("wetness_level"),
            **{
                field: cleaning.supports_option(field)
                for field in ("two_pass", "smart_scrub", "carpet_boost")
            },
        },
        "maps": [{"id": item.map_id, "name": item.name} for item in maps],
        "current_room": state.telemetry.get("current_room"),
        "last_mission_rooms": state.telemetry.get("last_mission_rooms", []),
        "active_rooms": state.telemetry.get("live_timeline_active_rooms", []),
        "live": live_geometry(account.live_path(robot_id), floor, datetime.now(UTC)),
    }
    if (requested, message.get("known_version"), message.get("known_inventory", inventory_id)) != (
        floor.map_id,
        floor.version_id,
        inventory_id,
    ):
        plan = await account.async_floor_plan(robot_id, floor)
        if plan is None or floor not in account.maps_for_robot(robot_id):
            connection.send_error(message["id"], "map_unavailable", "Floor maps are unavailable.")
            return
        response["geometry"] = map_geometry(floor, plan)
    connection.send_result(message["id"], response)
