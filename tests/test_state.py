from dataclasses import replace

import pytest

from custom_components.roomba_home.core.capabilities import DeviceCapabilities, DockCapabilities
from custom_components.roomba_home.core.state import RobotState, project_state


@pytest.mark.parametrize(
    "phase,cycle,activity",
    [
        ("run", "clean", "cleaning"),
        ("padWash", "clean", "cleaning"),
        ("padWash", "none", None),
        ("refill", "clean", "cleaning"),
        ("charge", "none", "docked"),
        ("hmUsrDock", "dock", "returning"),
        ("hmUsrChrg", "dock", "returning"),
        ("hmPostMsn", "clean", "returning"),
        ("hmMidMsn", "clean", "returning"),
        ("stop", "clean", "paused"),
        ("stop", "spot", "paused"),
        ("stop", "dock", None),
        ("stop", "none", "idle"),
        ("stuck", "clean", "error"),
        ("chargingerror", "none", "error"),
        ("chgerr", "none", "error"),
        ("unrecognized", "clean", None),
        ("stop", None, None),
    ],
)
def test_activity_preserves_observed_transitions_and_unknown_values(phase, cycle, activity):
    state = RobotState("fixture", "Robot", "X185240", True, 0, phase, cycle, 2, 0)
    assert state.activity == activity


@pytest.mark.parametrize(
    ("phase", "cycle", "dock_known", "wash_code", "expected_activity", "expected_ready"),
    [
        ("padWash", "none", True, 602, "docked", False),
        ("padWash", "none", True, 601, None, True),
        ("padWash", "none", None, 602, None, True),
        ("padWash", "clean", True, 602, "cleaning", True),
        ("charge", "none", True, 601, "docked", True),
    ],
)
def test_manual_mop_wash_is_docked_but_not_ready_to_start(
    phase, cycle, dock_known, wash_code, expected_activity, expected_ready
):
    state = RobotState(
        "fixture",
        "Robot",
        "X185240",
        True,
        100,
        phase,
        cycle,
        4,
        0,
        {"pad_wash_state": wash_code, "not_ready_code": 0},
        capabilities=DeviceCapabilities(dock=DockCapabilities(recognized=dock_known)),
    )
    assert state.activity == expected_activity
    assert state.ready is expected_ready
    assert state.preparing_mop is (cycle == "clean")


@pytest.mark.parametrize(
    "phase,cycle,error,expected",
    [
        ("charge", "clean", 0, True),
        ("charge", "none", 0, False),
        ("charge", "clean", 46, False),
        ("charge", "dock", 0, False),
        ("run", "clean", 0, False),
        ("charge", "unknown", 0, None),
        (None, "clean", 0, None),
        ("padWash", "clean", 0, False),
    ],
)
def test_mission_at_dock_uses_only_known_phase_cycle_and_error(phase, cycle, error, expected):
    robot = RobotState("fixture", "Robot", "X185240", True, 50, phase, cycle, 2, error)
    assert robot.mission_at_dock is expected


@pytest.mark.parametrize(
    "phase,cycle,error,expected",
    [
        ("padWash", "clean", 0, True),
        ("padWash", "none", 0, False),
        ("refill", "clean", 0, True),
        ("padWash", "clean", 44, False),
        ("refill", None, 0, None),
        ("run", "clean", 0, False),
    ],
)
def test_mop_preparation_requires_an_active_cleaning_cycle(phase, cycle, error, expected):
    robot = RobotState("fixture", "Robot", "X185240", True, 50, phase, cycle, 4, error)
    assert robot.preparing_mop is expected


def test_unrecognized_phase_and_cycle_are_not_exposed_as_state_strings():
    result = project_state(
        "fixture",
        {},
        {
            "ro-currentstate": {
                "state": {
                    "reported": {
                        "cleanMissionStatus": {
                            "phase": "fixture-private-phase",
                            "cycle": "fixture-private-cycle",
                        }
                    }
                }
            }
        },
    )
    assert result.phase is result.cycle is None
    assert result.telemetry["mission_phase"] is result.telemetry["mission_cycle"] is None


@pytest.mark.parametrize(
    "battery,expected",
    [(0, 0), (100, 100), (None, None), (-1, None), (101, None), (True, None), ("0", None)],
)
def test_unknown_battery_is_not_coerced_to_zero(battery, expected):
    state = project_state(
        "fixture",
        {},
        {
            "ro-currentstate": {
                "state": {"reported": {"batPct": battery, "cleanMissionStatus": {"phase": "run"}}}
            }
        },
    )
    assert state.battery == expected


@pytest.mark.parametrize("connected", [True, False, None, "true", 1])
def test_connectivity_requires_a_boolean_fact(connected):
    state = project_state(
        "fixture", {}, {"rw-constatus": {"state": {"reported": {"connected": connected}}}}
    )
    assert state.connected is (connected if type(connected) is bool else None)


@pytest.mark.parametrize(
    "data,expected",
    [
        ({"connectedv2": 1}, True),
        ({"connectedv2": 0, "connected": True}, False),
        ({"connectedv2": 63}, None),
        ({"connectedv2": 63, "connected": False}, False),
        ({"connectedv2": True}, None),
    ],
)
def test_native_connection_code_can_confirm_state_without_the_legacy_flag(data, expected):
    state = project_state("fixture", {}, {"rw-constatus": {"state": {"reported": data}}})
    assert state.connected is expected
    assert state.capabilities.connectivity is (True if expected is not None else None)


@pytest.mark.parametrize("shadow", [None, [], {"state": None}, {"state": {"reported": None}}])
def test_malformed_shadow_remains_unknown(shadow):
    state = project_state("fixture", {}, {"ro-currentstate": shadow})
    assert state.battery is None and state.activity is None


@pytest.mark.parametrize(
    "command,phase,cycle",
    [
        ("start", "run", "clean"),
        ("pause", "stop", "clean"),
        ("stop", "stop", "none"),
        ("dock", "charge", "none"),
    ],
)
def test_confirmations_require_the_expected_physical_state_and_connectivity(command, phase, cycle):
    state = RobotState("fixture", "Robot", "X185240", True, 50, phase, cycle, 2, 0)
    assert state.confirms(command)
    assert not replace(state, connected=False).confirms(command)
    assert not state.confirms("unsupported")
    assert not replace(state, mode=6).confirms("start")


@pytest.mark.parametrize("mission", [None, [], "run"])
def test_malformed_mission_has_no_invented_activity_or_mode(mission):
    state = project_state(
        "fixture", {}, {"ro-currentstate": {"state": {"reported": {"cleanMissionStatus": mission}}}}
    )
    assert state.activity is None and state.mode is None and state.error is None
