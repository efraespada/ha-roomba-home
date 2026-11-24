from datetime import UTC, datetime

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.history import history_metrics


def test_history_keeps_the_confirmed_origin_of_its_latest_record():
    rows = [
        {"robot_id": "robot-fixture", "timestamp": 1700000000, "initiator": "manual"},
        {"robot_id": "robot-fixture", "timestamp": 1700000500, "initiator": "cloud"},
        {"robot_id": "another-robot", "timestamp": 1700000600, "initiator": "rmtApp"},
    ]
    assert history_metrics(rows, "robot-fixture")["last_mission_initiator"] == "cloud"


@pytest.mark.parametrize("command", ["start", "point_clean", "spot", "unexpected", {}])
def test_history_retains_only_the_command_label_and_drops_point_geometry(command):
    rows = [
        {"robot_id": "fixture-a", "timestamp": 100, "cmd": {"command": "start"}},
        {
            "robot_id": "fixture-a",
            "timestamp": 200,
            "cmd": {
                "command": command,
                "p2map_id": "fixture-private-map",
                "geom": {"center": [1, 2]},
            },
            "sqft": 21,
            "done": "cncl",
        },
        {"robot_id": "fixture-b", "timestamp": 300, "cmd": {"command": "start"}},
    ]
    summary = history_metrics(rows, "fixture-a")
    expected = command if command in ("start", "point_clean", "spot") else None
    assert summary.get("last_mission_command") == expected
    assert summary["last_mission_area"] == 1.95
    assert summary["last_mission_outcome"] == "cancelled"
    assert "fixture-private-map" not in repr(summary) and "center" not in repr(summary)


@pytest.mark.parametrize(
    ("cmd", "target", "count"),
    [
        ({"command": "start"}, "whole_map", None),
        ({"command": "start", "regions": []}, "whole_map", None),
        ({"command": "start", "favorite_id": "fixture"}, None, None),
        ({"command": "start", "regions": "unknown"}, None, None),
        ({"command": "start", "regions": [None]}, None, None),
        ({"command": "start", "regions": [{"type": ["rid"]}]}, None, None),
        ({"command": "start", "regions": [{"type": "unknown"}]}, None, None),
        ({"command": "start", "regions": [{"type": "rid", "region_type": "zid"}]}, None, None),
        ({"command": "start", "regions": [{"type": "rid"}, {"region_type": "rid"}]}, "rooms", 2),
        ({"command": "start", "regions": [{"type": "zid"}]}, "saved_zones", 1),
        (
            {
                "command": "start",
                "regions": [{"type": "tid", "region_id": "fixture-private-id"}],
                "id_multipolys": [{"id": "fixture-private-id", "poly": [[0, 0], [1, 1]]}],
            },
            "temporary_zones",
            1,
        ),
        ({"command": "start", "regions": [{"type": "rid"}, {"type": "tid"}]}, "mixed_regions", 2),
        ({"command": "point_clean", "geom": {"center": [3, 4]}}, "map_point", None),
        ({"command": "spot"}, "local_spot", None),
        ({"command": "unknown"}, None, None),
    ],
)
def test_history_target_exposes_only_classification_and_region_count(cmd, target, count):
    record = {"robot_id": "fixture", "timestamp": 200, "cmd": cmd}
    result = history_metrics([record], "fixture")
    assert result.get("last_mission_target") == target
    assert result.get("last_mission_target_count") == count
    assert "fixture-private-id" not in repr(result) and "poly" not in repr(result)


def test_terminal_mission_error_is_projected_from_the_latest_valid_final_error_event():
    rows = [
        {
            "robot_id": "robot-fixture",
            "timestamp": 1700000000,
            "done": "stuck",
            "timeline": {
                "event": [{"type": "error", "ts": 1700000000, "error": {"value": 1030}}],
                "finEvents": [
                    None,
                    {"type": "reloc", "ts": 1700000030, "error": {"value": 19}},
                    {"type": "error", "ts": 1700000020, "error": {"value": 48}},
                    {"type": "error", "ts": "invalid", "error": {"value": 16}},
                    {"type": "error", "ts": 1700000100, "error": {"value": "49"}},
                    {"type": "error", "ts": 1700000100, "error": {"value": 0}},
                    {"type": "error", "ts": 1700000010, "error": {"value": 16}},
                ],
            },
        }
    ]
    summary = history_metrics(rows, "robot-fixture")
    assert summary["last_mission_outcome"] == "stuck"
    assert summary["last_mission_error"] == 48
    assert "timeline" not in summary
    rows[0]["timeline"]["finEvents"] = []
    assert "last_mission_error" not in history_metrics(rows, "robot-fixture")


