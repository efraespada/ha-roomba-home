"""Control policy over a semantic fake; these tests cannot move a robot."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from custom_components.roomba_home.core.actions import Command
from custom_components.roomba_home.core.application import (
    ControlError,
    ControlPlan,
    ControlState,
    PreparationConfirmation,
    execute_control,
    prepare_control,
)
from custom_components.roomba_home.core.capabilities import DigitalSpotCapability
from custom_components.roomba_home.core.cleaning import (
    CleaningCapabilities,
    CleaningMode,
    CleaningProfile,
)
from custom_components.roomba_home.core.cleaning_protocol import reported_cleaning_mode
from custom_components.roomba_home.core.dock import DockSnapshot
from custom_components.roomba_home.core.errors import AuthenticationError
from custom_components.roomba_home.core.preferences import profile_preferences, restore_profile

CAPS = CleaningCapabilities(frozenset(CleaningMode), 4, 3, True, True, True)
BASE = ControlState(True, "docked", False, CleaningMode.VACUUM, CAPS, docking=True)
RUNNING = replace(BASE, activity="cleaning", mission_active=True)
PAUSED = replace(RUNNING, activity="paused")
MISSION_IDENTITY = (10, datetime.fromtimestamp(100, UTC))
PREPARING = replace(
    RUNNING, mode=CleaningMode.MOP, preparing_mop=True, mission_identity=MISSION_IDENTITY
)


class Port:
    def __init__(self, *states, send_error=None, read_error=None):
        self.states = list(states or [BASE])
        self.active = True
        self.now = 0
        self.sent = []
        self.statuses = []
        self.preparations = []
        self.send_error = send_error
        self.read_error = read_error

    async def refresh(self):
        if self.read_error:
            raise self.read_error
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]

    async def send(self, command, profile):
        self.sent.append((command, profile))
        if self.send_error:
            raise self.send_error

    def report(self, status):
        self.statuses.append(status)

    def defer_preparation(self, plan, state):
        self.preparations.append((plan, state))
        self.report("submitted")

    async def wait(self, seconds):
        self.now += seconds

    def clock(self):
        return self.now


@pytest.mark.parametrize("mode", CleaningMode)
async def test_start_confirms_each_requested_mode_without_equating_ack_with_execution(mode):
    profile = CleaningProfile(mode)
    running = replace(RUNNING, mode=mode)
    port = Port(BASE, BASE, running)
    await execute_control(port, Command.VACUUM, profile)
    assert port.sent == [(Command.VACUUM, profile)]
    assert port.statuses == ["pending", "confirmed"] and port.now == 10


@pytest.mark.parametrize("command", [Command.VACUUM, Command.RESUME])
async def test_pad_preparation_is_submitted_until_floor_cleaning_is_observed(command):
    initial = BASE if command is Command.VACUUM else replace(PAUSED, mode=CleaningMode.MOP)
    profile = CleaningProfile(CleaningMode.MOP)
    port = Port(initial, PREPARING)
    await execute_control(port, command, profile)
    assert [sent for sent, _ in port.sent] == [command]
    assert port.statuses == ["pending", "submitted"] and port.now == 5
    ((plan, stage),) = port.preparations
    assert stage is PREPARING and not plan.confirms(stage)
    assert plan.confirms(replace(stage, preparing_mop=False))


async def test_start_while_the_existing_mission_is_preparing_never_republishes():
    port = Port(PREPARING)
    await execute_control(port, Command.VACUUM, CleaningProfile())
    assert not port.sent and port.statuses == ["submitted"]
    assert len(port.preparations) == 1


@pytest.mark.parametrize("mode", [None, CleaningMode.VACUUM, CleaningMode.VACUUM_MOP])
async def test_wash_preparation_in_a_different_or_unknown_mode_cannot_acknowledge_a_start(mode):
    port = Port(BASE, replace(PREPARING, mode=mode))
    with pytest.raises(ControlError, match="command_unconfirmed"):
        await execute_control(port, Command.VACUUM, CleaningProfile(CleaningMode.MOP))
    assert not port.preparations and len(port.sent) == 1


async def test_pad_preparation_with_a_new_dock_fault_is_unconfirmed_immediately():
    port = Port(BASE, replace(PREPARING, dock=DockSnapshot(fault=517)))
    with pytest.raises(ControlError, match="command_unconfirmed"):
        await execute_control(port, Command.VACUUM, CleaningProfile(CleaningMode.MOP))
    assert port.statuses == ["pending", "unconfirmed"] and port.now == 5


@pytest.mark.parametrize(
    "state,now,expected",
    [
        (PREPARING, 100, None),
        (None, 100, None),
        (replace(PREPARING, connected=False), 100, None),
        (replace(PREPARING, mission_identity=None, preparing_mop=False), 100, None),
        (replace(PREPARING, activity="error"), 100, "unconfirmed"),
        (replace(PREPARING, mission_active=False), 100, "unconfirmed"),
        (replace(PREPARING, dock=DockSnapshot(fault=517)), 100, "unconfirmed"),
        (replace(PREPARING, mission_identity=(11, MISSION_IDENTITY[1])), 100, "unconfirmed"),
        (replace(PREPARING, preparing_mop=False), 100, "confirmed"),
        (replace(PREPARING, preparing_mop=False), 300, "unconfirmed"),
    ],
)
def test_deferred_confirmation_uses_the_same_mission_and_expires(state, now, expected):
    plan = ControlPlan(Command.VACUUM, expected_mode=CleaningMode.MOP)
    assert PreparationConfirmation(plan, MISSION_IDENTITY, 300).result(state, now) == expected
    assert PreparationConfirmation(plan, None, 300).result(PREPARING, 100) is None


@pytest.mark.parametrize(
    "command,initial,final",
    [
        (Command.PAUSE, RUNNING, PAUSED),
        (Command.CANCEL, PAUSED, replace(BASE, activity="idle")),
        (Command.CANCEL, PREPARING, replace(BASE, activity="idle")),
        (Command.DOCK, replace(BASE, activity="idle"), BASE),
        (Command.RESUME, PAUSED, RUNNING),
    ],
)
async def test_other_control_transitions_use_one_publication(command, initial, final):
    port = Port(initial, final)
    await execute_control(port, command, CleaningProfile())
    assert port.sent == [(command, None)]
    assert port.statuses == ["pending", "confirmed"]


async def test_start_on_paused_mission_resumes_existing_mode_without_next_profile():
    current = replace(PAUSED, mode=CleaningMode.MOP)
    port = Port(current, replace(current, activity="cleaning"))
    await execute_control(port, Command.VACUUM, CleaningProfile(CleaningMode.VACUUM_MOP))
    assert port.sent == [(Command.RESUME, None)]


@pytest.mark.parametrize("initial", [PAUSED, RUNNING])
async def test_new_area_mission_does_not_resume_or_replace_an_existing_mission(initial):
    port = Port(initial)
    with pytest.raises(ControlError, match="unsupported_start"):
        await execute_control(port, Command.VACUUM, CleaningProfile(), new_mission=True)
    assert not port.sent


POINT_READY = replace(BASE, digital_spot=DigitalSpotCapability.SUPPORTED)
POINT_RUNNING = replace(
    POINT_READY,
    activity="cleaning",
    mission_active=True,
    mission_identity=MISSION_IDENTITY,
    mission_initiator="rmtApp",
)


async def test_point_starts_one_new_remote_vacuum_mission_without_claiming_target_confirmed():
    port = Port(POINT_READY, POINT_READY, POINT_RUNNING)
    await execute_control(port, Command.POINT_CLEAN, CleaningProfile())
    assert port.sent == [(Command.POINT_CLEAN, CleaningProfile())]
    assert port.statuses == ["pending", "submitted"]


@pytest.mark.parametrize(
    "state",
    [
        POINT_READY,
        replace(POINT_RUNNING, mission_identity=None),
        replace(POINT_RUNNING, mission_initiator="manual"),
        replace(POINT_RUNNING, mode=CleaningMode.MOP),
    ],
)
async def test_point_does_not_claim_success_for_stationary_or_unrelated_telemetry(state):
    port = Port(POINT_READY, state)
    with pytest.raises(ControlError, match="command_unconfirmed"):
        await execute_control(port, Command.POINT_CLEAN, CleaningProfile())
    assert len(port.sent) == 1 and port.statuses[-1] == "unconfirmed"


async def test_point_cannot_confirm_a_pre_existing_mission_identity():
    port = Port(replace(POINT_READY, mission_identity=MISSION_IDENTITY), POINT_RUNNING)
    with pytest.raises(ControlError, match="command_unconfirmed"):
        await execute_control(port, Command.POINT_CLEAN, CleaningProfile())
    assert len(port.sent) == 1


@pytest.mark.parametrize(
    ("state", "error"),
    [
        (BASE, "unsupported_point"),
        (replace(POINT_READY, digital_spot=DigitalSpotCapability.UNSUPPORTED), "unsupported_point"),
        (replace(POINT_READY, activity="paused", mission_active=True), "unsupported_start"),
        (POINT_RUNNING, "unsupported_start"),
        (replace(POINT_READY, activity="error"), "robot_not_ready"),
        (replace(POINT_READY, bin_present=False), "bin_missing"),
    ],
)
async def test_point_preconditions_prevent_publication(state, error):
    port = Port(state)
    with pytest.raises(ControlError, match=error):
        await execute_control(port, Command.POINT_CLEAN, CleaningProfile())
    assert not port.sent


async def test_observed_initial_vacuum_stage_does_not_claim_full_sequence():
    port = Port(BASE, replace(RUNNING, preparing_mop=True), RUNNING)
    profile = CleaningProfile(CleaningMode.VACUUM_THEN_MOP)
    await execute_control(port, Command.VACUUM, profile)
    assert port.sent == [(Command.VACUUM, profile)] and port.statuses == ["pending", "submitted"]
    assert port.now == 10 and not port.preparations


async def test_unconfirmed_native_sequence_for_regions_is_not_submitted():
    profile = CleaningProfile(CleaningMode.VACUUM_THEN_MOP)
    port = Port(BASE)
    with pytest.raises(ControlError, match="unsupported_area_mode"):
        await execute_control(port, Command.VACUUM, profile, new_mission=True)
    assert not port.sent


@pytest.mark.parametrize(
    "command,state",
    [
        (Command.VACUUM, RUNNING),
        (Command.PAUSE, PAUSED),
        (Command.CANCEL, BASE),
        (Command.DOCK, BASE),
    ],
)
async def test_already_reached_states_do_not_publish_duplicate_commands(command, state):
    port = Port(state)
    await execute_control(port, command, CleaningProfile(CleaningMode.MOP))
    assert not port.sent and port.statuses == ["confirmed"]


@pytest.mark.parametrize(
    "command,state,key",
    [
        ("start", BASE, "unsupported_command"),
        (Command.VACUUM, replace(BASE, connected=None), "robot_unavailable"),
        (Command.VACUUM, replace(BASE, connected=False), "robot_unavailable"),
        (Command.VACUUM, replace(BASE, activity="returning"), "unsupported_start"),
        (Command.VACUUM, replace(BASE, mission_active=None), "unsupported_start"),
        (Command.VACUUM, replace(BASE, ready=False), "robot_not_ready"),
        (Command.VACUUM, replace(BASE, activity="error"), "robot_not_ready"),
        (Command.VACUUM, replace(PREPARING, dock=DockSnapshot(fault=517)), "dock_not_ready"),
        (Command.RESUME, replace(PAUSED, activity="error"), "robot_not_ready"),
        (Command.VACUUM, replace(BASE, bin_present=False), "bin_missing"),
        (Command.VACUUM, replace(BASE, bin_present=False, ready=False), "bin_missing"),
        (Command.RESUME, replace(PAUSED, bin_present=False), "bin_missing"),
        (Command.VACUUM, replace(BASE, capabilities=CleaningCapabilities()), "unsupported_profile"),
        (Command.RESUME, BASE, "resume_requires_pause"),
        (Command.RESUME, replace(PAUSED, mission_active=None), "resume_requires_pause"),
        (Command.PAUSE, BASE, "pause_requires_cleaning"),
        (Command.PAUSE, PREPARING, "pause_requires_cleaning"),
        (Command.PAUSE, replace(RUNNING, mission_active=False), "pause_requires_cleaning"),
        (Command.DOCK, replace(BASE, docking=None), "unsupported_command"),
    ],
)
async def test_precondition_failures_are_local_and_do_not_publish(command, state, key):
    port = Port(state)
    with pytest.raises(ControlError) as error:
        await execute_control(port, command, CleaningProfile())
    assert error.value.key == key and not port.sent and not port.statuses


@pytest.mark.parametrize("command", [Command.VACUUM, Command.RESUME])
async def test_absent_dustbin_does_not_override_preparation_for_mop_only(command):
    mop = CleaningMode.MOP
    state = BASE if command is Command.VACUUM else PAUSED
    initial = replace(state, mode=mop, bin_present=False)
    port = Port(initial, replace(RUNNING, mode=mop))
    await execute_control(port, command, CleaningProfile(mop))
    assert [sent for sent, _ in port.sent] == [command]


@pytest.mark.parametrize(
    "plan,final",
    [
        (ControlPlan(Command.VACUUM, expected_mode=CleaningMode.MOP), RUNNING),
        (ControlPlan(Command.PAUSE), RUNNING),
        (ControlPlan(Command.CANCEL), PAUSED),
        (ControlPlan(Command.DOCK), replace(BASE, mission_active=True)),
        (ControlPlan(Command.DOCK), replace(BASE, activity="returning")),
        (ControlPlan(Command.PAUSE), replace(PAUSED, connected=False)),
    ],
)
def test_partial_or_wrong_state_is_not_confirmation(plan, final):
    assert not plan.confirms(final)


def test_unknown_resume_mode_does_not_require_an_invented_mode():
    plan = prepare_control(Command.RESUME, replace(PAUSED, mode=None), CleaningProfile())
    assert plan.confirms(replace(RUNNING, mode=None))


@pytest.mark.parametrize(
    "command,initial,deadline",
    [
        (Command.VACUUM, BASE, 40),
        (Command.DOCK, replace(BASE, activity="idle"), 120),
    ],
)
async def test_ack_only_times_out_without_retries(command, initial, deadline):
    port = Port(initial)
    with pytest.raises(ControlError, match="command_unconfirmed"):
        await execute_control(port, command, CleaningProfile())
    assert port.now == deadline and len(port.sent) == 1
    assert port.statuses == ["pending", "unconfirmed"]


async def test_disconnected_post_command_read_stops_confirmation_early():
    port = Port(BASE, replace(RUNNING, connected=False))
    with pytest.raises(ControlError):
        await execute_control(port, Command.VACUUM, CleaningProfile())
    assert port.now == 5 and len(port.sent) == 1


async def test_unloaded_port_does_not_continue_polling():
    port = Port(BASE)
    original = port.send

    async def send(command, profile):
        await original(command, profile)
        port.active = False

    port.send = send
    with pytest.raises(ControlError):
        await execute_control(port, Command.VACUUM, CleaningProfile())
    assert port.now == 0 and port.statuses[-1] == "unconfirmed"


async def test_closed_port_never_publishes():
    port = Port(BASE)
    port.active = False
    with pytest.raises(ControlError, match="not_configured"):
        await execute_control(port, Command.VACUUM, CleaningProfile())
    assert not port.sent and not port.statuses


async def test_port_closed_by_pre_command_refresh_never_publishes():
    port = Port(BASE)
    original = port.refresh

    async def refresh():
        state = await original()
        port.active = False
        return state

    port.refresh = refresh
    with pytest.raises(ControlError, match="command_unconfirmed"):
        await execute_control(port, Command.VACUUM, CleaningProfile())
    assert not port.sent and port.statuses == ["pending", "unconfirmed"]


@pytest.mark.parametrize(
    "error,expected",
    [
        (OSError(), ControlError),
        (AuthenticationError(), AuthenticationError),
        (asyncio.CancelledError(), asyncio.CancelledError),
    ],
)
async def test_publish_failures_retain_uncertainty_and_do_not_retry(error, expected):
    port = Port(BASE, send_error=error)
    with pytest.raises(expected):
        await execute_control(port, Command.VACUUM, CleaningProfile())
    assert len(port.sent) == 1 and port.statuses == ["pending", "unconfirmed"]


@pytest.mark.parametrize(
    "error,expected", [(OSError(), ControlError), (AuthenticationError(), AuthenticationError)]
)
async def test_initial_read_failure_never_publishes(error, expected):
    port = Port(read_error=error)
    with pytest.raises(expected):
        await execute_control(port, Command.VACUUM, CleaningProfile())
    assert not port.sent and not port.statuses


async def test_locate_is_submitted_without_claiming_an_audible_result():
    port = Port(replace(BASE, locate=True))
    await execute_control(port, Command.LOCATE, CleaningProfile())
    assert port.sent == [(Command.LOCATE, None)]
    assert port.statuses == ["pending", "submitted"]


async def test_exception_during_confirmation_does_not_hide_uncertainty():
    port = Port(BASE)

    async def wait(seconds):
        port.read_error = OSError()

    port.wait = wait
    with pytest.raises(ControlError):
        await execute_control(port, Command.VACUUM, CleaningProfile())
    assert port.statuses[-1] == "unconfirmed" and len(port.sent) == 1


@pytest.mark.parametrize("mode", CleaningMode)
def test_saved_preferences_round_trip_without_provider_codes(mode):
    profile = CleaningProfile(mode, 4, 3, True, False, True)
    saved = profile_preferences(profile)
    assert restore_profile(saved) == profile
    assert "operatingMode" not in saved and saved["mode"] == mode.value
    assert profile_preferences(CleaningProfile(mode)) == {"mode": mode.value}


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        "mop",
        {"mode": "unknown"},
        {"mode": []},
        {"unknown": 1},
        {"suction_level": True},
        {"wetness_level": 0},
        {"two_pass": 1},
    ],
)
def test_invalid_persisted_preferences_are_not_coerced(value):
    with pytest.raises(ValueError):
        restore_profile(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        (2, CleaningMode.VACUUM),
        (4, CleaningMode.MOP),
        (6, CleaningMode.VACUUM_MOP),
        (512, CleaningMode.VACUUM_THEN_MOP),
        (True, None),
        ("2", None),
        (0, None),
        (99, None),
    ],
)
def test_unknown_or_untyped_reported_mode_stays_unknown(value, expected):
    assert reported_cleaning_mode(value) is expected
