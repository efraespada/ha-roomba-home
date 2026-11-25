"""Project the destinations and outcomes declared by a live mission timeline."""

from dataclasses import dataclass

from .cleaning import CleaningMode, CleaningProfile
from .cleaning_protocol import parse_regional_profile, requested_region_mode
from .furniture_targets import furniture_links
from .history import ROOM_STATUSES, AreaResult, command_region_kind
from .maps import PersistentMap, RegionKind, map_identifier
from .telemetry import at

DESTINATION_KINDS = {
    RegionKind.ROOM: "room",
    RegionKind.ZONE: "saved_zone",
    RegionKind.FURNITURE: "furniture",
}
MAX_DESTINATIONS = 32


@dataclass(frozen=True, repr=False)
class MissionDestination:
    kind: str
    identity: tuple[str, str, str]
    mode: CleaningMode | None
    profile: CleaningProfile | None = None


@dataclass(frozen=True, repr=False)
class MissionPlan:
    scope: tuple[str, str]
    ordered: bool
    destinations: tuple[MissionDestination, ...]


def mission_plan(command: object) -> MissionPlan | None:
    if (
        not isinstance(command, dict)
        or command.get("command") != "start"
        or command.get("select_all") is True
        or not isinstance(regions := command.get("regions"), list)
        or not 1 <= len(regions) <= MAX_DESTINATIONS
    ):
        return None
    scope = command.get("p2map_id"), command.get("user_p2mapv_id")
    if not all(map_identifier(value) for value in scope):
        return None
    destinations = []
    links = furniture_links(command.get("id_multipolys"))
    common = command.get("params", {})
    for region in regions:
        if (
            not isinstance(region, dict)
            or (kind := command_region_kind(region)) is None
            or not map_identifier(identity := region.get("region_id"))
        ):
            return None
        if kind == "tid":
            identity, area_kind = (
                (links[identity], "furniture")
                if identity in links
                else (identity, "temporary_zone")
            )
        else:
            area_kind = DESTINATION_KINDS[RegionKind(kind)]
        local = region.get("params", {})
        params = common | local if isinstance(common, dict) and isinstance(local, dict) else {}
        mode = requested_region_mode(params.get("operatingMode")) or requested_region_mode(
            at(region, "params.operatingMode")
        )
        destinations.append(
            MissionDestination(area_kind, (*scope, identity), mode, parse_regional_profile(params))
        )
    if len({(item.kind, item.identity) for item in destinations}) != len(destinations):
        return None
    ordered = command.get("ordered")
    ordered_visit = len(destinations) == 1 or type(ordered) is int and ordered == 1
    return MissionPlan(scope, ordered_visit, tuple(destinations))


def present_mission_plan(
    plan: MissionPlan,
    final: tuple[AreaResult, ...],
    active: tuple[AreaResult, ...],
    travelling: AreaResult | None,
    maps: tuple[PersistentMap, ...],
) -> dict:
    names = {
        (DESTINATION_KINDS[region.kind], (*plan.scope, region.region_id)): region.name
        for floor in maps
        if (floor.map_id, floor.version_id) == plan.scope
        for region in floor.regions
    }
    results = {_destination_key(plan, area): area for area in final}
    current = {_destination_key(plan, area) for area in active}
    en_route = _destination_key(plan, travelling) if travelling is not None else None
    destinations = []
    for destination in plan.destinations:
        key = destination.kind, destination.identity
        if key in current:
            status = "in_progress"
        elif key == en_route:
            status = "traveling"
        else:
            result = results.get(key)
            status = (
                ROOM_STATUSES.get(result.status, "unknown") if result is not None else "pending"
            )
        row = {"kind": destination.kind, "name": names.get(key), "status": status}
        if destination.mode is not None:
            row["mode"] = destination.mode.value
        destinations.append(row)
    return {
        "ordered": plan.ordered,
        "destinations": destinations,
        "completed": sum(item["status"] == "finished" for item in destinations),
        "total": len(destinations),
    }


def _destination_key(plan: MissionPlan, area: AreaResult) -> tuple[str, tuple[str, str, str]]:
    map_id, revision, region = area.identity
    # A matched timeline uses the robot's internal revision for room events.
    # A declared room ID on the same map belongs to the command's user revision.
    if area.kind == "room" and map_id == plan.scope[0]:
        revision = plan.scope[1]
    return area.kind, (map_id, revision, region)
