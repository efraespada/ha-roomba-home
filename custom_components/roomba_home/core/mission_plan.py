"""Project the destinations and outcomes declared by a mission command."""

from dataclasses import asdict, dataclass

from .cleaning import CleaningMode, CleaningProfile
from .cleaning_protocol import parse_regional_profile, requested_region_mode
from .furniture_targets import furniture_links
from .maps import PersistentMap, RegionKind, map_identifier
from .mission_areas import ROOM_STATUSES, AreaResult, command_region_kind
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
    common = command.get("params")
    if common is None:
        common = {}
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
        local = region.get("params")
        if local is None:
            local = {}
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
    *,
    archived: bool = False,
) -> dict:
    """Historical callers supply only map revisions linked to the archived mission."""
    names = {
        (DESTINATION_KINDS[region.kind], (*plan.scope, region.region_id)): region.name
        for floor in maps
        if floor.map_id == plan.scope[0] and (archived or floor.version_id == plan.scope[1])
        for region in floor.regions
        if region.name is not None
    }
    results = {_destination_key(plan, area): area for area in final}
    current = {_destination_key(plan, area): area for area in active}
    en_route = _destination_key(plan, travelling) if travelling is not None else None
    missing = "unreported" if archived else "pending"
    destinations = []
    for destination in plan.destinations:
        key = destination.kind, destination.identity
        result = current.get(key, results.get(key))
        if key in current:
            status = "in_progress"
        elif key == en_route:
            status = "traveling"
        else:
            status = ROOM_STATUSES.get(result.status, "unknown") if result is not None else missing
        row = {"kind": destination.kind, "name": names.get(key), "status": status}
        if destination.mode is not None:
            row["mode"] = destination.mode.value
        if destination.profile is not None:
            settings = {
                name: value
                for name, value in asdict(destination.profile).items()
                if name != "mode" and value is not None
            }
            if settings:
                row["requested_settings"] = settings
        if result is not None and result.pass_count is not None:
            row["reported_pass_count"] = result.pass_count
        destinations.append(row)
    return {
        "ordered": plan.ordered,
        "destinations": destinations,
        "completed": sum(item["status"] == "finished" for item in destinations),
        "total": len(destinations),
    }


def _destination_key(plan: MissionPlan, area: AreaResult) -> tuple[str, tuple[str, str, str]]:
    map_id, revision, region = area.identity
    # A matched timeline can use the robot's internal revision for these events.
    if area.kind in {"room", "temporary_zone"} and map_id == plan.scope[0]:
        revision = plan.scope[1]
    return area.kind, (map_id, revision, region)
