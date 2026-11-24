import json
from datetime import UTC, datetime

import pytest

from custom_components.roomba_home.core.telemetry import (
    PART_COUNT_TYPES,
    PARTS,
    at,
    convert,
    project_parts,
    project_telemetry,
)


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("bool", False, False),
        ("bool", 0, None),
        ("bool", "false", None),
        ("flag", 0, False),
        ("flag", 1, True),
        ("flag", True, None),
        ("flag", 2, None),
        ("int", 0, 0),
        ("int", True, None),
        ("int", -1, None),
        ("int", 1.2, None),
        ("int", 2**54, None),
        ("int", "1", None),
        ("area", 100, 9.29),
        ("area", 0, 0.0),
        ("area", -1, None),
        ("area", float("nan"), None),
        ("area", float("inf"), None),
        ("area", True, None),
        ("area", "10", None),
        ("timezone", "Europe/Paris", "Europe/Paris"),
        ("timezone", "Etc/GMT+2", "Etc/GMT+2"),
        ("timezone", 5, None),
        ("timezone", "A" * 81, None),
        ("timezone", "../private/key", None),
        ("phase", "run", "run"),
        ("phase", "future_phase", None),
        ("phase", [], None),
        ("cycle", "none", "none"),
        ("cycle", "private arbitrary text", None),
        ("initiator", "cloud", "cloud"),
        ("initiator", "rmtApp", "rmtApp"),
        ("initiator", "schedule", "schedule"),
        ("initiator", "unknown-provider-value", None),
        ("pad", "padPlate", "padPlate"),
        ("pad", "future_pad", None),
        ("version", "26.9.0-test+1", "26.9.0-test+1"),
        ("version", "x\nsecret", None),
        ("version", "x" * 81, None),
        ("version", {}, None),
        ("timestamp", 0, None),
        ("timestamp", -1, None),
        ("timestamp", True, None),
        ("timestamp", 32_503_680_001, None),
        ("language", "es-ES", "es-ES"),
        ("language", "en", "en"),
        ("language", "fixture private name", None),
    ],
)
def test_type_and_unit_contract(kind, value, expected):
    assert convert(kind, value) == expected


def test_timestamp_is_aware_and_no_wall_clock_progress_is_fabricated():
    assert convert("timestamp", 1_700_000_000) == datetime.fromtimestamp(1_700_000_000, UTC)
    assert "progress_percent" not in project_telemetry({})
    assert "eta" not in project_telemetry({})


def test_mission_origin_is_read_from_the_mission():
    current = {"cleanMissionStatus": {"initiator": "cloud"}, "lastCommand": {"initiator": "manual"}}
    result = project_telemetry({"ro-currentstate": {"state": {"reported": current}}})
    assert result == {"mission_initiator": "cloud"}


def test_schedule_exposes_count_without_room_names_or_routines():
    value = project_telemetry(
        {
            "rw-schedule": {
                "state": {"reported": {"cleanSchedule2": [{"name": "fixture-private-room"}]}}
            }
        }
    )
    assert value == {"schedule_count": 1}


@pytest.mark.parametrize("shadow", [None, [], {}, {"state": None}, {"state": {"reported": []}}])
def test_bad_optional_shadow_is_empty(shadow):
    assert project_telemetry({"rw-settings": shadow}) == {}


def test_only_allowlisted_fields_leave_private_documents():
    result = project_telemetry(
        {
            "ro-currentstate": {
                "state": {
                    "reported": {
                        "batPct": 20,
                        "passwordHash": "fixture-private-hash",
                        "p2maps": ["fixture-map"],
                        "cleanMissionStatus": {
                            "phase": "run",
                            "sqft": 100,
                            "missionId": "fixture-mission",
                            "condNotReady": [4, 8],
                        },
                        "bin": {"present": False},
                        "dock": {"error": 0},
                    }
                }
            },
            "rw-settings": {
                "state": {
                    "reported": {
                        "name": "fixture-private-name",
                        "childLock": False,
                        "audio": {"volume": 0},
                    }
                }
            },
        }
    )
    assert result["mission_area"] == 9.29
    assert result["bin_present"] is False
    assert result["audio_volume"] == 0
    assert result["child_lock"] is False
    assert result["not_ready_conditions"] == (4, 8)
    assert "fixture-" not in json.dumps(result)
    assert at({}, "missing.child") is not None


@pytest.mark.parametrize("conditions", [[True], ["4"], {}, None])
def test_readiness_conditions_must_be_numeric(conditions):
    result = project_telemetry(
        {
            "ro-currentstate": {
                "state": {"reported": {"cleanMissionStatus": {"condNotReady": conditions}}}
            }
        }
    )
    assert result["not_ready_conditions"] is None


