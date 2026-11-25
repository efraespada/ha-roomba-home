"""Read the observed Roomba live position format without retaining raw messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import batched
from math import pi

from .application import SkipAreaEvent, SkipObservation
from .cleaning import CleaningMode
from .cleaning_protocol import reported_cleaning_mode
from .history import AreaResult, identify_zones, room_results, zone_results
from .maps import PersistentMap, map_identifier
from .mission_plan import MissionPlan, mission_plan
from .point_maps import PointTarget
from .telemetry import integer

MAX_PATH_POINTS = 2048
LIVE_CLOCK_SKEW_SECONDS = 5
POSITION_ACTIVITIES = {0: "traveling", 5: "vacuuming", 4: "mopping", 6: "vacuum_mop"}
TIMELINE_STAGES = frozenset(
    {
        "charge",
        "disc",
        "error",
        "fin",
        "padWash",
        "pause",
        "reloc",
        "room",
        "start",
        "travel",
        "zone",
    }
)


@dataclass(frozen=True, repr=False)
class Position:
    x: float
    y: float
    orientation: float
    modes: int


@dataclass(frozen=True, repr=False)
class RoutePoint:
    x: float
    y: float
    modes: int


@dataclass(frozen=True, repr=False)
class PositionBatch:
    index: int
    timestamp: int
    expires: int
    positions: tuple[Position, ...]

    def belongs_to(self, started: datetime, now: datetime) -> bool:
        observed = now.timestamp()
        return (
            started.timestamp() <= self.timestamp <= observed + LIVE_CLOCK_SKEW_SECONDS
            and observed < self.expires
        )


@dataclass(frozen=True, repr=False)
class MissionPoint:
    target: PointTarget
    mode: CleaningMode


@dataclass(frozen=True, repr=False)
class MissionTimeline:
    mission_number: int
    observed_at: datetime
    stage: str | None
    rooms: tuple[AreaResult, ...]
    active_rooms: tuple[AreaResult, ...] = ()
    zones: tuple[AreaResult, ...] = ()
    active_zones: tuple[AreaResult, ...] = ()
    travelling_to: AreaResult | None = None
    directed: bool = False
    point: MissionPoint | None = None
    stage_started_at: datetime | None = None
    plan: MissionPlan | None = None
    requested_floor: tuple[str, str] | None = None
    localized_maps: frozenset[str] = frozenset()

    def skip_observation(self) -> SkipObservation:
        active = {
            "room": self.active_rooms,
            "zone": self.active_zones,
        }.get(self.stage, ())
        target = (
            self.travelling_to
            if self.stage == "travel"
            else active[0]
            if len(active) == 1
            else None
        )
        skipped = frozenset(
            SkipAreaEvent(area.kind, area.identity, area.timestamp)
            for area in (*self.rooms, *self.zones)
            if area.status in {3, 7}
        )
        destination = (
            SkipAreaEvent(target.kind, target.identity, target.timestamp) if target else None
        )
        return SkipObservation(destination, skipped, self.directed)


def _travel_destination(event, stamp, command):
    travel = event.get("travel")
    if not isinstance(travel, dict) or travel.get("dest") not in ("room", "zone"):
        return None
    kind = travel["dest"]
    identifier = travel.get("rid" if kind == "room" else "zid")
    identity = travel.get("p2mapId"), travel.get("p2mapvId"), identifier
    if not all(map_identifier(value) for value in identity):
        return None
    area = AreaResult(identity, stamp, None, None, None, None, kind)
    return identify_zones((area,), command)[0] if kind == "zone" else area


def _point_destination(command: object) -> MissionPoint | None:
    if (
        not isinstance(command, dict)
        or command.get("command") != "point_clean"
        or not isinstance(geometry := command.get("geom"), dict)
        or not isinstance(center := geometry.get("center"), list)
        or len(center) != 2
        or not isinstance(params := command.get("params"), dict)
        or (mode := reported_cleaning_mode(params.get("operatingMode"))) is None
    ):
        return None
    try:
        target = PointTarget(command.get("p2map_id"), command.get("user_p2mapv_id"), tuple(center))
    except ValueError:
        return None
    return MissionPoint(target, mode)


def _requested_floor(command) -> tuple[str, str] | None:
    if isinstance(command, dict) and command.get("command") in ("start", "point_clean"):
        scope = command.get("p2map_id"), command.get("user_p2mapv_id")
        if all(map_identifier(value) for value in scope):
            return scope
    return None


def _localized_maps(events) -> frozenset[str]:
    if not isinstance(events, list):
        return frozenset()
    matched = set()
    for event in events:
        if (
            isinstance(event, dict)
            and event.get("type") == "reloc"
            and isinstance(relocation := event.get("reloc"), dict)
            and map_identifier(map_id := relocation.get("confp2mapId"))
            and map_identifier(relocation.get("confp2mapvId"))
            and relocation.get("p2mapId") == map_id
        ):
            matched.add(map_id)
    return frozenset(matched)


def resolve_live_floor(
    maps: tuple[PersistentMap, ...],
    timeline: MissionTimeline | None,
    pinned: tuple[str, str] | None,
) -> PersistentMap | None:
    """Resolve the mission's floor and keep its verified saved revision."""
    requested = timeline.requested_floor if timeline else None
    identified = set(timeline.localized_maps) if timeline else set()
    if requested:
        identified.add(requested[0])
    if pinned:
        identified.add(pinned[0])
    if len(identified) > 1:
        return None
    choices = [floor for floor in maps if not identified or floor.map_id in identified]
    if pinned:
        choices = [floor for floor in choices if (floor.map_id, floor.version_id) == pinned]
    if requested and len(maps) > 1:
        choices = [floor for floor in choices if (floor.map_id, floor.version_id) == requested]
    return choices[0] if len(choices) == 1 else None


