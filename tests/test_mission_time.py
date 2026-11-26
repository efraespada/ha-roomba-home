"""Validate timing without assuming estimates for unknown work."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind
from custom_components.roomba_home.core.mission_areas import AreaResult
from custom_components.roomba_home.core.mission_plan import mission_plan
from custom_components.roomba_home.core.mission_time import (
    MissionTiming,
    estimate_durations,
    estimate_target,
    remaining_duration,
    remaining_plan_duration,
    reported_interruptions,
    with_destination_elapsed,
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


def test_elapsed_restores_each_destination_from_valid_reported_intervals():
    started = NOW - timedelta(seconds=500)

    def stamp(second):
        return int(started.timestamp()) + second

    def area(begin, end, *, kind="room", scope="map", identity="room-a", passes=None):
        return AreaResult(
            (scope, "robot-revision" if kind == "room" else "v1", identity),
            stamp(begin),
            None,
            None,
            None,
            passes,
            kind,
            ended_at=stamp(end) if end is not None else None,
        )

    plan = mission_plan(
        COMMAND
        | {
            "regions": [
                {"type": "rid", "region_id": "room-a"},
                {"type": "zid", "region_id": "zone-a"},
                {"type": "rid", "region_id": "room-b"},
            ]
        }
    )
    first_pass = area(252, 300, kind="saved_zone", identity="zone-a", passes=0)
    next_pass = area(301, None, kind="saved_zone", identity="zone-a", passes=1)
    timing = MissionTiming(
        (
            area(110, 160),
            area(150, 200),
            area(220, 250),
            first_pass,
            area(150, 499, scope="other-floor"),
            area(-1, 499),
            area(400, 501),
            area(390, 250),
            area(400, None),
        ),
        (
            (stamp(158), stamp(170)),
            (stamp(168), stamp(175)),
            (stamp(330), stamp(370)),
            (stamp(-1), stamp(200)),
            (stamp(400), stamp(501)),
            (stamp(420), stamp(390)),
        ),
    )
    assert timing.elapsed(plan, started, NOW, (next_pass, stamp(380))) == (103, 87, None)
    assert MissionTiming().elapsed(plan, started, NOW, (next_pass, stamp(380))) == (
        None,
        None,
        None,
    )
    assert MissionTiming().elapsed(plan, started, NOW, (area(110, None), stamp(110))) == (
        0,
        None,
        None,
    )
    assert timing.elapsed(plan, None, NOW) == ()

    view = {
        "destinations": [
            {"status": "in_progress", "estimated_duration_seconds": 500},
            {"status": "pending", "estimated_duration_seconds": 20},
        ]
    }
    current = with_destination_elapsed(view, (103, None))
    assert current["destinations"][1] is view["destinations"][1]
    assert "cleaning_elapsed_seconds" not in view["destinations"][0]
    assert with_destination_elapsed(view, (None, None)) is view
    assert remaining_plan_duration(current, "room", started, NOW) == 417


def test_reported_interruptions_use_only_completed_known_downtime():
    assert reported_interruptions(
        [
            None,
            {"type": "disc", "ts": 100, "ets": 150},
            {"type": "charge", "ts": 100},
            {"type": "pause", "ts": [], "ets": 110},
            {"type": "pause", "ts": 100, "ets": 150},
            {"type": "padWash", "ts": 200, "ets": 250},
        ]
    ) == ((100, 150), (200, 250))
