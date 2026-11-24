"""Read the observed Roomba live position format without retaining raw messages."""

from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import batched
from math import pi

from .history import RoomResult, room_results
from .telemetry import integer

MAX_PATH_POINTS = 2048
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
class PositionBatch:
    index: int
    timestamp: int
    expires: int
    positions: tuple[Position, ...]


@dataclass(frozen=True, repr=False)
class MissionTimeline:
    mission_number: int
    observed_at: datetime
    stage: str | None
    rooms: tuple[RoomResult, ...]
    active_rooms: tuple[RoomResult, ...] = ()


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
    return MissionTimeline(
        mission_number,
        datetime.fromtimestamp(now, UTC),
        current[2],
        room_results(document.get("finEvents")),
        room_results(events),
    )


@dataclass(frozen=True, repr=False)
class MissionPath:
    map_version: tuple[str, str]
    started: datetime
    latest: PositionBatch
    points: tuple[tuple[int, Position], ...]

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
        or timestamp > now + 5
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
