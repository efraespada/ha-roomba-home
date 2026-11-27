"""Authenticated floor plans and device views for the optional dashboard card."""

from datetime import UTC, datetime
from pathlib import Path

import probatio as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
from homeassistant.components import websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.vacuum.const import DATA_COMPONENT
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .coordinator import control_snapshot, mission_review
from .core.capabilities import supports_point_clean
from .core.cleaning import CleaningMode
from .core.cleaning_protocol import reported_cleaning_mode
from .core.errors import AuthenticationError
from .core.floor_settings import MAX_INITIAL_FLOOR_NAME_LENGTH, floor_name_limit
from .core.furniture_edits import FURNITURE_TYPES, can_edit_furniture, furniture_pose
from .core.furniture_targets import furniture_regions
from .core.history import DEFAULT_HISTORY_DAYS, HISTORY_WINDOWS
from .core.live_coverage import CELL_SIZE
from .core.live_maps import POSITION_ACTIVITIES
from .core.maintenance import maintenance_parts
from .core.maps import RegionKind
from .core.point_maps import with_archive_destinations
from .core.problems import active_device_errors
from .core.restriction_edits import EDITABLE_RESTRICTIONS
from .core.room_edits import MAX_ROOM_NAME_LENGTH, ROOM_TYPES
from .core.routine_presets import routine_presets, supports_routine_presets
from .core.state import RobotState
from .core.telemetry import CLEANING_CYCLES
from .core.zone_edits import zone_corners
from .vacuum import RoombaVacuum

CARD_URL = "/roomba_home/roomba-home-map-card.js"
IDENTIFIER = vol.All(str, vol.Length(min=1, max=128))


def current_mission(state: RobotState, now: datetime) -> dict | None:
    if state.connected is not True or state.cycle not in CLEANING_CYCLES:
        return None
    return {
        "activity": state.activity,
        "phase": state.phase,
        "mode": reported_cleaning_mode(state.mode),
        "elapsed_seconds": state.mission_elapsed(now),
        "cleaned_area_m2": state.telemetry.get("mission_area"),
        "error_code": state.error or None,
    }


async def async_setup_map_api(hass):
    from .map_history_api import async_register_map_history

    path = Path(__file__).with_name("frontend") / "roomba-home-map-card.js"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), False)])
    websocket_api.async_register_command(hass, websocket_floor_plan)
    websocket_api.async_register_command(hass, websocket_live_positions)
    websocket_api.async_register_command(hass, websocket_mission_history)
    websocket_api.async_register_command(hass, websocket_maintenance)
    websocket_api.async_register_command(hass, websocket_robot_help)
    websocket_api.async_register_command(hass, websocket_cleaning_scores)
    websocket_api.async_register_command(hass, websocket_floor_routines)
    websocket_api.async_register_command(hass, websocket_edit_floor_settings)
    websocket_api.async_register_command(hass, websocket_remove_floor)
    websocket_api.async_register_command(hass, websocket_edit_rooms)
    websocket_api.async_register_command(hass, websocket_edit_zones)
    websocket_api.async_register_command(hass, websocket_edit_restrictions)
    websocket_api.async_register_command(hass, websocket_edit_furniture)
    async_register_map_history(hass)


