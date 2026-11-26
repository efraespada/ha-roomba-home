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
    SkipAreaEvent,
    SkipObservation,
    execute_control,
    prepare_control,
    skip_review,
)
from custom_components.roomba_home.core.capabilities import DigitalSpotCapability, SkipCapability
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


async def test_reboot_confirms_only_after_the_robot_disconnects_and_returns():
    unknown = replace(BASE, connected=None)
    offline = replace(BASE, connected=False)
    port = Port(BASE, unknown, BASE, offline, unknown, BASE)
    await execute_control(port, Command.REBOOT, CleaningProfile())
    assert port.sent == [(Command.REBOOT, None)]
    assert port.statuses == ["pending", "confirmed"]
    assert port.now == 25


@pytest.mark.parametrize("connected", [True, False, None])
async def test_reboot_timeout_does_not_resend_or_assume_a_restart(connected):
    port = Port(BASE, replace(BASE, connected=connected))
    with pytest.raises(ControlError, match="command_unconfirmed"):
        await execute_control(port, Command.REBOOT, CleaningProfile())
    assert port.sent == [(Command.REBOOT, None)]
    assert port.statuses == ["pending", "unconfirmed"]
    assert port.now == 180


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"mapping_supported": False}, "mapping_unsupported"),
        ({"activity": "idle"}, "mapping_requires_dock"),
        ({"mission_active": True}, "mapping_requires_dock"),
        ({"ready": False}, "robot_not_ready"),
    ],
)
async def test_mapping_starts_only_on_a_ready_supported_dock(changes, reason):
    base = replace(BASE, mapping_supported=True)
    port = Port(replace(base, **changes))
    with pytest.raises(ControlError, match=reason):
        await execute_control(port, Command.START_MAPPING, CleaningProfile())
    assert not port.sent


async def test_mapping_ignores_cleaning_or_local_training_when_confirming_the_start():
    base = replace(BASE, mapping_supported=True)
    cleaning = replace(RUNNING, mission_initiator="rmtApp")
    local = replace(RUNNING, mission_initiator="manual", mapping=True)
    remote = replace(local, mission_initiator="rmtApp")
    port = Port(base, cleaning, local, remote)
    await execute_control(port, Command.START_MAPPING, CleaningProfile(CleaningMode.MOP))
    assert port.sent == [(Command.START_MAPPING, None)]
    assert port.statuses == ["pending", "confirmed"]
    assert port.now == 15


async def test_mapping_resume_ignores_cleaning_mode_and_does_not_restart_the_run():
    paused = replace(PAUSED, mapping=True, mode=CleaningMode.MOP, dock=DockSnapshot(fault=517))
    mapping = replace(paused, activity="cleaning")
    port = Port(paused, RUNNING, mapping)
    await execute_control(port, Command.VACUUM, CleaningProfile())
    assert port.sent == [(Command.RESUME, None)]
    assert port.statuses == ["pending", "confirmed"]
    assert port.now == 10
    with pytest.raises(ControlError, match="mapping_in_progress"):
        prepare_control(Command.VACUUM, mapping, CleaningProfile())


@pytest.mark.parametrize("change", [{"activity": "paused"}, {"mission_active": False}])
def test_only_a_running_training_cycle_confirms_mapping(change):
    plan = ControlPlan(Command.START_MAPPING)
    state = replace(RUNNING, mapping=True)
    assert plan.confirms(state)
    assert not plan.confirms(replace(state, **change))
    assert not ControlPlan(Command.VACUUM).confirms(state)


DESTINATION = SkipAreaEvent("room", ("map", "revision", "room-a"), 120)
SKIPPING = replace(
    RUNNING,
    mission_identity=MISSION_IDENTITY,
    skip_capability=SkipCapability.CURRENT_AREA,
    skip_observation=SkipObservation(DESTINATION, frozenset(), True),
)


