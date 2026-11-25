"""Read-only geometry from the exact map archive referenced by a cleaning report."""

from .maps import PersistentMap
from .point_maps import (
    _coordinates,
    _display_features,
    _dock_points,
    _floor_plan_documents,
    _map_documents,
    _polygons,
    with_archive_destinations,
)
from .telemetry import integer

MISSION_LAYERS = ("coverage", "trajectories", "hazard", "adHocCleanZones")
MOVEMENT_MODES = frozenset({"vacuuming", "mopping", "traveling"})


def _operating_modes(properties: dict) -> tuple[str, ...]:
    modes = properties.get("operatingModes")
    if not isinstance(modes, list):
        return ()
    return tuple(
        dict.fromkeys(mode for mode in modes if isinstance(mode, str) and mode in MOVEMENT_MODES)
    )


def _coverage(feature: dict) -> tuple[dict, ...]:
    return ({"modes": _operating_modes(feature["properties"]), "polygons": _polygons(feature)},)


def _trajectory(feature: dict) -> tuple[dict, ...]:
    props, geometry = feature["properties"], feature["geometry"]
    index = integer(props.get("index"))
    if index is None or geometry.get("type") != "LineString":
        return ()
    points = _coordinates(geometry["coordinates"])
    if len(points) < 2:
        return ()
    return ({"index": index, "modes": _operating_modes(props), "points": points},)


def read_mission_map(data: bytes, map_id: str, version_id: str) -> tuple[PersistentMap, dict]:
    docs = _map_documents(data, map_id, version_id, MISSION_LAYERS)
    floor = PersistentMap(map_id, version_id, None, ())
    plan = _floor_plan_documents(docs, floor)
    return with_archive_destinations(floor, plan), {
        "rooms": [{"name": room.name, "polygons": room.polygons} for room in plan.rooms],
        "borders": _display_features(docs, "borders", _polygons),
        "walls": [{"kind": kind, "points": points} for kind, points in plan.walls],
        "furniture": [{"kind": item.kind, "points": item.points} for item in plan.furniture or ()],
        "carpets": plan.carpets,
        "docks": plan.docks,
        "saved_zones": _display_features(docs, "cleanZones", _polygons),
        "keep_out": plan.keep_out,
        "no_mop": plan.no_mop,
        "virtual_walls": plan.virtual_walls,
        "hazards": _display_features(docs, "hazard", _dock_points),
        "temporary_zones": _display_features(docs, "adHocCleanZones", _polygons),
        "coverage": _display_features(docs, "coverage", _coverage),
        "trajectories": sorted(
            _display_features(docs, "trajectories", _trajectory), key=lambda path: path["index"]
        ),
    }