def map_geometry(floor, plan):
    floor = with_archive_destinations(floor, plan)
    polygons = {
        (kind, region.region_id): region.polygons
        for kind, regions in (
            (RegionKind.ROOM, plan.rooms),
            (RegionKind.ZONE, (*plan.zones, *plan.zone_outlines)),
        )
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
    geometry = {
        "regions": shapes,
        "selection_id": floor.selection_id,
        "keep_out": plan.keep_out,
        "virtual_walls": plan.virtual_walls,
        "no_mop": plan.no_mop,
        "unlinked_zone_count": plan.unlinked_zone_count,
    }
    if plan.walls or plan.carpets or plan.docks:
        geometry["presentation"] = {
            "walls": [{"kind": kind, "points": points} for kind, points in plan.walls],
            "carpets": plan.carpets,
            "docks": plan.docks,
        }
    if plan.source_format == "picea":
        geometry["floor_settings_supported"] = True
        geometry["room_naming"] = {"max_length": MAX_ROOM_NAME_LENGTH, "types": ROOM_TYPES}
        geometry["editable_rooms"] = [
            {
                "id": room.region_id,
                "name": room.name,
                "adjacent": sorted(room.adjacent),
                "can_split": len(room.polygons) == 1,
                "room_type": room.room_type,
            }
            for room in plan.rooms
            if room.visible
        ]
        zone_ids = {region.region_id for region in floor.regions if region.kind is RegionKind.ZONE}
        geometry["unlinked_zone_count"] = sum(
            zone.region_id not in zone_ids for zone in plan.zone_outlines
        )
        geometry["editable_zones"] = [
            {
                "id": zone.region_id,
                "name": zone.name,
                "polygons": zone.polygons,
                "can_rename": bool(zone_corners(zone)),
                "destination_available": zone.region_id in zone_ids,
            }
            for zone in plan.zone_outlines
        ]
        geometry["furniture"] = {
            "editable": can_edit_furniture(plan),
            "types": {kind: label for kind, (_, label) in FURNITURE_TYPES.items()},
            "destinations": [
                {
                    "id": item.segment_id(floor.map_id),
                    "name": item.name,
                    "object_id": item.region_id,
                    "outline": item.outline,
                }
                for item in furniture_regions(plan)
            ],
            "items": [
                {
                    "id": item.identifier,
                    "kind": item.kind,
                    "source": item.source,
                    "points": item.points,
                    "pose": furniture_pose(item),
                    "cleaning_area": item.cleaning_area,
                }
                for item in (plan.furniture or ())
            ],
        }
        shapes.extend(
            {"id": None, "kind": "zone", "name": zone.name, "polygons": zone.polygons}
            for zone in plan.zone_outlines
            if zone.region_id not in zone_ids
        )
    if plan.policy_shapes is not None:
        geometry["editable_restrictions"] = [
            {"id": shape.identifier, "kind": shape.kind, "points": shape.points}
            for shape in plan.policy_shapes
        ]
    return geometry


def remembered_cleaning(floor, plan, capabilities):
    active = {(RegionKind.ROOM, room.region_id) for room in plan.rooms if room.visible}
    active.update((RegionKind.ZONE, zone.region_id) for zone in plan.zone_outlines)
    return {
        region.segment_id(floor.map_id): region.remembered.action_response(capabilities)
        for region in floor.regions
        if region.remembered is not None and (region.kind, region.region_id) in active
    }


def _live_position(path, now):
    batch = path.latest
    if batch.expires <= now.timestamp():
        return None
    latest = batch.positions[-1]
    return {
        "x": latest.x,
        "y": latest.y,
        "orientation": latest.orientation,
        "expires_at": batch.expires,
        "timestamp": batch.timestamp,
        "index": batch.index + len(batch.positions) - 1,
    }


def _live_trail(path, known=None):
    return [
        (index, point.x, point.y, POSITION_ACTIVITIES.get(point.modes))
        for index, point in path.points
        if known is None or known.get(index) != point
    ]


def _coverage_rows(covered, known):
    return [(row, runs) for row, runs in sorted(covered.items()) if known.get(row) != runs]


def live_geometry(path, floor, now, covered=None, obstacles=()):
    if path is None or path.map_version != (floor.map_id, floor.version_id):
        return {"trail": [], "position": None}
    result = {"trail": _live_trail(path), "position": _live_position(path, now)}
    if covered:
        result["coverage"] = {"cell_size": CELL_SIZE, "rows": _coverage_rows(covered, {})}
    if obstacles:
        result["obstacles"] = obstacles
    return result


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/live_positions",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("map_id"): IDENTIFIER,
        vol.Required("version"): IDENTIFIER,
    }
)
@callback
def websocket_live_positions(hass, connection, message):
    entity_id = message["entity_id"]
    identifier = message["id"]
    if not connection.user.permissions.check_entity(entity_id, POLICY_READ):
        connection.send_error(identifier, websocket_api.ERR_UNAUTHORIZED, "Access denied.")
        return
    component = hass.data.get(DATA_COMPONENT)
    vacuum = component.get_entity(entity_id) if component else None
    if not isinstance(vacuum, RoombaVacuum) or not vacuum.account.show_maps:
        connection.send_error(identifier, "map_unavailable", "Floor maps are unavailable.")
        return
    account, robot_id = vacuum.account, vacuum.robot_id
    scope = message["map_id"], message["version"]

    def current_floor():
        return any(
            (floor.map_id, floor.version_id) == scope for floor in account.maps_for_robot(robot_id)
        )

    if not current_floor():
        connection.send_error(identifier, "map_unavailable", "Floor maps are unavailable.")
        return
    generation, known, known_coverage, last_position, last_obstacles = None, {}, {}, None, ()

    @callback
    def publish():
        nonlocal generation, known, known_coverage, last_position, last_obstacles
        path = account.live_path(robot_id)
        if (
            path is None
            or path.map_version != scope
            or not account.show_maps
            or not account.last_update_success
            or not current_floor()
            or not connection.user.permissions.check_entity(entity_id, POLICY_READ)
        ):
            if generation is not None:
                connection.send_message(
                    websocket_api.event_message(
                        identifier, {"reset": True, "trail": [], "position": None}
                    )
                )
                generation, known, known_coverage, last_position, last_obstacles = (
                    None,
                    {},
                    {},
                    None,
                    (),
                )
            return
        reset = path.started != generation
        trail = _live_trail(path, None if reset else known)
        now = datetime.now(UTC)
        position = _live_position(path, now)
        covered = account.live_coverage_rows(robot_id, path)
        coverage_delta = _coverage_rows(covered, {} if reset else known_coverage)
        obstacles = account.live_obstacles(robot_id, path, now)
        obstacles_changed = obstacles != (() if reset else last_obstacles)
        if reset or trail or position != last_position or coverage_delta or obstacles_changed:
            event = {"reset": reset, "trail": trail, "position": position}
            if coverage_delta:
                event["coverage"] = {"cell_size": CELL_SIZE, "rows": coverage_delta}
            if obstacles_changed:
                event["obstacles"] = obstacles
            connection.send_message(websocket_api.event_message(identifier, event))
            generation = path.started
            known = dict(path.points)
            known_coverage = dict(covered)
            last_position = position
            last_obstacles = obstacles

    connection.subscriptions[identifier] = account.async_add_listener(publish)
    connection.send_result(identifier)
    publish()