@pytest.mark.parametrize(
    ("changes", "key"),
    [
        ({"connected": False}, "robot_unavailable"),
        ({"skip_capability": None}, "unsupported_skip"),
        ({"skip_capability": SkipCapability.UNSUPPORTED}, "unsupported_skip"),
        ({"activity": "paused"}, "skip_requires_destination"),
        ({"mission_active": False}, "skip_requires_destination"),
        ({"preparing_mop": True}, "skip_requires_destination"),
        ({"mission_identity": None}, "skip_requires_destination"),
        ({"skip_observation": None}, "skip_requires_destination"),
        (
            {"skip_observation": SkipObservation(None, frozenset(), True)},
            "skip_requires_destination",
        ),
        (
            {
                "skip_capability": SkipCapability.DIRECTED_ONLY,
                "skip_observation": SkipObservation(DESTINATION, frozenset(), False),
            },
            "skip_requires_destination",
        ),
    ],
)
async def test_skip_requires_advertised_support_and_a_current_destination(changes, key):
    state = replace(SKIPPING, **changes)
    assert skip_review(state) is None
    port = Port(state)
    with pytest.raises(ControlError, match=key):
        await execute_control(port, Command.SKIP, CleaningProfile())
    assert port.sent == []


async def test_skip_confirms_only_a_new_matching_result_in_the_same_mission():
    matching = replace(DESTINATION, timestamp=130)
    previous = DESTINATION
    state = replace(
        SKIPPING,
        skip_capability=SkipCapability.DIRECTED_ONLY,
        skip_observation=SkipObservation(DESTINATION, frozenset({previous}), True),
    )
    unconfirmed = [
        replace(state, mission_identity=(11, MISSION_IDENTITY[1])),
        replace(state, skip_observation=None),
        replace(
            state,
            skip_observation=SkipObservation(
                None,
                frozenset(
                    {
                        replace(matching, kind="zone"),
                        replace(matching, identity=("map", "revision", "room-b")),
                        replace(matching, timestamp=119),
                        previous,
                    }
                ),
                True,
            ),
        ),
    ]
    result = replace(state, skip_observation=SkipObservation(None, frozenset({matching}), True))
    port = Port(state, *unconfirmed, result)
    await execute_control(port, Command.SKIP, CleaningProfile(), reviewed_skip=skip_review(state))
    assert port.sent == [(Command.SKIP, None)]
    assert port.statuses == ["pending", "confirmed"] and port.now == 20
    assert not ControlPlan(Command.SKIP).confirms(BASE)


async def test_skip_rejects_changed_review_and_times_out_without_republishing():
    port = Port(SKIPPING)
    with pytest.raises(ControlError, match="skip_destination_changed"):
        await execute_control(
            port,
            Command.SKIP,
            CleaningProfile(),
            reviewed_skip=(MISSION_IDENTITY, "room", ("old", "r", "room")),
        )
    assert not port.sent
    with pytest.raises(ControlError, match="command_unconfirmed"):
        await execute_control(port, Command.SKIP, CleaningProfile())
    assert port.sent == [(Command.SKIP, None)]
    assert port.statuses == ["pending", "unconfirmed"]


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


RETURN_RUNNING = replace(RUNNING, pause_before_return=True, mission_identity=MISSION_IDENTITY)
RETURN_PAUSED = replace(RETURN_RUNNING, activity="paused")
RETURN_TRAVEL = replace(RETURN_RUNNING, activity="returning")


async def test_return_waits_for_pause_and_reports_success_only_at_the_dock():
    port = Port(RETURN_RUNNING, RETURN_RUNNING, RETURN_PAUSED, RETURN_TRAVEL, BASE)
    await execute_control(port, Command.DOCK, CleaningProfile())
    assert port.sent == [(Command.PAUSE, None), (Command.DOCK, None)]
    assert port.statuses == ["pending", "confirmed"]
    assert port.now == 20


