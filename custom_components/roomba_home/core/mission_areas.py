"""Area identities and outcomes shared by live and archived missions."""

from dataclasses import dataclass

REGION_TARGETS = {"rid": "rooms", "zid": "saved_zones", "tid": "temporary_zones"}
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


@dataclass(frozen=True, repr=False)
class AreaResult:
    identity: tuple[str, str, str]
    timestamp: int
    status: int | None
    area: int | None
    total_area: int | None
    pass_count: int | None
    kind: str = "room"
    confirmed_completed_passes: int | None = None
    ended_at: int | None = None
    completed_passes_sqft: int | None = None


def command_region_kind(region: dict) -> str | None:
    kind = region.get("type", region.get("region_type"))
    if isinstance(kind, str) and kind in REGION_TARGETS and region.get("region_type", kind) == kind:
        return kind
    return None
