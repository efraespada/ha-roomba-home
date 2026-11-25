"""Use Roomba's room duration estimates and current mission stage."""

from datetime import datetime

from .maps import AreaTarget, PersistentMap, RegionKind
from .mission_plan import MissionPlan

PENDING = {"pending", "traveling"}
RESOLVED = {"finished", "skipped"}
COUNTDOWN_STAGES = {"start", "reloc", "travel", "room"}


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


def remaining_duration(
    destination_statuses: tuple[str, ...],
    durations: tuple[int | None, ...],
    stage: str | None,
    stage_started: datetime | None,
    now: datetime,
) -> int | None:
    """Calculate an approximate time for remaining, explicitly timed work."""
    if stage not in COUNTDOWN_STAGES:
        return None
    active = destination_statuses.count("in_progress")
    if stage == "room":
        if active != 1 or stage_started is None or stage_started > now:
            return None
        elapsed = int((now - stage_started).total_seconds())
    else:
        elapsed = 0
    total = 0
    for status, duration in zip(destination_statuses, durations, strict=True):
        if status in RESOLVED:
            continue
        if duration is None or status not in PENDING | {"in_progress"}:
            return None
        if status == "in_progress":
            duration -= elapsed
            if duration <= 0:
                return None
        total += duration
    return total or None
