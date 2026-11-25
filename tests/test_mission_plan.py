"""Check provider-declared destinations and their individual live outcomes."""

from dataclasses import replace

import pytest

from custom_components.roomba_home.core.history import AreaResult
from custom_components.roomba_home.core.live_maps import mission_timeline
from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind
from custom_components.roomba_home.core.mission_plan import mission_plan, present_mission_plan

SCOPE = ("map-a", "version.2")
ROOM = {"type": "rid", "region_id": "room-a"}
ZONE = {"region_type": "zid", "region_id": "101", "params": {"operatingMode": 32}}
FURNITURE = {"type": "tid", "region_id": "polygon-a", "params": {"operatingMode": 512}}
TEMPORARY = {"type": "tid", "region_id": "polygon-b"}
COMMAND = {
    "command": "start",
    "p2map_id": SCOPE[0],
    "user_p2mapv_id": SCOPE[1],
    "regions": [ROOM, ZONE, FURNITURE, TEMPORARY],
    "ordered": 1,
    "id_multipolys": [
        {
            "id": "polygon-a",
            "metadata": {"furniture_id": "sofa-a"},
            "poly": [[0, 0], [1, 0], [1, 1], [0, 1]],
        }
    ],
}
FLOOR = PersistentMap(
    *SCOPE,
    "Example floor",
    (
        CleaningRegion("room-a", RegionKind.ROOM, "Cocina"),
        CleaningRegion("101", RegionKind.ZONE, "Kitchen table"),
        CleaningRegion("sofa-a", RegionKind.FURNITURE, "Sofá"),
    ),
)
NOW = 1_800_000_010


@pytest.mark.parametrize(
    "changes",
    [
        {"command": "spot"},
        {"select_all": True},
        {"regions": {}},
        {"regions": []},
        {"regions": [ROOM] * 33},
        {"regions": [ROOM, ROOM]},
        {"regions": [ROOM, None]},
        {"regions": [ROOM, ZONE | {"type": "rid"}]},
        {"regions": [ROOM, {"type": "rid", "region_id": ".."}]},
        {"user_p2mapv_id": "invalid map revision"},
    ],
)
def test_incomplete_or_ambiguous_destination_lists_are_omitted(changes):
    assert mission_plan(COMMAND | changes) is None


@pytest.mark.parametrize(
    ("ordered", "regions", "expected"),
    [
        (None, [ROOM], True),
        (None, [ROOM, ZONE], False),
        (True, [ROOM, ZONE], False),
        (0, [ROOM, ZONE], False),
        (1, [ZONE, ROOM], True),
    ],
)
def test_order_only_claimed_when_requested_or_single_destination(ordered, regions, expected):
    plan = mission_plan(COMMAND | {"regions": regions, "ordered": ordered})
    assert plan.ordered is expected
    assert [item.identity[2] for item in plan.destinations] == [row["region_id"] for row in regions]


def test_plan_uses_the_matched_timeline_and_exact_revision():
    def zone(identifier, status):
        return {
            "type": "zone",
            "ts": NOW - 1,
            "zone": {
                "p2mapId": SCOPE[0],
                "p2mapvId": "device-revision",
                "zid": identifier,
                "status": status,
                "area": 2,
            },
        }

    document = {
        "nMssn": 10,
        "timelineRequestId": 99,
        "cmd": COMMAND,
        "event": [zone("polygon-a", None)],
        "finEvents": [zone("101", 0), zone("polygon-a", 0)],
    }
    assert mission_timeline(document, 98, 10, NOW) is None
    assert mission_timeline(document, 99, 11, NOW) is None
    timeline = mission_timeline(document, 99, 10, NOW)
    result = present_mission_plan(
        timeline.plan,
        timeline.zones,
        timeline.active_zones,
        None,
        (replace(FLOOR, version_id="other-version"), FLOOR),
    )
    assert result == {
        "ordered": True,
        "completed": 1,
        "total": 4,
        "destinations": [
            {"kind": "room", "name": "Cocina", "status": "pending"},
            {
                "kind": "saved_zone",
                "name": "Kitchen table",
                "status": "finished",
                "mode": "vacuum_mop",
            },
            {
                "kind": "furniture",
                "name": "Sofá",
                "status": "in_progress",
                "mode": "vacuum_then_mop",
            },
            {"kind": "temporary_zone", "name": None, "status": "pending"},
        ],
    }
    assert "map-a" not in str(result) and "sofa-a" not in str(result)


def test_travel_skips_partial_and_unknown_outcomes_do_not_count_as_completion():
    def result(identity, status, kind, scope=SCOPE):
        return AreaResult((*scope, identity), NOW, status, None, None, None, kind)

    finished_on_other_revision = result("room-a", 0, "room", (SCOPE[0], "old-version"))
    final = (
        finished_on_other_revision,
        result("101", 8, "saved_zone"),
        result("sofa-a", 249, "furniture"),
        result("polygon-b", 1, "temporary_zone"),
    )
    plan = mission_plan(COMMAND)
    output = present_mission_plan(plan, final, (), result("room-a", None, "room"), ())
    assert output["completed"] == 0
    assert [target["status"] for target in output["destinations"]] == [
        "traveling",
        "skipped_will_return",
        "unknown",
        "finished_with_more_passes",
    ]


def test_correlated_room_uses_the_command_revision_only_on_the_same_map():
    target = mission_plan(COMMAND | {"regions": [ROOM]})
    robot_revision = AreaResult((SCOPE[0], "device-version", "room-a"), NOW, 0, 4, 10, 1)
    foreign = replace(robot_revision, identity=("other-map", "device-version", "room-a"))
    transit = present_mission_plan(target, (), (), robot_revision, (FLOOR,))
    assert transit["destinations"][0]["status"] == "traveling"
    mixed = present_mission_plan(target, (robot_revision,), (foreign,), None, (FLOOR,))
    assert mixed["completed"] == 1
    assert mixed["destinations"][0]["name"] == "Cocina"
