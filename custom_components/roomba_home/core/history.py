"""Typed history summaries. Private mission, map and event data stay in the API response."""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from .errors import ProtocolError
from .furniture_targets import furniture_links
from .maps import PersistentMap, RegionKind, map_identifier
from .mission_areas import REGION_TARGETS, ROOM_STATUSES, AreaResult, command_region_kind
from .mission_plan import MissionPlan, mission_plan, present_mission_plan
from .mission_time import MissionTiming, reported_interruptions, with_destination_elapsed
from .state import RobotState
from .telemetry import CLEANING_CYCLES, at, convert, integer

OUTCOMES = {"ok": "completed", "cncl": "cancelled", "inc": "incomplete", "stuck": "stuck"}
MODES = {"vac": "vacuum", "mop": "mop", "vacmop": "vacuum_mop"}
HISTORY_COMMANDS = ("start", "spot", "point_clean")
TIMELINE_EVENTS = frozenset(
    {
        "start",
        "pause",
        "travel",
        "reloc",
        "room",
        "zone",
        "charge",
        "padWash",
        "refill",
        "evac",
        "error",
        "fin",
    }
)
HISTORY_DOCK_EVENTS = {
    "evac": ("evacuation", "state"),
    "padWash": ("pad_wash", "pwState"),
    "refill": ("refill", "frState"),
}
HISTORY_TARGETS = (
    "whole_map",
    *REGION_TARGETS.values(),
    "furniture",
    "mixed_regions",
    "map_point",
    "local_spot",
)
EXTRA_HISTORY_FIELDS = {
    "last_mission_started": ("startTime", "timestamp"),
    "last_mission_active_duration": ("runM", "int"),
    "last_mission_pause_duration": ("pauseM", "int"),
    "last_mission_charge_duration": ("chrgM", "int"),
    "last_mission_recharges": ("chrgs", "int"),
    "last_mission_evacuations": ("evacs", "int"),
    "last_mission_started_at_dock": ("dockedAtStart", "bool"),
    "last_mission_initiator": ("initiator", "initiator"),
}


def _area_events(events: object, kind: str, field: str) -> Iterable[AreaResult]:
    if not isinstance(events, list):
        return
    for event in events:
        if not isinstance(event, dict) or event.get("type") != kind:
            continue
        data = event.get(kind)
        if not isinstance(data, dict):
            continue
        key = (data.get("p2mapId"), data.get("p2mapvId"), data.get(field))
        timestamp = integer(event.get("ts"), 32_503_680_000)
        if timestamp is None or not all(map_identifier(value) for value in key):
            continue
        status, area, total, passes = (
            integer(data.get(field)) for field in ("status", "area", "totalArea", "passCount")
        )
        if all(value is None for value in (status, area, total, passes)):
            continue
        yield AreaResult(
            key,
            timestamp,
            status,
            area,
            total,
            passes,
            kind,
            ended_at=integer(event.get("ets"), 32_503_680_000),
        )


def _latest_area_results(events: Iterable[AreaResult]) -> tuple[AreaResult, ...]:
    results = {}
    completed_passes = {}
    for result in events:
        key = result.kind, result.identity
        earlier = results.get(key)
        if earlier is None or result.timestamp >= earlier.timestamp:
            results[key] = result
        if (
            result.kind == "saved_zone"
            and result.status in (0, 1)
            and result.pass_count is not None
        ):
            passes = completed_passes.setdefault(key, {})
            previous_pass = passes.get(result.pass_count)
            if previous_pass is None or result.timestamp >= previous_pass.timestamp:
                passes[result.pass_count] = result
    # Firmware uses zero-based pass indexes in saved-zone completion events.
    for key, passes in completed_passes.items():
        if 0 in passes:
            values = [event.total_area for event in passes.values() if event.total_area is not None]
            results[key] = replace(
                results[key],
                confirmed_completed_passes=len(passes),
                completed_passes_sqft=sum(values) if len(values) == len(passes) else None,
            )
    return tuple(sorted(results.values(), key=lambda area: area.timestamp))


def room_results(events: object) -> tuple[AreaResult, ...]:
    """Keep the newest reported result for each room and exact map revision."""
    return _latest_area_results(_area_events(events, "room", "rid"))


def zone_results(events: object, command: object = None) -> tuple[AreaResult, ...]:
    """Resolve zone events to the matching command's saved, temporary, or furniture target."""
    return identify_zones(tuple(_area_events(events, "zone", "zid")), command)