@pytest.mark.parametrize("document", [None, [], {}, {"parts": None}, {"parts": {}}])
def test_missing_parts_do_not_become_healthy_consumables(document):
    assert project_parts(document) == {}


@pytest.mark.parametrize("part", list(PARTS))
def test_all_catalog_parts_keep_their_own_identity_and_units(part):
    count_type = PART_COUNT_TYPES[part]
    projected = project_parts(
        {
            "robot_id": "fixture-private-id",
            "parts": [
                {
                    "part_id": part,
                    "counter": 100,
                    "count_type": count_type,
                    "count_remaining": 0,
                    "count_used": 100,
                    "minutes_remaining": -1,
                    "counter_category": "maintenance",
                    "reset_by": "fixture-private-user",
                }
            ],
        }
    )
    if part == "147":
        assert projected[f"part_{part}_usage"] is None
    else:
        assert projected[f"part_{part}_usage"] == 100
        assert projected[f"part_{part}_remaining"] == 0
    assert projected[f"part_{part}_unit"] == (
        "m²" if count_type == "sqft" else "min" if count_type == "minutes" else None
    )
    assert "fixture-" not in json.dumps(projected)


def test_part_catalog_disabled_counter_is_not_healthy_or_due():
    document = {
        "parts": [{"part_id": "71", "counter": 100, "count_remaining": 0, "count_type": "minutes"}]
    }
    catalog = {"parts": [{"part_id": "71", "counter_enabled": False}]}
    assert project_parts(document, catalog)["part_71_usage"] is None
    assert project_parts(document, catalog)["part_71_remaining"] is None


@pytest.mark.parametrize("raw", [-1, True, "10", None, 101])
def test_bad_usage_never_becomes_a_percentage(raw):
    result = project_parts(
        {
            "parts": [
                {"part_id": "71", "counter": raw, "count_type": "minutes", "count_remaining": -1}
            ]
        }
    )
    assert result["part_71_usage"] is None
    assert result["part_71_remaining"] is None


@pytest.mark.parametrize("count_type", [None, [], "unrecognized", "sqft"])
def test_unexpected_part_unit_does_not_change_existing_sensor_semantics(count_type):
    result = project_parts(
        {
            "parts": [
                {"part_id": "71", "counter": 1, "count_type": count_type, "count_remaining": 10}
            ]
        }
    )
    assert result["part_71_remaining"] is None
    assert result["part_71_count_type"] is None


@pytest.mark.parametrize("catalog", [None, [], {"parts": None}, {"parts": [None, {"part_id": []}]}])
def test_malformed_catalog_and_unknown_parts_do_not_escape_allowlist(catalog):
    assert (
        project_parts({"parts": [None, {"part_id": []}, {"part_id": "fixture-private"}]}, catalog)
        == {}
    )


def test_part_area_count_is_converted_and_unknown_category_is_absent():
    result = project_parts(
        {
            "parts": [
                {
                    "part_id": "212",
                    "count_type": "sqft",
                    "count_remaining": 100,
                    "count_used": 200,
                    "counter_category": [],
                }
            ]
        }
    )
    assert result["part_212_remaining"] == 9.29
    assert result["part_212_used"] == 18.58
    assert result["part_212_category"] is None


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ({"connectedv2": 0, "connected": True}, 1_700_000_000),
        ({"connectedv2": 1}, 1_700_000_000),
        ({"connectedv2": "1", "connected": False}, 1_700_000_001),
        ({"connectedv2": True, "connected": 1}, None),
    ],
)
def test_connectivity_time_uses_the_selected_attribute(reported, expected):
    shadow = {
        "state": {"reported": reported},
        "metadata": {
            "reported": {
                "connectedv2": {"timestamp": 1_700_000_000},
                "connected": {"timestamp": 1_700_000_001},
            }
        },
        "timestamp": 1_800_000_000,
    }
    metrics = project_telemetry({"rw-constatus": shadow})
    assert metrics.get("connection_updated_at") == (
        datetime.fromtimestamp(expected, UTC) if expected is not None else None
    )


def test_connectivity_time_does_not_fall_back_to_an_unselected_attribute():
    shadow = {
        "state": {"reported": {"connectedv2": 0, "connected": True}},
        "metadata": {
            "reported": {"connectedv2": {"timestamp": 0}, "connected": {"timestamp": 1_700_000_001}}
        },
    }
    assert "connection_updated_at" not in project_telemetry({"rw-constatus": shadow})
