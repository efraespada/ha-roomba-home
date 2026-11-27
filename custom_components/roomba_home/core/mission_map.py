"""Read-only geometry from the exact map archive referenced by a cleaning report."""

from dataclasses import replace

from .furniture_targets import furniture_regions
from .map_snapshots import read_snapshot_archive
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


def _floor_and_plan(docs, map_id, version_id):
    floor = PersistentMap(map_id, version_id, None, ())
    plan = _floor_plan_documents(docs, floor)
    floor = with_archive_destinations(floor, plan)
    return replace(floor, regions=(*floor.regions, *furniture_regions(plan))), plan


def _report_geometry(docs, plan):
    return {
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


def read_mission_map(data: bytes, map_id: str, version_id: str) -> tuple[PersistentMap, dict]:
    docs = _map_documents(data, map_id, version_id, MISSION_LAYERS)
    floor, plan = _floor_and_plan(docs, map_id, version_id)
    return floor, _report_geometry(docs, plan)


def read_requested_floor(data, map_id, version_id, itinerary, footprints):
    """Read a base floor, with destination outlines for the exact requested revision."""
    docs = _map_documents(data, map_id, version_id)
    floor, plan = _floor_and_plan(docs, map_id, version_id)
    zones = {zone.region_id: zone.polygons for zone in (*plan.zones, *plan.zone_outlines)}
    targets = {
        "room": {room.region_id: room.polygons for room in plan.rooms},
        "saved_zone": zones,
    }
    exact_plan = itinerary is not None and itinerary.scope == (map_id, version_id)
    destinations = itinerary.destinations if exact_plan else ()
    requested = tuple(
        polygon
        for destination in destinations
        for polygon in targets.get(destination.kind, {}).get(destination.identity[2], ())
    )
    outlines = (*requested, *footprints) if exact_plan else ()
    return floor, {**_report_geometry(docs, plan), "requested_areas": outlines}


def read_backed_up_floor(snapshot, scope, itinerary, footprints):
    """Read a verified local archive with the same manifest validation as a provider read."""
    _, archive = read_snapshot_archive(snapshot)
    return read_requested_floor(archive, *scope, itinerary, footprints)