def identify_zones(results: tuple[AreaResult, ...], command: object) -> tuple[AreaResult, ...]:
    return _latest_area_results(_correlate_zones(results, command))


def _correlate_zones(results: tuple[AreaResult, ...], command: object) -> tuple[AreaResult, ...]:
    if not results or not isinstance(command, dict) or command.get("command") != "start":
        return results
    regions = command.get("regions")
    if not isinstance(regions, list):
        return results
    scope = command.get("p2map_id"), command.get("user_p2mapv_id")
    if not all(map_identifier(value) for value in scope):
        return results
    kinds = {
        region["region_id"]: kind
        for region in regions
        if isinstance(region, dict)
        and map_identifier(region.get("region_id"))
        and (kind := command_region_kind(region)) in {"tid", "zid"}
    }
    links = furniture_links(command.get("id_multipolys"))
    identified = []
    for result in results:
        identity = result.identity[2]
        # The robot can report a different revision from the requested user map.
        # Temporary IDs are scoped to this mission's embedded command and map.
        kind = kinds.get(identity) if result.identity[0] == scope[0] else None
        if kind == "zid":
            result = replace(result, identity=(*scope, identity), kind="saved_zone")
        elif kind == "tid":
            if furniture_id := links.get(identity):
                result = replace(result, identity=(*scope, furniture_id), kind="furniture")
            else:
                result = replace(result, kind="temporary_zone")
        identified.append(result)
    return tuple(identified)


def mission_timing(events: object, command: object) -> MissionTiming:
    """Preserve every timed area event before the outcome projection deduplicates them."""
    if not isinstance(events, list):
        return MissionTiming()
    rooms = tuple(_area_events(events, "room", "rid"))
    zones = _correlate_zones(tuple(_area_events(events, "zone", "zid")), command)
    return MissionTiming((*rooms, *zones), reported_interruptions(events))


def _public_result(area: AreaResult) -> dict:
    result = {
        "status": ROOM_STATUSES.get(area.status),
        "status_code": area.status,
        "area": area.area,
        "total_area": area.total_area,
        "pass_count": area.pass_count,
    }
    if area.confirmed_completed_passes is not None:
        result["confirmed_completed_passes"] = area.confirmed_completed_passes
    if area.kind == "saved_zone":
        if area.area is not None:
            result["target_area_m2"] = convert("area", area.area)
        if area.completed_passes_sqft is not None:
            result["completed_passes_area_m2"] = convert("area", area.completed_passes_sqft)
    return result


def present_rooms(results: tuple[AreaResult, ...], maps: tuple[PersistentMap, ...]) -> list[dict]:
    names = {
        (floor.map_id, floor.version_id, region.region_id): region.name
        for floor in maps
        for region in floor.regions
        if region.kind is RegionKind.ROOM
    }
    return [{"room": names.get(room.identity), **_public_result(room)} for room in results]


def present_zones(results: tuple[AreaResult, ...], maps: tuple[PersistentMap, ...]) -> list[dict]:
    kinds = {RegionKind.ZONE: "saved_zone", RegionKind.FURNITURE: "furniture"}
    names = {
        (kinds[region.kind], (floor.map_id, floor.version_id, region.region_id)): region.name
        for floor in maps
        for region in floor.regions
        if region.kind in kinds
    }
    zones = []
    for area in results:
        kind = area.kind
        if kind == "zone" and ("saved_zone", area.identity) in names:
            kind = "saved_zone"
        zones.append(
            {"kind": kind, "name": names.get((kind, area.identity)), **_public_result(area)}
        )
    return zones


def _terminal_mission_error(row: dict) -> int | None:
    events = at(row, "timeline.finEvents")
    if not isinstance(events, list):
        return None
    candidates = (
        (timestamp, index, code)
        for index, event in enumerate(events)
        if isinstance(event, dict)
        and event.get("type") == "error"
        and (timestamp := integer(event.get("ts"))) is not None
        and (code := integer(at(event, "error.value")))
    )
    return max(candidates, default=(0, 0, None))[2]