def mission_timeline(document, request_id, mission_number, now) -> MissionTimeline | None:
    if (
        not isinstance(document, dict)
        or integer(document.get("timelineRequestId")) != request_id
        or integer(document.get("nMssn")) != mission_number
        or not isinstance(events := document.get("event"), list)
    ):
        return None
    current = max(
        (
            (stamp, index, kind)
            for index, item in enumerate(events)
            if isinstance(item, dict)
            and isinstance(kind := item.get("type"), str)
            and kind in TIMELINE_STAGES
            and (stamp := integer(item.get("ts"), 32_503_680_000)) is not None
        ),
        default=(0, 0, None),
    )
    command = document.get("cmd")
    finished = document.get("finEvents")
    return MissionTimeline(
        mission_number,
        datetime.fromtimestamp(now, UTC),
        current[2],
        room_results(finished),
        room_results(events),
        zone_results(finished, command),
        zone_results(events, command),
        _travel_destination(events[current[1]], current[0], command)
        if current[2] == "travel"
        else None,
        isinstance(command, dict)
        and isinstance(command.get("regions"), list)
        and bool(command["regions"]),
        _point_destination(command),
        datetime.fromtimestamp(current[0], UTC) if 0 < current[0] <= now else None,
        mission_plan(command),
        _requested_floor(command),
        _localized_maps(events) | _localized_maps(finished),
    )


@dataclass(frozen=True, repr=False)
class MissionPath:
    map_version: tuple[str, str]
    started: datetime
    latest: PositionBatch
    points: tuple[tuple[int, Position | RoutePoint], ...]

    def needs_backfill(self) -> bool:
        if not self.points:
            return False
        last = self.points[-1][0]
        first = max(min(1, self.points[0][0]), last - MAX_PATH_POINTS + 1)
        return len(self.points) < last - first + 1

    def append(self, batch: PositionBatch):
        points = dict(self.points)
        points.update(enumerate(batch.positions, start=batch.index))
        most_recent = max((self.latest, batch), key=lambda item: (item.timestamp, item.index))
        return MissionPath(
            self.map_version,
            self.started,
            most_recent,
            tuple(sorted(points.items())[-MAX_PATH_POINTS:]),
        )

    def merge(self, live: MissionPath) -> MissionPath:
        points = dict(self.points)
        points.update(live.points)
        latest = max((self.latest, live.latest), key=lambda item: (item.timestamp, item.index))
        return MissionPath(
            self.map_version,
            self.started,
            latest,
            tuple(sorted(points.items())[-MAX_PATH_POINTS:]),
        )


def position_batch(document, now: int) -> PositionBatch | None:
    """Accept complete, current batches of planar positions and operating modes."""
    if not isinstance(document, dict) or not isinstance(update := document.get("pos_update"), dict):
        return None
    path = update.get("cur_path")
    timestamp = integer(document.get("timestamp"), 32_503_680_000)
    expires = integer(document.get("update_expire_ts"), 32_503_680_000)
    if (
        not timestamp
        or not expires
        or not timestamp <= expires
        or not now < expires
        or timestamp > now + LIVE_CLOCK_SKEW_SECONDS
        or not isinstance(path, list)
        or not 6 <= len(path) <= 4 * MAX_PATH_POINTS + 2
        or (len(path) - 2) % 4
        or integer(path[0]) is None
        or integer(path[-1]) != timestamp
    ):
        return None
    positions = []
    for x, y, orientation, modes in batched(path[1:-1], 4, strict=True):
        if (
            not all(type(value) in (int, float) and -1e9 <= value <= 1e9 for value in (x, y))
            or type(orientation) not in (int, float)
            or not -4 * pi <= orientation <= 4 * pi
            or integer(modes) is None
        ):
            return None
        positions.append(Position(x, y, orientation, modes))
    return PositionBatch(path[0], timestamp, expires, tuple(positions))
