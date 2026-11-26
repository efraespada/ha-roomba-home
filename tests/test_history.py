from datetime import UTC, datetime

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.history import history_metrics, mission_reports


def test_mission_reports_expose_only_owned_cleaning_records_and_exact_archive_references():
    row = {
        "robot_id": "fixture-a",
        "missionId": "private-mission",
        "timestamp": 1700000500,
        "startTime": 1700000000,
        "durationM": 8,
        "sqft": 100,
        "done": "ok",
        "cmd": {"command": "point_clean"},
        "p2maps": [
            None,
            {"p2map_id": "..", "p2mapv_id": "version"},
            {"p2map_id": "map", "p2mapv_id": "../version"},
            {"p2map_id": "private-floor", "p2mapv_id": "version"},
            {"p2map_id": "private-floor", "p2mapv_id": "version"},
        ],
        "timeline": {
            "finEvents": [
                None,
                {"type": [], "ts": 1700000000},
                {"type": "unrecognized", "ts": 1700000000},
                {"type": "travel"},
                {"type": "padWash", "ts": 1700000100, "ets": 1700000110, "secret": "not rendered"},
                {"type": "charge", "ts": 1700000500, "ets": 1700000200},
                {"type": "start", "ts": 1700000000},
            ]
        },
    }
    earlier = {
        "robot_id": "fixture-a",
        "timestamp": 1700000000,
        "cmd": {"command": "start"},
        "nMssn": 7,
    }
    other_robot = {**row, "robot_id": "fixture-b"}
    mapping = {**row, "cmd": {"command": "train"}}
    latest, previous = mission_reports([earlier, other_robot, mapping, row], "fixture-a")
    assert len(latest.key) == 64
    assert latest.key == mission_reports([row], "fixture-a")[0].key
    assert latest.maps == (("private-floor", "version"),)
    assert not previous.maps and not previous.timeline
    assert previous.summary()["started_at"] is None
    assert latest.summary()["duration_minutes"] == 8
    assert latest.summary()["area_m2"] == 9.29
    detail = latest.detail(())
    assert [item["type"] for item in detail["timeline"]] == ["start", "padWash", "charge", "finish"]
    assert [item["duration_seconds"] for item in detail["timeline"]] == [None, 10, None, None]
    assert detail["timeline"][-1]["timestamp"] == row["timestamp"]
    assert "private" not in repr(detail) and "not rendered" not in repr(detail)


def test_history_keeps_typed_event_codes_and_prefers_a_reported_finish():
    row = {
        "robot_id": "fixture-a",
        "timestamp": 1700000500,
        "cmd": {"command": "start"},
        "timeline": {
            "finEvents": [
                {"type": "error", "ts": 1700000100, "error": {"value": 48}},
                {"type": "error", "ts": 1700000102, "error": {"value": True}},
                {"type": "padWash", "ts": 1700000300, "padWash": {"pwState": 603, "error": 0}},
                {"type": "refill", "ts": 1700000310, "refill": {"frState": 404, "error": "hidden"}},
                {"type": "evac", "ts": 1700000470, "ets": 1700000487, "evac": {"state": 301}},
                {"type": "evac", "ts": 1700000488, "evac": {"error": 350}},
                {"type": "fin", "ts": 1700000498},
            ]
        },
    }
    (report,) = mission_reports([row], "fixture-a")
    timeline = report.detail(())["timeline"]
    assert [(event["type"], event.get("error_code"), event.get("dock")) for event in timeline] == [
        ("error", 48, None),
        ("error", None, None),
        ("padWash", None, {"component": "pad_wash", "state_code": 603, "error_code": 0}),
        ("refill", None, {"component": "refill", "state_code": 404, "error_code": None}),
        ("evac", None, {"component": "evacuation", "state_code": 301, "error_code": None}),
        ("evac", None, {"component": "evacuation", "state_code": None, "error_code": 350}),
        ("finish", None, None),
    ]
    assert timeline[4]["duration_seconds"] == 17
    assert timeline[-1]["timestamp"] == 1700000498


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
        ({"command": "start", "p2map_id": None, "regions": None}, "whole_map", None),
        ({"command": "start", "favorite_id": "fixture"}, None, None),
        ({"command": "start", "favorite_id": "fixture", "regions": None}, None, None),
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


