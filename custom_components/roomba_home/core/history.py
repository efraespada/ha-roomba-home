"""Typed history summaries. Private mission, map and event data stay in the API response."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .errors import ProtocolError
from .maps import PersistentMap, RegionKind, map_identifier
from .state import RobotState
from .telemetry import CLEANING_CYCLES, at, convert, integer

OUTCOMES = {"ok": "completed", "cncl": "cancelled", "inc": "incomplete", "stuck": "stuck"}
MODES = {"vac": "vacuum", "mop": "mop", "vacmop": "vacuum_mop"}
ROOM_STATUSES = {
    0: "finished",
    1: "finished_with_more_passes",
    2: "partial_incomplete",
    3: "partial_skipped",
    4: "kidnapped",
    5: "user_ended",
    6: "robot_aborted",
    7: "skipped",
    8: "skipped_will_return",
}
HISTORY_COMMANDS = ("start", "spot", "point_clean")
REGION_TARGETS = {"rid": "rooms", "zid": "saved_zones", "tid": "temporary_zones"}
HISTORY_TARGETS = (
    "whole_map",
    *REGION_TARGETS.values(),
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


@dataclass(frozen=True, repr=False)
class RoomResult:
    identity: tuple[str, str, str]
    timestamp: int
    status: int | None
    area: int | None
    total_area: int | None
    pass_count: int | None


def room_results(events: object) -> tuple[RoomResult, ...]:
    """Keep the newest reported result for each room and exact map revision."""
    if not isinstance(events, list):
        return ()
    rooms = {}
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "room":
            continue
        data = event.get("room")
        if not isinstance(data, dict):
            continue
        key = tuple(data.get(field) for field in ("p2mapId", "p2mapvId", "rid"))
        timestamp = integer(event.get("ts"), 32_503_680_000)
        if timestamp is None or not all(map_identifier(value) for value in key):
            continue
        status, area, total, passes = (
            integer(data.get(field)) for field in ("status", "area", "totalArea", "passCount")
        )
        if all(value is None for value in (status, area, total, passes)):
            continue
        earlier = rooms.get(key)
        if earlier is None or timestamp >= earlier.timestamp:
            rooms[key] = RoomResult(key, timestamp, status, area, total, passes)
    return tuple(sorted(rooms.values(), key=lambda room: room.timestamp))


def present_rooms(results: tuple[RoomResult, ...], maps: tuple[PersistentMap, ...]) -> list[dict]:
    names = {
        (floor.map_id, floor.version_id, region.region_id): region.name
        for floor in maps
        for region in floor.regions
        if region.kind is RegionKind.ROOM
    }
    return [
        {
            "room": names.get(room.identity),
            "status": ROOM_STATUSES.get(room.status),
            "status_code": room.status,
            "area": room.area,
            "total_area": room.total_area,
            "pass_count": room.pass_count,
        }
        for room in results
    ]


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
            regions = command.get("regions", [])
        case _:
            return None, None
    if not isinstance(regions, list):
        return None, None
    if not regions:
        if any(command.get(key) for key in ("favorite_id", "geom", "id_multipolys")):
            return None, None
        return "whole_map", None
    targets = set()
    for region in regions:
        if not isinstance(region, dict):
            return None, None
        kind = region.get("type", region.get("region_type"))
        if (
            not isinstance(kind, str)
            or kind not in REGION_TARGETS
            or region.get("region_type", kind) != kind
        ):
            return None, None
        targets.add(REGION_TARGETS[kind])
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


def history_metrics(response: object, robot_id: str) -> dict:
    if not isinstance(response, list):
        raise ProtocolError("Expected the Roomba Home mission list")
    valid = [
        row
        for row in response
        if isinstance(row, dict)
        and row.get("robot_id") == robot_id
        and integer(row.get("timestamp"), 32_503_680_000)
    ]
    if not valid:
        return {"history_count": 0}
    row = max(valid, key=lambda row: row["timestamp"])
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
        "history_count": len(valid),
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
    if rooms := room_results(at(row, "timeline.finEvents")):
        result["last_mission_room_results"] = rooms
    if isinstance(command := row.get("cmd"), dict):
        if command.get("command") in HISTORY_COMMANDS:
            result["last_mission_command"] = command["command"]
        target, count = _mission_target(command)
        if target is not None:
            result["last_mission_target"] = target
        if count is not None:
            result["last_mission_target_count"] = count
    return result