async def test_return_docks_if_the_same_cleaning_mission_ends_while_pausing():
    ended = replace(RETURN_RUNNING, activity="idle", mission_active=False)
    port = Port(RETURN_RUNNING, ended, RETURN_TRAVEL, BASE)
    await execute_control(port, Command.DOCK, CleaningProfile())
    assert port.sent == [(Command.PAUSE, None), (Command.DOCK, None)]
    assert port.statuses == ["pending", "confirmed"]


@pytest.mark.parametrize(
    "initial",
    [
        RETURN_PAUSED,
        replace(RETURN_RUNNING, pause_before_return=False),
        replace(RETURN_RUNNING, mapping=True),
        replace(RETURN_RUNNING, preparing_mop=True),
        replace(RETURN_RUNNING, mission_active=None),
    ],
)
async def test_return_sends_only_dock_outside_the_verified_running_cleaning_state(initial):
    port = Port(initial, BASE)
    await execute_control(port, Command.DOCK, CleaningProfile())
    assert port.sent == [(Command.DOCK, None)]


@pytest.mark.parametrize("intermediate", [RETURN_TRAVEL, BASE])
async def test_return_observes_arrival_if_the_robot_starts_docking_on_its_own(intermediate):
    port = Port(RETURN_RUNNING, intermediate, BASE)
    await execute_control(port, Command.DOCK, CleaningProfile())
    assert port.sent == [(Command.PAUSE, None)]
    assert port.statuses == ["pending", "confirmed"]


@pytest.mark.parametrize(
    "intermediate",
    [
        RETURN_RUNNING,
        replace(RETURN_PAUSED, connected=False),
        replace(RETURN_PAUSED, mission_identity=None),
        replace(RETURN_PAUSED, mission_identity=(11, MISSION_IDENTITY[1])),
        replace(RETURN_PAUSED, activity="idle", mission_active=True),
        replace(RETURN_PAUSED, activity="idle", mission_active=False, mission_identity=None),
        replace(RETURN_PAUSED, docking=None),
        replace(RETURN_RUNNING, activity="error"),
    ],
)
async def test_return_never_sends_dock_until_the_same_mission_is_paused(intermediate):
    port = Port(RETURN_RUNNING, intermediate)
    with pytest.raises(ControlError, match="command_unconfirmed"):
        await execute_control(port, Command.DOCK, CleaningProfile())
    assert port.sent == [(Command.PAUSE, None)]
    assert port.statuses == ["pending", "unconfirmed"]


async def test_return_leaves_an_unidentified_cleaning_mission_alone():
    port = Port(replace(RETURN_RUNNING, mission_identity=None))
    with pytest.raises(ControlError, match="command_unconfirmed"):
        await execute_control(port, Command.DOCK, CleaningProfile())
    assert not port.sent
    assert port.statuses == ["pending", "unconfirmed"]


async def test_return_does_not_send_dock_if_the_integration_unloads_after_pause():
    class ClosingPort(Port):
        async def refresh(self):
            state = await super().refresh()
            if state is RETURN_PAUSED:
                self.active = False
            return state

    port = ClosingPort(RETURN_RUNNING, RETURN_PAUSED)
    with pytest.raises(ControlError, match="command_unconfirmed"):
        await execute_control(port, Command.DOCK, CleaningProfile())
    assert port.sent == [(Command.PAUSE, None)]
    assert port.statuses == ["pending", "unconfirmed"]


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


async def test_wet_point_submission_identifies_pad_preparation_without_claiming_success():
    profile = CleaningProfile(CleaningMode.MOP)
    ready = replace(POINT_READY, bin_present=False)
    preparing = replace(POINT_RUNNING, mode=profile.mode, preparing_mop=True)
    port = Port(ready, preparing)
    await execute_control(port, Command.POINT_CLEAN, profile)
    assert port.sent == [(Command.POINT_CLEAN, profile)]
    assert port.statuses == ["pending", "submitted"]
    assert not port.preparations