def _mission_target(command: dict) -> tuple[str | None, int | None]:
    match command.get("command"):
        case "point_clean":
            return "map_point", None
        case "spot":
            return "local_spot", None
        case "start":
            regions = command.get("regions")
        case _:
            return None, None
    if regions is not None and not isinstance(regions, list):
        return None, None
    if not regions:
        if any(command.get(key) for key in ("favorite_id", "geom", "id_multipolys")):
            return None, None
        return "whole_map", None
    targets = set()
    links = furniture_links(command.get("id_multipolys"))
    for region in regions:
        if not isinstance(region, dict) or (kind := command_region_kind(region)) is None:
            return None, None
        identity = region.get("region_id")
        targets.add(
            "furniture"
            if kind == "tid" and map_identifier(identity) and identity in links
            else REGION_TARGETS[kind]
        )
    return (next(iter(targets)) if len(targets) == 1 else "mixed_regions"), len(regions)


def ended_mission_start(previous: RobotState | None, current: RobotState) -> datetime | None:
    """Detect an ended mission, including a short one first seen during docking."""
    if (
        previous is None
        or previous.connected is not True
        or current.connected is not True
        or current.cycle not in {"none", "dock"}
    ):
        return None
    earlier = previous.telemetry.get("mission_started")
    latest = current.telemetry.get("mission_started")
    if previous.cycle in CLEANING_CYCLES and isinstance(earlier, datetime):
        return earlier
    if isinstance(latest, datetime) and (not isinstance(earlier, datetime) or latest > earlier):
        return latest
    return None


def history_includes_mission(snapshot: dict, started: datetime) -> bool:
    observed = snapshot.get("last_mission_started")
    return isinstance(observed, datetime) and observed >= started - timedelta(seconds=3)


def _history_rows(response: object, robot_id: str) -> list[dict]:
    if not isinstance(response, list):
        raise ProtocolError("Expected the Roomba Home mission list")
    return [
        row
        for row in response
        if isinstance(row, dict)
        and row.get("robot_id") == robot_id
        and integer(row.get("timestamp"), 32_503_680_000)
    ]


def history_metrics(response: object, robot_id: str) -> dict:
    rows = _history_rows(response, robot_id)
    if not rows:
        return {"history_count": 0}
    return {
        "history_count": len(rows),
        **_mission_metrics(max(rows, key=lambda row: row["timestamp"])),
    }


def _mission_metrics(row: dict) -> dict:
    outcome = row.get("done")
    mode_stats = row.get("oModeStats")
    modes = {}
    if isinstance(mode_stats, dict):
        for key, name in MODES.items():
            if isinstance(values := mode_stats.get(key), dict):
                modes[name] = {
                    "duration_minutes": integer(values.get("nMin")),
                    "area_m2": convert("area", values.get("sqft")),
                }
    result = {
        "last_mission_finished": datetime.fromtimestamp(row["timestamp"], UTC),
        "last_mission_duration": integer(row.get("durationM")),
        "last_mission_area": convert("area", row.get("sqft")),
        "last_mission_outcome": OUTCOMES.get(outcome) if isinstance(outcome, str) else None,
        "last_mission_modes": tuple(modes),
        "last_mission_mode_statistics": modes,
        **{
            key: convert(kind, row[wire])
            for key, (wire, kind) in EXTRA_HISTORY_FIELDS.items()
            if wire in row
        },
    }
    if (code := _terminal_mission_error(row)) is not None:
        result["last_mission_error"] = code
    events = at(row, "timeline.finEvents")
    if rooms := room_results(events):
        result["last_mission_room_results"] = rooms
    command = row.get("cmd")
    if zones := zone_results(events, command):
        result["last_mission_zone_results"] = zones
    if isinstance(command, dict):
        if command.get("command") in HISTORY_COMMANDS:
            result["last_mission_command"] = command["command"]
        target, count = _mission_target(command)
        if target is not None:
            result["last_mission_target"] = target
        if count is not None:
            result["last_mission_target_count"] = count
    return result


