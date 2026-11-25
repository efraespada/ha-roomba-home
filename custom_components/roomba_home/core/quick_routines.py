"""Interpret Roomba's floor-scoped recent and suggested routines as drafts."""

from math import dist

from .capabilities import DeviceCapabilities, supports_point_clean
from .cleaning import CleaningMode, CleaningProfile
from .errors import ProtocolError
from .furniture_targets import furniture_links
from .maps import FurnitureRegion, PersistentMap, RegionKind, command_region_id, map_identifier
from .routines import routine_region_profile
from .telemetry import convert, integer

QUICK_ROUTINE_LIMIT = 5
_FURNITURE_TOLERANCE_METRES = 0.001
_COMMAND_FIELDS = {"command", "p2map_id", "robot_id", "params"}
_REPLAY_FIELDS = {*_COMMAND_FIELDS, "user_p2mapv_id", "regions", "ordered", "id_multipolys"}
_KINDS = {
    "REPLAY": ("recent", "Recent cleaning", "start"),
    "CLEAN_ALL": ("clean_all", "Clean all rooms", "start"),
    "SPOT_CLEAN": ("spot_clean", "Clean a point", "point_clean"),
}


def read_quick_routines(
    document: object, robot_id: str, floor: PersistentMap, capabilities: DeviceCapabilities
) -> dict:
    """Scope the native list to the reviewed robot and floor and ignore unknown types."""
    if not isinstance(document, list):
        raise ProtocolError("Expected Roomba's quick cleaning routines.")
    rooms = [room for room in floor.regions if room.kind is RegionKind.ROOM]
    current = {region.segment_id(floor.map_id): region for region in floor.regions}
    items = []
    for row in document[:QUICK_ROUTINE_LIMIT]:
        if not isinstance(row, dict) or not isinstance(commands := row.get("commanddefs"), list):
            continue
        if len(commands) != 1 or not isinstance(command := commands[0], dict):
            continue
        params = command.get("params")
        if (
            command.get("robot_id") != robot_id
            or command.get("p2map_id") != floor.map_id
            or not isinstance(params, dict)
            or not isinstance(kind := params.get("routine_type"), str)
            or kind not in _KINDS
        ):
            continue
        key, label, start_command = _KINDS[kind]
        if command.get("command") != start_command:
            continue
        draft = None
        choose_point = False
        if kind == "REPLAY":
            draft = _replay_regions(command, params, floor, current, capabilities)
        elif command.keys() == _COMMAND_FIELDS and params.keys() == {"routine_type"}:
            if kind == "CLEAN_ALL" and 1 <= len(rooms) <= 32:
                draft = [{"id": room.segment_id(floor.map_id)} for room in rooms]
            elif kind == "SPOT_CLEAN":
                choose_point = bool(rooms) and supports_point_clean(capabilities.digital_spot)
        stamp = convert("timestamp", row.get("last_run"))
        items.append(
            {
                "kind": key,
                "name": label,
                "last_run": stamp.isoformat() if stamp is not None else None,
                "duration_seconds": integer(row.get("time_estimate_seconds")),
                "region_settings": draft,
                "choose_point": choose_point,
            }
        )
    return {"map_id": floor.map_id, "version": floor.version_id, "routines": items}


def _replay_regions(command, params, floor, current, capabilities):
    if (
        command.keys() - _REPLAY_FIELDS
        or not map_identifier(command.get("user_p2mapv_id"))
        or not isinstance(replay := params.get("replay_of"), str)
        or not replay
        or not isinstance(regions := command.get("regions"), list)
        or not 1 <= len(regions) <= 32
    ):
        return None
    order = command.get("ordered")
    if (len(regions) > 1 or "ordered" in command) and (type(order) is not int or order != 1):
        return None
    polygons = command.get("id_multipolys", [])
    links = furniture_links(polygons)
    if not isinstance(polygons, list) or len(links) != len(polygons):
        return None
    outlines = {polygon["id"]: polygon["poly"] for polygon in polygons}
    global_preferences = {
        key: value for key, value in params.items() if key not in {"routine_type", "replay_of"}
    }
    result = {}
    used_links = set()
    for region in regions:
        if (
            not isinstance(region, dict)
            or region.keys() - {"region_id", "type", "params", "region_name", "region_type"}
            or region.get("region_type", region.get("type")) != region.get("type")
            or not isinstance(local := region.get("params", {}), dict)
        ):
            return None
        native_id = region.get("region_id")
        if region.get("type") == "tid":
            if not map_identifier(native_id) or native_id not in links:
                return None
            identifier = f"{floor.map_id}:{RegionKind.FURNITURE}:{links[native_id]}"
            furniture = current.get(identifier)
            if not isinstance(furniture, FurnitureRegion) or not _matches_outline(
                outlines[native_id], furniture
            ):
                return None
            used_links.add(native_id)
        else:
            identifier = command_region_id(floor.map_id, region)
        if identifier not in current or identifier in result:
            return None
        profile = routine_region_profile(
            {"region_id": native_id, "type": region["type"], "params": global_preferences | local}
        )
        if profile is None:
            return None
        try:
            CleaningProfile(**(profile | {"mode": CleaningMode(profile["mode"])})).validate(
                capabilities.cleaning
            )
        except ValueError:
            return None
        result[identifier] = {"id": identifier, **profile}
    return list(result.values()) if used_links == links.keys() else None


def _matches_outline(points, furniture):
    return all(
        min(dist(point, corner) for corner in furniture.outline) <= _FURNITURE_TOLERANCE_METRES
        for point in points
    )