def test_zone_history_uses_the_mission_target_with_its_requested_map_revision():
    from custom_components.roomba_home.core.history import present_zones, zone_results
    from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind

    def zone(identity, timestamp, *, map_id="private-map", version="revision", **details):
        return {
            "type": "zone",
            "ts": timestamp,
            "zone": {
                "zid": identity,
                "p2mapId": map_id,
                "p2mapvId": version,
                **details,
            },
        }

    events = [
        zone("160", 15, map_id="different-map", version="previous", area=3),
        zone("160", 19, area=2),
        zone("160", 20, version="previous", status=0, area=5, totalArea=10, passCount=0),
        zone("saved", 27, status=2, area=11),
        zone("orphan", 28, status=100),
        zone("temporary", 31, status=5),
    ]
    command = {
        "command": "start",
        "p2map_id": "private-map",
        "user_p2mapv_id": "revision",
        "regions": [
            {"type": "tid", "region_id": "160"},
            {"type": "zid", "region_id": "saved"},
            {"type": "tid", "region_id": "temporary"},
            {"type": "rid", "region_id": "ignored"},
            {"type": "tid", "region_id": []},
            None,
        ],
        "id_multipolys": [
            {
                "id": "160",
                "metadata": {"furniture_id": "furniture-1"},
                "poly": [[0, 0], [0, 1], [1, 1], [1, 0]],
            }
        ],
    }
    floor = PersistentMap(
        "private-map",
        "revision",
        "Floor",
        (
            CleaningRegion("furniture-1", RegionKind.FURNITURE, "Sofa"),
            CleaningRegion("saved", RegionKind.ZONE, "Near the entrance"),
            CleaningRegion("temporary", RegionKind.ZONE, "Unrelated saved zone"),
        ),
    )
    results = zone_results(events, command)
    rows = present_zones(results, (floor,))
    assert [(r["kind"], r["name"], r["area"]) for r in rows] == [
        ("zone", None, 3),
        ("furniture", "Sofa", 5),
        ("saved_zone", "Near the entrance", 11),
        ("zone", None, None),
        ("temporary_zone", None, None),
    ]
    assert rows[1] == {
        "kind": "furniture",
        "name": "Sofa",
        "area": 5,
        "status": "finished",
        "status_code": 0,
        "total_area": 10,
        "pass_count": 0,
    }
    raw = present_zones(zone_results(events), (floor,))
    assert raw[3]["kind"] == "saved_zone" and raw[3]["name"] == "Near the entrance"
    assert present_zones(zone_results(events, {"command": "start"}), (floor,)) == raw
    assert present_zones(zone_results(events, {"command": "point_clean"}), (floor,)) == raw
    assert present_zones(zone_results(events, command | {"user_p2mapv_id": []}), (floor,)) == raw
    assert "private-map" not in repr(rows) and "furniture-1" not in repr(rows)

    stored = {
        "robot_id": "fixture",
        "timestamp": 33,
        "timeline": {"finEvents": events},
        "cmd": command | {"regions": command["regions"][:1]},
    }
    summary = history_metrics([stored], "fixture")
    assert summary["last_mission_target"] == "furniture"
    assert summary["last_mission_target_count"] == 1
    assert summary["last_mission_zone_results"][1] == results[1]


@pytest.mark.parametrize(("final_status", "confirmed"), [(0, 2), (5, 1)])
def test_saved_zone_counts_completed_events_across_correlated_revisions(final_status, confirmed):
    from custom_components.roomba_home.core.history import present_zones, zone_results
    from custom_components.roomba_home.core.mission_plan import mission_plan, present_mission_plan

    def event(timestamp, status, passes, map_id="floor"):
        return {
            "type": "zone",
            "ts": timestamp,
            "zone": {
                "p2mapId": map_id,
                "p2mapvId": f"robot-{timestamp}",
                "zid": "100",
                "passCount": passes,
                "status": status,
            },
        }

    command = {
        "command": "start",
        "p2map_id": "floor",
        "user_p2mapv_id": "reviewed",
        "regions": [{"type": "zid", "region_id": "100", "params": {"twoPass": True}}],
    }
    first = event(10, 1, 0)
    second = event(20, final_status, 1)
    duplication = event(11, 1, 0)
    unrelated = event(15, 0, 2, map_id="foreign")
    draft = mission_plan(command)
    finished = zone_results([second, unrelated, first, duplication], command)
    zone = present_zones(finished, ())[1]
    assert zone["pass_count"] == 1 and zone["confirmed_completed_passes"] == confirmed
    history = present_mission_plan(draft, finished, (), None, (), archived=True)
    assert history["destinations"][0]["confirmed_completed_passes"] == confirmed
    assert history["destinations"][0]["reported_pass_count"] == 1
    underway = zone_results([event(20, None, 1)], command)
    running = present_mission_plan(draft, zone_results([first], command), underway, None, ())
    assert running["destinations"][0]["status"] == "in_progress"
    assert running["destinations"][0]["confirmed_completed_passes"] == 1
    assert zone_results([second], command)[0].confirmed_completed_passes is None
    assert all(
        result.confirmed_completed_passes is None for result in zone_results([first, second])
    )


def test_archived_destination_duration_totals_passes_and_excludes_pauses():
    start = 1700000000

    def zone(begin, end, pass_number, status):
        return {
            "type": "zone",
            "ts": start + begin,
            "ets": start + end,
            "zone": {
                "p2mapId": "floor",
                "p2mapvId": f"robot-{pass_number}",
                "zid": "100",
                "passCount": pass_number,
                "status": status,
            },
        }

    row = {
        "robot_id": "fixture",
        "timestamp": start + 424,
        "startTime": start,
        "done": "ok",
        "cmd": {
            "command": "start",
            "p2map_id": "floor",
            "user_p2mapv_id": "saved",
            "regions": [{"type": "zid", "region_id": "100"}],
        },
        "timeline": {
            "finEvents": [
                zone(51, 207, 0, 1),
                {"type": "pause", "ts": start + 70, "ets": start + 90},
                zone(208, 366, 1, 0),
            ]
        },
    }
    (report,) = mission_reports([row], "fixture")
    (destination,) = report.detail(())["plan"]["destinations"]
    assert destination["cleaning_elapsed_seconds"] == 294
    assert destination["confirmed_completed_passes"] == 2
    assert destination["status"] == "finished"
    assert "cleaning_elapsed_seconds" not in report.summary()
