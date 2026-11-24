from dataclasses import replace

import pytest

from custom_components.roomba_home.core.capabilities import DockCapabilities
from custom_components.roomba_home.core.problems import (
    ProblemTracker,
    dock_has_problem,
    has_problem,
    observations,
    reason,
)
from custom_components.roomba_home.core.state import RobotState


@pytest.fixture
def robot():
    return RobotState(
        "fixture",
        "Robot",
        "X185240",
        True,
        50,
        "charge",
        "none",
        2,
        0,
        {
            "dock_known": True,
            "dock_error": 0,
            "evacuation_state": 301,
            "refill_state": 401,
            "pad_wash_state": 601,
            "pad_dry_state": 701,
            "not_ready_code": 0,
        },
    )


@pytest.mark.parametrize(
    "source,key,code",
    [
        ("dock", "dock_error", 501),
        ("evacuation", "evacuation_state", 353),
        ("refill", "refill_state", 451),
        ("pad_wash", "pad_wash_state", 654),
        ("pad_dry", "pad_dry_state", 750),
        ("readiness", "not_ready_code", 4),
    ],
)
def test_equipment_errors_keep_their_component_source(robot, source, key, code):
    robot.telemetry[key] = code
    assert observations(robot)[source] == code
    assert has_problem(robot) is True


@pytest.mark.parametrize(
    "key,code",
    [
        ("evacuation_state", 300),
        ("refill_state", 400),
        ("pad_wash_state", 600),
        ("pad_dry_state", 700),
        ("dock_error", None),
        ("pad_dry_state", 9999),
    ],
)
def test_unknown_component_state_is_not_a_healthy_state(robot, key, code):
    robot.telemetry[key] = code
    assert has_problem(robot) is None


def test_normal_snapshot_is_healthy_but_mission_error_is_not(robot):
    assert has_problem(robot) is False
    assert has_problem(replace(robot, error=17)) is True
    assert has_problem(replace(robot, error=None)) is None
    assert has_problem(replace(robot, connected=False)) is True


def test_shared_refill_normal_state_does_not_prove_absent_washing_or_drying_health(robot):
    values = {
        key: value
        for key, value in robot.telemetry.items()
        if key not in {"pad_wash_state", "pad_dry_state"}
    }
    codes = observations(replace(robot, telemetry=values))
    assert codes["refill"] == 0
    assert codes["pad_wash"] is None and codes["pad_dry"] is None
    assert has_problem(replace(robot, connected=None)) is None


def test_other_component_state_cannot_clear_an_active_dock_error(robot):
    tracker = ProblemTracker({"pad_wash": 654})
    robot.telemetry["pad_wash_state"] = 401
    codes = observations(robot)
    assert codes["pad_wash"] is None
    assert dock_has_problem(robot) is None
    assert tracker.observe(codes) == []
    assert tracker.codes["pad_wash"] == 654

    robot.telemetry["pad_wash_state"] = 601
    (recovered,) = tracker.observe(observations(robot))
    assert recovered.source == "pad_wash" and recovered.event_type == "problem_cleared"


def test_shared_dock_field_clears_only_the_component_its_code_belongs_to(robot):
    robot.telemetry.pop("pad_wash_state")
    robot.telemetry["refill_state"] = 602
    tracker = ProblemTracker({"pad_wash": 654, "refill": 451})
    codes = observations(robot)
    assert codes["refill"] is None and codes["pad_wash"] == 0
    (recovered,) = tracker.observe(codes)
    assert recovered.source == "pad_wash" and tracker.codes["refill"] == 451


def test_unsupported_dock_components_cannot_invalidate_confirmed_health(robot):
    robot.telemetry["pad_wash_state"] = 654
    robot.telemetry.pop("refill_state")
    robot.telemetry.pop("pad_dry_state")
    robot = replace(
        robot,
        capabilities=replace(
            robot.capabilities,
            dock=DockCapabilities(True, evacuation=True, refill=False, wash=False, dry=False),
        ),
    )
    assert observations(robot)["pad_wash"] is None
    assert has_problem(robot) is False and dock_has_problem(robot) is False
    robot.telemetry["evacuation_state"] = 353
    assert has_problem(robot) is True and dock_has_problem(robot) is True


def test_updating_dock_is_not_classified_as_equipment_failure(robot):
    robot.telemetry["dock_error"] = 510
    assert observations(robot)["dock"] == 0
    assert has_problem(robot) is False


def test_missing_consumable_source_cannot_claim_all_problems_cleared(robot):
    robot.telemetry["parts_available"] = False
    assert has_problem(robot) is None


def test_firmware_errors_are_independent_of_mission_and_recover_on_a_known_state(robot):
    tracker = ProblemTracker()
    robot.telemetry["software_deployment_state"] = 106
    (detected,) = tracker.observe(observations(robot))
    assert has_problem(robot) is True
    assert detected.attributes()["reason"] == "hardware_not_suitable"
    robot.telemetry["software_deployment_state"] = 9
    assert tracker.observe(observations(robot)) == []
    robot.telemetry["software_deployment_state"] = 4
    (recovered,) = tracker.observe(observations(robot))
    assert recovered.event_type == "problem_cleared"
    assert recovered.source == "firmware" and has_problem(robot) is False


def test_malformed_readiness_list_cannot_claim_robot_is_healthy(robot):
    robot.telemetry["not_ready_conditions"] = None
    assert has_problem(robot) is None