def live_point_geometry(reading, floor):
    if reading is None:
        return None
    point, expires = reading
    target = point.target
    if (target.map_id, target.version_id) != (floor.map_id, floor.version_id):
        return None
    return {"center": target.center, "mode": point.mode, "expires_at": expires}


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/cleaning_scores",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("map_id"): IDENTIFIER,
        vol.Required("version"): IDENTIFIER,
    }
)
@websocket_api.async_response
async def websocket_cleaning_scores(hass, connection, message):
    await _send_floor_details(hass, connection, message, "async_map_cleaning_scores")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/floor_routines",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("map_id"): IDENTIFIER,
        vol.Required("version"): IDENTIFIER,
        vol.Optional("include_saved", default=False): bool,
    }
)
@websocket_api.async_response
async def websocket_floor_routines(hass, connection, message):
    await _send_floor_details(
        hass, connection, message, "async_list_map_routines", include_saved=message["include_saved"]
    )


async def _send_floor_details(hass, connection, message, method, **options):
    entity_id = message["entity_id"]
    if not connection.user.permissions.check_entity(entity_id, POLICY_READ):
        connection.send_error(message["id"], websocket_api.ERR_UNAUTHORIZED, "Access denied.")
        return
    component = hass.data.get(DATA_COMPONENT)
    vacuum = component.get_entity(entity_id) if component else None
    if not isinstance(vacuum, RoombaVacuum):
        connection.send_error(message["id"], "map_unavailable", "Floor maps are unavailable.")
        return
    try:
        response = await getattr(vacuum.account, method)(
            vacuum.robot_id, message["map_id"], message["version"], **options
        )
    except AuthenticationError:
        connection.send_error(message["id"], "map_unavailable", "Authentication is required.")
        return
    except HomeAssistantError as error:
        connection.send_error(message["id"], error.translation_key or "map_unavailable", str(error))
        return
    connection.send_result(message["id"], response)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/mission_history",
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("report_id"): vol.All(str, vol.Match(r"[a-f0-9]{64}\Z")),
        vol.Optional("map_index", default=0): vol.All(int, vol.Range(min=0)),
        vol.Optional("include_short_canceled", default=False): bool,
        vol.Optional("history_days", default=DEFAULT_HISTORY_DAYS): vol.All(
            int, vol.In(HISTORY_WINDOWS)
        ),
    }
)
@websocket_api.async_response
async def websocket_mission_history(hass, connection, message):
    entity_id = message["entity_id"]
    if not connection.user.permissions.check_entity(entity_id, POLICY_READ):
        connection.send_error(message["id"], websocket_api.ERR_UNAUTHORIZED, "Access denied.")
        return
    component = hass.data.get(DATA_COMPONENT)
    vacuum = component.get_entity(entity_id) if component else None
    if not isinstance(vacuum, RoombaVacuum):
        connection.send_error(
            message["id"], "history_unavailable", "Cleaning history is unavailable."
        )
        return
    try:
        history = await vacuum.account.async_mission_history(
            vacuum.robot_id,
            message.get("report_id"),
            message["map_index"],
            include_short_canceled=message["include_short_canceled"],
            history_days=message["history_days"],
        )
    except AuthenticationError:
        connection.send_error(message["id"], "history_unavailable", "Authentication is required.")
        return
    except HomeAssistantError as error:
        connection.send_error(
            message["id"], error.translation_key or "history_unavailable", str(error)
        )
        return
    connection.send_result(message["id"], history)


