"""Use Roomba's reported cleaning intervals and room duration estimates."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from .maps import AreaTarget, PersistentMap, RegionKind
from .mission_areas import AreaResult
from .mission_plan import MissionPlan, destination_key
from .telemetry import integer

PENDING = {"pending", "traveling"}
RESOLVED = {"finished", "skipped"}
COUNTDOWN_STAGES = {"start", "reloc", "travel", "room", "pause"}
ACTIVE_AREA_STAGES = {"room", "zone"}
INTERRUPTIONS = ("pause", "charge", "padWash")

type Interval = tuple[int, int]


@dataclass(frozen=True, repr=False)
class RoomPause:
    area: AreaResult
    paused_at: int
    resumed_at: int | None = None


@dataclass(frozen=True, repr=False)
class RoomTiming:
    """Keep observed room intervals if a later timeline omits them."""

    pauses: tuple[RoomPause, ...] = ()

    @property
    def areas(self) -> tuple[AreaResult, ...]:
        return tuple(item.area for item in self.pauses)

    def observe(self, plan: MissionPlan, area: AreaResult, stage: str, stamp: int) -> RoomTiming:
        target = destination_key(plan, area)
        if not any((item.kind, item.identity) == target for item in plan.destinations):
            return self
        if self.pauses and stamp <= self.pauses[-1].paused_at:
            return self
        previous = self._last_pause(plan, area)
        if stage == "room":
            if (
                previous is None
                or previous is not self.pauses[-1]
                or previous.resumed_at is not None
            ):
                return self
            return RoomTiming((*self.pauses[:-1], replace(previous, resumed_at=stamp)))
        if previous is not None and area.timestamp <= previous.paused_at:
            if previous.resumed_at is None or stamp < previous.resumed_at:
                return self
            area = replace(area, timestamp=previous.resumed_at)
        return RoomTiming((*self.pauses, RoomPause(replace(area, ended_at=stamp), stamp)))

    def resumed_area(self, plan: MissionPlan, area: AreaResult, stamp: int) -> AreaResult | None:
        previous = self._last_pause(plan, area)
        if previous is None or previous.resumed_at != stamp:
            return None
        return replace(area, timestamp=stamp)

    def interruptions(
        self, plan: MissionPlan, target: tuple[str, tuple[str, str, str]], through: int
    ) -> Iterable[Interval]:
        return (
            (item.paused_at, item.resumed_at)
            for item in self.pauses
            if item.resumed_at is not None
            and item.resumed_at <= through
            and destination_key(plan, item.area) == target
        )

    def _last_pause(self, plan: MissionPlan, area: AreaResult) -> RoomPause | None:
        key = destination_key(plan, area)
        return next(
            (item for item in reversed(self.pauses) if destination_key(plan, item.area) == key),
            None,
        )


@dataclass(frozen=True, repr=False)
class MissionTiming:
    areas: tuple[AreaResult, ...] = ()
    interruptions: tuple[Interval, ...] = ()

    def elapsed(
        self,
        plan: MissionPlan,
        started: datetime | None,
        now: datetime,
        active: tuple[AreaResult, int] | None = None,
        *,
        observed_rooms: RoomTiming = RoomTiming(),
    ) -> tuple[int | None, ...]:
        if started is None:
            return ()
        beginning, through = int(started.timestamp()), int(now.timestamp())
        areas = (*self.areas, *observed_rooms.areas)
        if active is not None:
            area, until = active
            areas = (*areas, replace(area, ended_at=until))
        by_destination = {}
        for area in areas:
            if (
                area.ended_at is not None
                and beginning <= area.timestamp <= area.ended_at <= through
            ):
                by_destination.setdefault(destination_key(plan, area), []).append(area)
        interruptions = tuple(
            (start, end)
            for start, end in self.interruptions
            if beginning <= start <= end <= through
        )
        return tuple(
            _area_elapsed(
                item.kind,
                by_destination.get((item.kind, item.identity), ()),
                _merge_intervals(
                    (
                        *interruptions,
                        *observed_rooms.interruptions(plan, (item.kind, item.identity), through),
                    )
                ),
            )
            for item in plan.destinations
        )


def reported_interruptions(
    events: list, *, stages: tuple[str, ...] = INTERRUPTIONS
) -> tuple[Interval, ...]:
    result = []
    for event in events:
        if isinstance(event, dict) and event.get("type") in stages:
            start = integer(event.get("ts"), 32_503_680_000)
            end = integer(event.get("ets"), 32_503_680_000)
            if start is not None and end is not None:
                result.append((start, end))
    return tuple(result)


def _merge_intervals(intervals: Iterable[Interval]) -> tuple[Interval, ...]:
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            begin, previous_end = merged[-1]
            merged[-1] = (begin, max(previous_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _area_elapsed(
    kind: str, areas: Sequence[AreaResult], interruptions: tuple[Interval, ...]
) -> int | None:
    if not areas:
        return None
    if kind == "saved_zone":
        # A late observer needs the reported first pass to total a later one.
        passes = {item.pass_count for item in areas if item.pass_count is not None}
        if passes and 0 not in passes:
            return None
    return sum(
        end
        - start
        - sum(
            max(0, min(end, paused_end) - max(start, paused_start))
            for paused_start, paused_end in interruptions
        )
        for start, end in _merge_intervals((item.timestamp, item.ended_at) for item in areas)
    )


def with_destination_elapsed(plan: dict, elapsed: tuple[int | None, ...]) -> dict:
    if all(seconds is None for seconds in elapsed):
        return plan
    return {
        **plan,
        "destinations": [
            row | {"cleaning_elapsed_seconds": seconds} if seconds is not None else row
            for row, seconds in zip(plan["destinations"], elapsed, strict=True)
        ],
    }


def estimate_target(plan: MissionPlan, floor: PersistentMap) -> AreaTarget | None:
    rooms = {region.region_id: region for region in floor.regions if region.kind is RegionKind.ROOM}
    candidates = [
        (rooms[destination.identity[2]], destination.profile)
        for destination in plan.destinations
        if destination.kind == "room"
        and destination.identity[2] in rooms
        and destination.profile is not None
    ]
    if not candidates:
        return None
    return AreaTarget(
        *plan.scope,
        tuple(room for room, _ in candidates),
        tuple(profile for _, profile in candidates),
    )


def estimate_durations(plan: MissionPlan, reading: dict) -> tuple[int | None, ...]:
    estimates = {area["id"]: area["duration_seconds"] for area in reading["areas"]}
    return tuple(
        estimates.get(f"{plan.scope[0]}:{RegionKind.ROOM}:{destination.identity[2]}")
        if destination.kind == "room"
        else None
        for destination in plan.destinations
    )


def remaining_plan_duration(
    plan: dict, stage: str | None, stage_started: datetime | None, now: datetime
) -> int | None:
    """Apply the same countdown to a freshly projected or cached plan."""
    destinations = plan["destinations"]
    active_status = "paused" if stage == "pause" else "in_progress"
    return remaining_duration(
        tuple(item["status"] for item in destinations),
        tuple(item.get("estimated_duration_seconds") for item in destinations),
        stage,
        stage_started,
        now,
        elapsed_seconds=next(
            (
                item.get("cleaning_elapsed_seconds")
                for item in destinations
                if item["status"] == active_status
            ),
            None,
        ),
    )


def with_live_area_elapsed(
    plan: dict, stage: str | None, stage_started: datetime | None, now: datetime
) -> dict:
    """Annotate the single current destination with time in its reported stage."""
    if stage not in ACTIVE_AREA_STAGES or stage_started is None or stage_started > now:
        return plan
    destinations = list(plan["destinations"])
    active = [index for index, row in enumerate(destinations) if row["status"] == "in_progress"]
    if len(active) != 1:
        return plan
    index = active[0]
    elapsed = int((now - stage_started).total_seconds())
    destinations[index] = {**destinations[index], "stage_elapsed_seconds": elapsed}
    return {**plan, "destinations": destinations}


def remaining_duration(
    destination_statuses: tuple[str, ...],
    durations: tuple[int | None, ...],
    stage: str | None,
    stage_started: datetime | None,
    now: datetime,
    *,
    elapsed_seconds: int | None = None,
) -> int | None:
    """Calculate an approximate time for remaining, explicitly timed work."""
    if stage not in COUNTDOWN_STAGES:
        return None
    active_status = "paused" if stage == "pause" else "in_progress"
    elapsed = 0
    if stage in {"room", "pause"}:
        if (
            destination_statuses.count(active_status) != 1
            or stage_started is None
            or stage_started > now
        ):
            return None
        if elapsed_seconds is not None:
            elapsed = elapsed_seconds
        elif stage == "room":
            elapsed = int((now - stage_started).total_seconds())
        else:
            return None
    total = 0
    for status, duration in zip(destination_statuses, durations, strict=True):
        if status in RESOLVED:
            continue
        if duration is None or status not in PENDING | {active_status}:
            return None
        if status == active_status:
            duration -= elapsed
            if duration <= 0:
                return None
        total += duration
    return total or None