def test_history_sorts_valid_rows_and_never_exposes_map_or_mission_identifiers():
    rows = [
        {"robot_id": "robot-fixture", "timestamp": 100, "done": "ok"},
        {
            "robot_id": "robot-fixture",
            "timestamp": 200,
            "durationM": 31,
            "sqft": 100,
            "done": "cncl",
            "oModeStats": {
                "vac": {"nMin": 14, "sqft": 100, "room_name": "fixture-private-room"},
                "mop": {"nMin": 2, "sqft": 0},
                "unknown": {"nMin": 8},
            },
            "startTime": 100,
            "runM": 14,
            "pauseM": 2,
            "chrgM": 0,
            "chrgs": 0,
            "evacs": 2,
            "dockedAtStart": True,
            "map_id": "fixture-private-map",
            "missionId": "fixture-private-mission",
            "cmd": {"private": True},
        },
        {"robot_id": "other-robot", "timestamp": 300},
        {"robot_id": "robot-fixture", "timestamp": True},
        None,
    ]
    assert history_metrics(rows, "robot-fixture") == {
        "history_count": 2,
        "last_mission_finished": datetime.fromtimestamp(200, UTC),
        "last_mission_duration": 31,
        "last_mission_area": 9.29,
        "last_mission_outcome": "cancelled",
        "last_mission_modes": ("vacuum", "mop"),
        "last_mission_mode_statistics": {
            "vacuum": {"duration_minutes": 14, "area_m2": 9.29},
            "mop": {"duration_minutes": 2, "area_m2": 0.0},
        },
        "last_mission_started": datetime.fromtimestamp(100, UTC),
        "last_mission_active_duration": 14,
        "last_mission_pause_duration": 2,
        "last_mission_charge_duration": 0,
        "last_mission_recharges": 0,
        "last_mission_evacuations": 2,
        "last_mission_started_at_dock": True,
    }


@pytest.mark.parametrize("done,stats", [("new", []), (None, {"mop": True})])
def test_unknown_history_values_are_not_reported_as_success(done, stats):
    result = history_metrics(
        [
            {
                "robot_id": "robot-fixture",
                "timestamp": 100,
                "done": done,
                "durationM": -1,
                "sqft": "100",
                "oModeStats": stats,
            }
        ],
        "robot-fixture",
    )
    assert result["last_mission_outcome"] is None and result["last_mission_modes"] == ()
    assert result["last_mission_duration"] is None and result["last_mission_area"] is None


def test_mode_statistics_and_record_totals_keep_unknown_numeric_values():
    result = history_metrics(
        [
            {
                "robot_id": "robot-fixture",
                "timestamp": 100,
                "runM": True,
                "pauseM": -1,
                "chrgM": "0",
                "evacs": 0,
                "dockedAtStart": False,
                "startTime": 0,
                "oModeStats": {"vacmop": {"nMin": -1, "sqft": True}},
            }
        ],
        "robot-fixture",
    )
    assert result["last_mission_mode_statistics"] == {
        "vacuum_mop": {"duration_minutes": None, "area_m2": None}
    }
    assert result["last_mission_active_duration"] is None
    assert result["last_mission_pause_duration"] is None
    assert result["last_mission_charge_duration"] is None
    assert result["last_mission_started"] is None
    assert result["last_mission_started_at_dock"] is False
    assert result["last_mission_evacuations"] == 0
    assert "last_mission_recharges" not in result


def test_empty_history_is_known_empty_and_bad_response_is_rejected():
    assert history_metrics([], "robot-fixture") == {"history_count": 0}
    with pytest.raises(ProtocolError):
        history_metrics({}, "robot-fixture")


def test_room_history_uses_exact_map_revision_and_latest_observation():
    from custom_components.roomba_home.core.history import present_rooms, room_results
    from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind

    data = {"p2mapId": "private-floor", "p2mapvId": "revision", "rid": "private-room"}

    def room(ts, **fields):
        return {"type": "room", "ts": ts, "room": {**data, **fields}}

    events = [
        None,
        {"type": "room"},
        room("invalid", area=1),
        room(21, rid=None, area=1),
        room(21),
        room(22, status=0, area=0, totalArea=42, passCount=0),
        room(20, status=5, area=11),
        room(25, rid="other-room", status=42, area=12),
    ]
    record = {"robot_id": "fixture", "timestamp": 30, "timeline": {"finEvents": events}}
    results = history_metrics([record], "fixture")["last_mission_room_results"]
    assert results == room_results(events)
    assert "private-floor" not in repr(results)
    mapped = PersistentMap(
        "private-floor",
        "revision",
        "Ground",
        (
            CleaningRegion("private-room", RegionKind.ROOM, "Hall"),
            CleaningRegion("other-room", RegionKind.ZONE, "Area"),
        ),
    )
    public = present_rooms(results, (mapped,))
    assert public == [
        {
            "room": "Hall",
            "status": "finished",
            "status_code": 0,
            "area": 0,
            "total_area": 42,
            "pass_count": 0,
        },
        {
            "room": None,
            "status": None,
            "status_code": 42,
            "area": 12,
            "total_area": None,
            "pass_count": None,
        },
    ]
    assert "private-room" not in repr(public)
    from dataclasses import replace

    assert present_rooms(results, (replace(mapped, version_id="changed"),))[0]["room"] is None
