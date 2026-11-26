"""Validate timing without assuming estimates for unknown work."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind
from custom_components.roomba_home.core.mission_plan import mission_plan
from custom_components.roomba_home.core.mission_time import (
    estimate_durations,
    estimate_target,
    remaining_duration,
    with_live_area_elapsed,
)

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)
FLOOR = PersistentMap(
    "map",
    "v1",
    None,
    (
        CleaningRegion("room-a", RegionKind.ROOM, "Kitchen"),
        CleaningRegion("room-b", RegionKind.ROOM, "Office"),
        CleaningRegion("zone-a", RegionKind.ZONE, "Table"),
    ),
)
COMMAND = {"command": "start", "p2map_id": "map", "user_p2mapv_id": "v1"}


def test_match_each_room_profile_and_keep_unestimated_destinations_in_order():
    regions = [
        {"type": "rid", "region_id": "room-a", "params": {"suctionLevel": 3}},
        {"type": "zid", "region_id": "zone-a"},
        {"type": "rid", "region_id": "room-b", "params": {"operatingMode": 4}},
        {"type": "rid", "region_id": "unknown"},
        {"type": "rid", "region_id": "unknown-mode", "params": {"operatingMode": 99}},
    ]
    plan = mission_plan(COMMAND | {"regions": regions, "params": {"operatingMode": 2}})
    target = estimate_target(plan, FLOOR)
    assert target.regions == FLOOR.regions[:2]
    assert [profile.mode for profile in target.profiles] == ["vacuum", "mop"]
    assert target.profiles[0].suction_level == 3
    assert estimate_durations(
        plan,
        {
            "areas": [
                {"id": "map:rid:room-b", "duration_seconds": 250},
                {"id": "map:rid:room-a", "duration_seconds": 500},
            ]
        },
    ) == (500, None, 250, None, None)
    invalid = mission_plan(
        COMMAND
        | {
            "regions": [{"type": "rid", "region_id": "room-a", "params": {"operatingMode": 2}}],
            "params": "invalid",
        }
    )
    assert invalid.destinations[0].mode == "vacuum"
    assert estimate_target(invalid, FLOOR) is None


@pytest.mark.parametrize(
    ("statuses", "durations", "stage", "offset", "expected"),
    [
        (("traveling", "pending"), (500, 250), "travel", None, 750),
        (("in_progress", "pending"), (500, 250), "room", 31, 719),
        (("finished", "in_progress"), (500, 250), "room", 25, 225),
        (("skipped", "pending"), (None, 250), "reloc", None, 250),
        (("pending",), (0,), "start", None, None),
        (("finished",), (500,), "travel", None, None),
        (("in_progress", "pending"), (500, None), "room", 30, None),
        (("in_progress",), (500,), "room", 501, None),
        (("in_progress",), (500,), "room", None, None),
        (("in_progress",), (500,), "room", -3, None),
        (("pending",), (500,), "room", 30, None),
        (("in_progress", "in_progress"), (500, 250), "room", 30, None),
        (("skipped_will_return",), (500,), "travel", None, None),
        (("in_progress",), (500,), "pause", 40, None),
    ],
)
def test_countdown_waits_for_timed_work_and_a_verified_stage(
    statuses, durations, stage, offset, expected
):
    stage_started = NOW - timedelta(seconds=offset) if offset is not None else None
    assert remaining_duration(statuses, durations, stage, stage_started, NOW) == expected


@pytest.mark.parametrize(
    ("stage", "offset", "statuses", "elapsed"),
    [
        ("room", 0, ("in_progress", "pending"), 0),
        ("zone", 86, ("finished", "in_progress"), 86),
        ("pause", 86, ("in_progress",), None),
        ("zone", None, ("in_progress",), None),
        ("zone", -1, ("in_progress",), None),
        ("zone", 86, ("finished",), None),
        ("zone", 86, ("in_progress", "in_progress"), None),
    ],
)
def test_elapsed_stage_requires_one_current_destination(stage, offset, statuses, elapsed):
    plan = {"destinations": [{"status": status} for status in statuses]}
    started = NOW - timedelta(seconds=offset) if offset is not None else None
    reading = with_live_area_elapsed(plan, stage, started, NOW)
    assert all("stage_elapsed_seconds" not in row for row in plan["destinations"])
    if elapsed is None:
        assert reading is plan
    else:
        assert [
            row["stage_elapsed_seconds"]
            for row in reading["destinations"]
            if "stage_elapsed_seconds" in row
        ] == [elapsed]
        assert (
            reading["destinations"][statuses.index("in_progress")]["stage_elapsed_seconds"]
            == elapsed
        )