def test_readiness_conditions_generate_events_even_when_the_main_code_is_zero(robot):
    robot.telemetry["not_ready_conditions"] = (6, 0, 4, 4)
    assert has_problem(robot) is True
    tracker = ProblemTracker()
    (first,) = tracker.observe(observations(robot))
    assert first.attributes() == {
        "source": "readiness_conditions",
        "code": 3,
        "previous_code": None,
        "reason": "reported_conditions",
        "condition_codes": [0, 4, 6],
        "previous_condition_codes": None,
    }
    restored = ProblemTracker({"readiness_conditions": [0, 4, 6]})
    assert restored.observe(observations(robot)) == []
    robot.telemetry["not_ready_conditions"] = (0, 6, 8)
    (changed,) = restored.observe(observations(robot))
    assert changed.event_type == "problem_changed"
    assert changed.attributes()["condition_codes"] == [0, 6, 8]
    assert changed.attributes()["previous_condition_codes"] == [0, 4, 6]
    robot.telemetry["not_ready_conditions"] = None
    assert restored.observe(observations(robot)) == []
    robot.telemetry["not_ready_conditions"] = ()
    (cleared,) = restored.observe(observations(robot))
    assert cleared.event_type == "problem_cleared"
    assert cleared.attributes()["condition_codes"] == []


@pytest.mark.parametrize("phase,source", [("stuck", "stuck"), ("chgerr", "charging_problem")])
def test_problem_phase_with_no_numeric_error_emits_and_clears(robot, phase, source):
    tracker = ProblemTracker()
    blocked = replace(robot, phase=phase, error=0)
    assert has_problem(blocked) is True
    (opened,) = tracker.observe(observations(blocked))
    assert opened.source == source and opened.event_type == "problem_detected"
    assert tracker.observe(observations(replace(blocked, phase="unknown"))) == []
    (cleared,) = tracker.observe(observations(robot))
    assert cleared.source == source and cleared.event_type == "problem_cleared"


@pytest.mark.parametrize(
    "source,key,problem,normal",
    [("bin_missing", "bin_present", False, True), ("bin_full", "bin_full", True, False)],
)
def test_explicit_bin_flags_are_observable_without_a_mission_code(
    robot, source, key, problem, normal
):
    tracker = ProblemTracker()
    robot.telemetry[key] = problem
    assert has_problem(robot) is True
    (detected,) = tracker.observe(observations(robot))
    assert detected.attributes()["reason"] == source
    robot.telemetry[key] = None
    assert tracker.observe(observations(robot)) == []
    robot.telemetry[key] = normal
    (cleared,) = tracker.observe(observations(robot))
    assert cleared.event_type == "problem_cleared"


@pytest.mark.parametrize("source,shared", [("pad_wash", 650), ("pad_dry", 750)])
def test_legacy_shared_refill_state_can_report_wash_or_dry_error(robot, source, shared):
    del robot.telemetry[source + "_state"]
    robot.telemetry["refill_state"] = shared
    assert observations(robot)[source] == shared


@pytest.mark.parametrize(
    "usage,remaining,expected", [(100, None, 1), (99, 0, 1), (0, 20, 0), (None, None, None)]
)
def test_maintenance_due_uses_explicit_counters(robot, usage, remaining, expected):
    robot.telemetry.update(part_71_usage=usage, part_71_remaining=remaining)
    assert observations(robot)["part_71"] == expected


def test_repeated_error_changes_and_recovery_are_distinct():
    tracker = ProblemTracker()
    first = tracker.observe({"mission": 17})
    assert first[0].event_type == "problem_detected"
    for _ in range(10):
        assert tracker.observe({"mission": 17}) == []
    changed = tracker.observe({"mission": 18})
    assert changed[0].event_type == "problem_changed"
    assert changed[0].previous_code == 17
    cleared = tracker.observe({"mission": 0})
    assert cleared[0].event_type == "problem_cleared"
    assert cleared[0].attributes()["previous_code"] == 18
    assert tracker.observe({"mission": 0}) == []


def test_missing_evidence_offline_and_unrelated_source_cannot_clear_active_error(robot):
    tracker = ProblemTracker({"mission": 17})
    changes = tracker.observe(observations(replace(robot, connected=False)))
    assert tracker.codes["mission"] == 17
    assert [c.source for c in changes] == ["connection"]
    assert tracker.observe({"mission": None}) == []
    assert tracker.codes["mission"] == 17


@pytest.mark.parametrize(
    "restored", [None, [], {"mission": True}, {"mission": -1}, {"unknown_private_key": 17}]
)
def test_restore_is_allowlisted_and_typed(restored):
    assert ProblemTracker(restored).codes == {}


def test_restore_deduplicates_active_error_and_preserves_component_isolation():
    tracker = ProblemTracker({"mission": 17, "dock": 501})
    assert tracker.observe({"mission": 17, "dock": 501}) == []
    assert [c.source for c in tracker.observe({"mission": 18, "dock": 0})] == ["mission", "dock"]


@pytest.mark.parametrize(
    "source,code,expected",
    [
        ("connection", 1, "disconnected"),
        ("part_71", 1, "maintenance_due"),
        ("mission", 17, "provider_code"),
        ("mission", 4, "left_wheel_jammed"),
        ("mission", 106, "battery_too_hot"),
        ("mission", 451, "dock_tank_level_too_low"),
        ("mission", 670, "cleaning_tray_out_of_position"),
        ("mission", 1026, "mop_stuck"),
        ("mission", 1029, "incompatible_map"),
        ("readiness", 4, "provider_code"),
        ("refill", 450, "dock_tank_missing"),
        ("dock", 9999, "unknown_code"),
    ],
)
def test_reason_is_a_bounded_protocol_classification(source, code, expected):
    assert reason(source, code) == expected