@dataclass(frozen=True, repr=False)
class MissionReport:
    key: str
    maps: tuple[tuple[str, str], ...]
    metrics: dict
    timeline: tuple[dict, ...]
    plan: MissionPlan | None = None
    destination_elapsed: tuple[int | None, ...] = ()

    def summary(self) -> dict:
        started = self.metrics.get("last_mission_started")
        return {
            "id": self.key,
            "started_at": started.isoformat() if started is not None else None,
            "finished_at": self.metrics["last_mission_finished"].isoformat(),
            "duration_minutes": self.metrics["last_mission_duration"],
            "area_m2": self.metrics["last_mission_area"],
            "outcome": self.metrics["last_mission_outcome"],
            "command": self.metrics["last_mission_command"],
            "target": self.metrics.get("last_mission_target"),
            "error_code": self.metrics.get("last_mission_error"),
            "map_count": len(self.maps),
        }

    def detail(
        self, floors: tuple[PersistentMap, ...], *, requested_floor: PersistentMap | None = None
    ) -> dict:
        rooms = self.metrics.get("last_mission_room_results", ())
        zones = self.metrics.get("last_mission_zone_results", ())
        archived = tuple(floor for floor in floors if (floor.map_id, floor.version_id) in self.maps)
        label_floors = (requested_floor, *archived) if requested_floor is not None else archived
        return {
            "mission": self.summary(),
            "active_minutes": self.metrics.get("last_mission_active_duration"),
            "pause_minutes": self.metrics.get("last_mission_pause_duration"),
            "charge_minutes": self.metrics.get("last_mission_charge_duration"),
            "recharges": self.metrics.get("last_mission_recharges"),
            "evacuations": self.metrics.get("last_mission_evacuations"),
            "started_at_dock": self.metrics.get("last_mission_started_at_dock"),
            "initiator": self.metrics.get("last_mission_initiator"),
            "modes": self.metrics["last_mission_mode_statistics"],
            "rooms": present_rooms(rooms, floors),
            "zones": present_zones(zones, floors),
            "timeline": self.timeline,
            "plan": (
                with_destination_elapsed(
                    present_mission_plan(
                        self.plan, (*rooms, *zones), (), None, label_floors, archived=True
                    ),
                    self.destination_elapsed,
                )
                if self.plan is not None
                else None
            ),
        }


def _report_maps(row: dict) -> tuple[tuple[str, str], ...]:
    values = row.get("p2maps")
    if not isinstance(values, list):
        return ()
    return tuple(
        dict.fromkeys(
            (item["p2map_id"], item["p2mapv_id"])
            for item in values
            if isinstance(item, dict)
            and map_identifier(item.get("p2map_id"))
            and map_identifier(item.get("p2mapv_id"))
        )
    )


def _report_event_details(item: dict, kind: str) -> dict:
    if kind == "error":
        code = integer(at(item, "error.value"))
        return {"error_code": code} if code else {}
    if (source := HISTORY_DOCK_EVENTS.get(kind)) is None:
        return {}
    component, state_key = source
    state = integer(at(item, f"{kind}.{state_key}"))
    error = integer(at(item, f"{kind}.error"))
    if state is None and error is None:
        return {}
    return {"dock": {"component": component, "state_code": state, "error_code": error}}


def _report_timeline(row: dict) -> tuple[dict, ...]:
    values = at(row, "timeline.finEvents")
    if not isinstance(values, list):
        return ()
    timeline = []
    for item in values:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        start = integer(item.get("ts"), 32_503_680_000)
        end = integer(item.get("ets"), 32_503_680_000)
        if not isinstance(kind, str) or kind not in TIMELINE_EVENTS or not start:
            continue
        timeline.append(
            {
                "type": "finish" if kind == "fin" else kind,
                "timestamp": start,
                "duration_seconds": end - start if end and end >= start else None,
                **_report_event_details(item, kind),
            }
        )
    if timeline and all(event["type"] != "finish" for event in timeline):
        timeline.append({"type": "finish", "timestamp": row["timestamp"], "duration_seconds": None})
    return tuple(sorted(timeline, key=lambda event: event["timestamp"]))


def mission_reports(response: object, robot_id: str) -> tuple[MissionReport, ...]:
    """Authorize each report against its source robot without returning native identifiers."""
    reports = {}
    for row in sorted(
        _history_rows(response, robot_id), key=lambda row: row["timestamp"], reverse=True
    ):
        if at(row, "cmd.command") not in HISTORY_COMMANDS:
            continue
        identity = row.get("missionId")
        if not map_identifier(identity):
            identity = integer(row.get("nMssn"))
        key = sha256(f"{robot_id}:{identity}:{row['timestamp']}".encode()).hexdigest()
        command = row.get("cmd")
        metrics = _mission_metrics(row)
        plan = mission_plan(command)
        elapsed = (
            mission_timing(at(row, "timeline.finEvents"), command).elapsed(
                plan, metrics.get("last_mission_started"), metrics["last_mission_finished"]
            )
            if plan is not None
            else ()
        )
        reports[key] = MissionReport(
            key,
            _report_maps(row),
            metrics,
            _report_timeline(row),
            plan,
            elapsed,
        )
    return tuple(reports.values())