@websocket_api.websocket_command(
    {"type": "roomba_home/maintenance", vol.Required("entity_id"): cv.entity_id}
)
@callback
def websocket_maintenance(hass, connection, message):
    entity_id = message["entity_id"]
    if not connection.user.permissions.check_entity(entity_id, POLICY_READ):
        connection.send_error(message["id"], websocket_api.ERR_UNAUTHORIZED, "Access denied.")
        return
    component = hass.data.get(DATA_COMPONENT)
    vacuum = component.get_entity(entity_id) if component else None
    if not isinstance(vacuum, RoombaVacuum) or vacuum.robot is None:
        connection.send_error(
            message["id"], "maintenance_unavailable", "Maintenance is unavailable."
        )
        return
    state = vacuum.robot
    counters_available = (
        vacuum.account.last_update_success and state.telemetry.get("parts_available") is True
    )
    connection.send_result(
        message["id"],
        {
            "robot": state.name,
            "parts": maintenance_parts(
                state.telemetry,
                dock_recognized=state.capabilities.dock.recognized is True,
                counters_available=counters_available,
            ),
            "counters_available": counters_available,
        },
    )


@websocket_api.websocket_command(
    {"type": "roomba_home/robot_help", vol.Required("entity_id"): cv.entity_id}
)
@websocket_api.async_response
async def websocket_robot_help(hass, connection, message):
    entity_id = message["entity_id"]
    if not connection.user.permissions.check_entity(entity_id, POLICY_READ):
        connection.send_error(message["id"], websocket_api.ERR_UNAUTHORIZED, "Access denied.")
        return
    component = hass.data.get(DATA_COMPONENT)
    vacuum = component.get_entity(entity_id) if component else None
    if not isinstance(vacuum, RoombaVacuum):
        connection.send_error(message["id"], "robot_help_unavailable", "Robot help is unavailable.")
        return
    try:
        catalog = await vacuum.async_get_robot_help()
    except HomeAssistantError as error:
        connection.send_error(
            message["id"], error.translation_key or "robot_help_unavailable", str(error)
        )
        return
    connection.send_result(message["id"], catalog)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/floor_plan",
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("map_id"): IDENTIFIER,
        vol.Optional("known_map_id"): IDENTIFIER,
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
    ):
        connection.send_error(message["id"], "map_unavailable", "Floor maps are unavailable.")
        return
    can_control = connection.user.permissions.check_entity(entity_id, POLICY_CONTROL)
    cleaning = state.capabilities.cleaning
    can_clean_everywhere = (
        can_control
        and bool(cleaning.modes)
        and state.connected is True
        and state.activity in {"docked", "idle"}
        and state.cycle == "none"
    )
    mapping = {
        "can_start": can_control and state.capabilities.persistent_maps is True,
        "activity": (state.activity or "mapping") if state.mapping is True else None,
    }
    now = datetime.now(UTC)
    mission = current_mission(state, now)
    controls = mission_review(robot_id, control_snapshot(state)) if can_control else None
    errors = active_device_errors(state)
    if not maps:
        connection.send_result(
            message["id"],
            {
                "robot": state.name,
                "map": None,
                "maps": [],
                "mapping": mapping,
                "current_mission": mission,
                "mission_controls": controls,
                "active_errors": errors,
                "can_clean_everywhere": can_clean_everywhere,
            },
        )
        return
    live_floor = account.live_floor(state)
    known_id = message.get("known_map_id", requested)
    known_floor = next((item for item in maps if item.map_id == known_id), maps[0])
    floor = next((item for item in maps if item.map_id == requested), live_floor or known_floor)
    active_floor = floor == live_floor
    # The archive revision and the associated region inventory can change independently.
    inventory_id = floor.inventory_id
    can_clean_point = can_control and supports_point_clean(state.capabilities.digital_spot)
    path = account.live_path(robot_id) if active_floor else None
    live = live_geometry(
        path,
        floor,
        now,
        account.live_coverage_rows(robot_id, path),
        account.live_obstacles(robot_id, path, now),
    )
    position_available = live["position"] is not None
    response = {
        "robot": state.name,
        "mapping": mapping,
        "current_mission": mission,
        "mission_controls": controls,
        "active_errors": errors,
        "map": {"id": floor.map_id, "version": floor.version_id},
        "inventory_id": inventory_id,
        "floor_settings": {
            "id": floor.settings_id,
            "name": floor.name,
            "name_max_length": floor_name_limit(floor),
            "orientation": floor.orientation,
        },
        "can_edit_rooms": can_control,
        "can_manage_schedules": can_control and state.capabilities.schedules is True,
        "can_clean_everywhere": can_clean_everywhere,
        "can_clean_point": can_clean_point,
        "point_modes": [mode for mode in CleaningMode if mode in (cleaning.modes or ())]
        if can_clean_point
        else [],
        "skip_review": account.skip_review_for_robot(robot_id)
        if can_control and active_floor
        else None,
        "cleaning": {
            "modes": sorted(cleaning.modes or ()),
            "default_mode": account.profile(robot_id).mode,
            "presets": routine_presets(state.sku, state.capabilities),
            "supports_smart_presets": supports_routine_presets(state.sku, state.capabilities),
            "suction_level": cleaning.maximum_level("suction_level"),
            "wetness_level": cleaning.maximum_level("wetness_level"),
            **{
                field: cleaning.supports_option(field)
                for field in ("two_pass", "smart_scrub", "carpet_boost")
            },
        },
        "maps": [{"id": item.map_id, "name": item.name} for item in maps],
        "current_room": state.telemetry.get("current_room") if position_available else None,
        "on_mapped_carpet": state.telemetry.get("on_mapped_carpet") if position_available else None,
        "last_mission_rooms": state.telemetry.get("last_mission_rooms", []),
        "last_mission_zones": state.telemetry.get("last_mission_zones", []),
        "active_rooms": state.telemetry.get("live_timeline_active_rooms", [])
        if active_floor
        else [],
        "active_zones": state.telemetry.get("live_timeline_active_zones", [])
        if active_floor
        else [],
        "live_plan": account.live_plan(state, floor, now),
        "live": live,
        "active_point": live_point_geometry(account.live_point(robot_id, now), floor),
    }
    needs_geometry = (
        known_id,
        message.get("known_version"),
        message.get("known_inventory", inventory_id),
    ) != (
        floor.map_id,
        floor.version_id,
        inventory_id,
    )
    if needs_geometry or any(region.remembered is not None for region in floor.regions):
        plan = await account.async_floor_plan(robot_id, floor)
        current = next((item for item in account.maps_for_robot(robot_id) if item == floor), None)
        if plan is not None and current is not None:
            if needs_geometry:
                response["geometry"] = map_geometry(current, plan)
            if remembered := remembered_cleaning(current, plan, cleaning):
                response["remembered_cleaning"] = remembered
        elif needs_geometry:
            connection.send_error(message["id"], "map_unavailable", "Floor maps are unavailable.")
            return
    connection.send_result(message["id"], response)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/edit_floor_settings",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("map_id"): IDENTIFIER,
        vol.Required("version"): IDENTIFIER,
        vol.Required("inventory_id"): IDENTIFIER,
        vol.Required("settings_id"): IDENTIFIER,
        vol.Required("operation"): vol.In(("rename", "rotate")),
        vol.Optional("name"): vol.All(str, vol.Length(min=1, max=MAX_INITIAL_FLOOR_NAME_LENGTH)),
        vol.Optional("quarter_turns"): vol.In((1, 2, 3)),
    }
)
@websocket_api.async_response
async def websocket_edit_floor_settings(hass, connection, message):
    await _edit_map(
        hass,
        connection,
        message,
        "async_edit_floor_settings",
        message["operation"],
        message["settings_id"],
        message.get("name"),
        message.get("quarter_turns"),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/remove_floor",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("map_id"): IDENTIFIER,
        vol.Required("version"): IDENTIFIER,
        vol.Required("inventory_id"): IDENTIFIER,
        vol.Required("settings_id"): IDENTIFIER,
        vol.Required("confirmed"): vol.All(bool, vol.In([True])),
    }
)
@websocket_api.async_response
async def websocket_remove_floor(hass, connection, message):
    await _edit_map(hass, connection, message, "async_remove_floor", message["settings_id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/edit_rooms",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("map_id"): IDENTIFIER,
        vol.Required("version"): IDENTIFIER,
        vol.Required("inventory_id"): IDENTIFIER,
        vol.Required("operation"): vol.In(("split", "merge", "rename")),
        vol.Required("room_ids"): vol.All([IDENTIFIER], vol.Length(min=1, max=2)),
        vol.Optional("split_points"): vol.All([vol.Any(int, float)], vol.Length(min=4, max=4)),
        vol.Optional("name"): vol.All(str, vol.Length(min=1, max=MAX_ROOM_NAME_LENGTH)),
        vol.Optional("room_type"): vol.In(tuple(ROOM_TYPES)),
    }
)
@websocket_api.async_response
async def websocket_edit_rooms(hass, connection, message):
    await _edit_map(
        hass,
        connection,
        message,
        "async_edit_rooms",
        message["operation"],
        message["room_ids"],
        message.get("split_points"),
        message.get("name"),
        message.get("room_type"),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/edit_zones",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("map_id"): IDENTIFIER,
        vol.Required("version"): IDENTIFIER,
        vol.Required("inventory_id"): IDENTIFIER,
        vol.Required("operation"): vol.In(("create", "update", "delete")),
        vol.Optional("zone_id"): IDENTIFIER,
        vol.Optional("name"): vol.All(str, vol.Length(min=1, max=16)),
        vol.Optional("bounds"): vol.All([vol.Any(int, float)], vol.Length(min=4, max=4)),
    }
)
@websocket_api.async_response
async def websocket_edit_zones(hass, connection, message):
    await _edit_map(
        hass,
        connection,
        message,
        "async_edit_zones",
        message["operation"],
        message.get("zone_id"),
        message.get("name"),
        message.get("bounds"),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/edit_restrictions",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("map_id"): IDENTIFIER,
        vol.Required("version"): IDENTIFIER,
        vol.Required("inventory_id"): IDENTIFIER,
        vol.Required("operation"): vol.In(("create", "update", "delete")),
        vol.Optional("zone_id"): IDENTIFIER,
        vol.Optional("kind"): vol.In(tuple(kind.value for kind in EDITABLE_RESTRICTIONS)),
        vol.Optional("bounds"): vol.All([vol.Any(int, float)], vol.Length(min=4, max=4)),
    }
)
@websocket_api.async_response
async def websocket_edit_restrictions(hass, connection, message):
    await _edit_map(
        hass,
        connection,
        message,
        "async_edit_restrictions",
        message["operation"],
        message.get("zone_id"),
        message.get("kind"),
        message.get("bounds"),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "roomba_home/edit_furniture",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("map_id"): IDENTIFIER,
        vol.Required("version"): IDENTIFIER,
        vol.Required("inventory_id"): IDENTIFIER,
        vol.Required("operation"): vol.In(("create", "update", "delete")),
        vol.Optional("object_id"): IDENTIFIER,
        vol.Optional("kind"): vol.In(tuple(FURNITURE_TYPES)),
        vol.Optional("pose"): vol.All([vol.Any(int, float)], vol.Length(min=5, max=5)),
    }
)
@websocket_api.async_response
async def websocket_edit_furniture(hass, connection, message):
    await _edit_map(
        hass,
        connection,
        message,
        "async_edit_furniture",
        message["operation"],
        message.get("object_id"),
        message.get("kind"),
        message.get("pose"),
    )


async def _edit_map(hass, connection, message, method, *options):
    entity_id = message["entity_id"]
    if not connection.user.permissions.check_entity(entity_id, POLICY_CONTROL):
        connection.send_error(message["id"], websocket_api.ERR_UNAUTHORIZED, "Access denied.")
        return
    component = hass.data.get(DATA_COMPONENT)
    vacuum = component.get_entity(entity_id) if component else None
    if not isinstance(vacuum, RoombaVacuum):
        connection.send_error(message["id"], "map_unavailable", "Floor maps are unavailable.")
        return
    try:
        result = await getattr(vacuum.account, method)(
            vacuum.robot_id,
            message["map_id"],
            message["version"],
            message["inventory_id"],
            *options,
        )
    except AuthenticationError:
        connection.send_error(message["id"], "room_edit_failed", "Authentication is required.")
        return
    except HomeAssistantError as error:
        connection.send_error(
            message["id"], error.translation_key or "room_edit_failed", str(error)
        )
        return
    connection.send_result(message["id"], result)