@pytest.mark.parametrize(
    ("dock", "error"),
    [
        (DockSnapshot(pad_attached=False), "mop_not_ready"),
        (DockSnapshot(tank_present=False), "mop_not_ready"),
        (DockSnapshot(fault=517), "dock_not_ready"),
    ],
)
async def test_wet_point_requires_the_mop_and_a_ready_dock(dock, error):
    port = Port(replace(POINT_READY, dock=dock))
    with pytest.raises(ControlError, match=error):
        await execute_control(port, Command.POINT_CLEAN, CleaningProfile(CleaningMode.MOP))
    assert not port.sent


async def test_observed_initial_vacuum_stage_does_not_claim_full_sequence():
    port = Port(BASE, replace(RUNNING, preparing_mop=True), RUNNING)
    profile = CleaningProfile(CleaningMode.VACUUM_THEN_MOP)
    await execute_control(port, Command.VACUUM, profile)
    assert port.sent == [(Command.VACUUM, profile)] and port.statuses == ["pending", "submitted"]
    assert port.now == 10 and not port.preparations


async def test_mop_point_reports_a_dock_fault_that_appears_after_dispatch():
    profile = CleaningProfile(CleaningMode.MOP)
    dock_fault = replace(POINT_READY, mode=profile.mode, dock=DockSnapshot(pad_wash=654))
    port = Port(POINT_READY, dock_fault)
    with pytest.raises(ControlError, match="dock_not_ready"):
        await execute_control(port, Command.POINT_CLEAN, profile)
    assert port.sent == [(Command.POINT_CLEAN, profile)]
    assert port.statuses == ["pending", "unconfirmed"]


@pytest.mark.parametrize("active_mode", [CleaningMode.VACUUM, CleaningMode.MOP])
async def test_sequential_point_submission_waits_for_a_new_mission_in_either_phase(active_mode):
    profile = CleaningProfile(CleaningMode.VACUUM_THEN_MOP)
    unrelated = replace(POINT_RUNNING, mode=active_mode, mission_initiator="cloud")
    active = replace(POINT_RUNNING, mode=active_mode)
    port = Port(POINT_READY, unrelated, active)
    await execute_control(port, Command.POINT_CLEAN, profile)
    assert port.sent == [(Command.POINT_CLEAN, profile)]
    assert port.statuses == ["pending", "submitted"]
    assert port.now == 10


@pytest.mark.parametrize(
    "change",
    [
        {"mission_identity": None},
        {"mission_identity": MISSION_IDENTITY},
        {"mission_initiator": "cloud"},
        {"activity": "returning"},
        {"mission_active": False},
        {"preparing_mop": True},
        {"mode": CleaningMode.VACUUM_MOP},
    ],
)
async def test_directed_sequence_does_not_claim_an_unrelated_or_inactive_mission(change):
    initial = replace(BASE, mission_identity=MISSION_IDENTITY)
    candidate = replace(
        RUNNING, mission_identity=(11, MISSION_IDENTITY[1]), mission_initiator="rmtApp"
    )
    profile = CleaningProfile(CleaningMode.VACUUM_THEN_MOP)
    port = Port(initial, replace(candidate, **change))
    with pytest.raises(ControlError, match="command_unconfirmed"):
        await execute_control(port, Command.VACUUM, profile, new_mission=True)
    assert port.sent == [(Command.VACUUM, profile)]
    assert port.statuses == ["pending", "unconfirmed"]


async def test_mixed_target_reports_start_without_claiming_that_it_finished_both_phases():
    first = CleaningProfile(CleaningMode.VACUUM)
    sequential = CleaningProfile(CleaningMode.VACUUM_THEN_MOP)
    running = replace(RUNNING, mission_identity=MISSION_IDENTITY, mission_initiator="rmtApp")
    port = Port(BASE, running)
    await execute_control(
        port, Command.VACUUM, first, new_mission=True, area_profiles=(first, sequential)
    )
    assert port.sent == [(Command.VACUUM, first)]
    assert port.statuses == ["pending", "submitted"]


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
