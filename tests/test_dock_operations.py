"""The native operations use capability and activity checks before sending."""

from dataclasses import replace

import pytest

from custom_components.roomba_home.core.actions import Command
from custom_components.roomba_home.core.application import (
    ControlError,
    ControlState,
    prepare_control,
)
from custom_components.roomba_home.core.capabilities import DockCapabilities
from custom_components.roomba_home.core.cleaning import (
    CleaningCapabilities,
    CleaningMode,
    CleaningProfile,
)
from custom_components.roomba_home.core.dock import OPERATIONS, DockSnapshot

CAPS = DockCapabilities(True, True, True, True, True, True)
DOCK = DockSnapshot(CAPS, 301, 401, 601, 701, 0, True, True)
PROFILE = CleaningProfile()
DOCKED = ControlState(True, "docked", False, None, CleaningCapabilities(), dock=DOCK)


@pytest.mark.parametrize(
    "command,component,ready,result",
    [
        (Command.EMPTY_BIN, "evacuation", 301, 302),
        (Command.REFILL, "refill", 401, 403),
        (Command.WASH_MOP, "pad_wash", 601, 602),
        (Command.DRY_MOP, "pad_dry", 701, 702),
        (Command.STOP_DRYING, "pad_dry", 702, 706),
    ],
)
def test_each_dock_command_requires_its_own_post_command_transition(
    command, component, ready, result
):
    initial = replace(DOCKED, dock=replace(DOCK, **{component: ready}))
    plan = prepare_control(command, initial, PROFILE)
    assert not plan.already_confirmed and plan.profile is None
    assert not plan.confirms(initial)
    assert plan.confirms(replace(initial, dock=replace(initial.dock, **{component: result})))


@pytest.mark.parametrize(
    "state,key",
    [
        (
            replace(DOCKED, dock=replace(DOCK, capabilities=DockCapabilities())),
            "unsupported_dock_action",
        ),
        (replace(DOCKED, activity="idle"), "dock_not_ready"),
        (replace(DOCKED, mission_active=True), "dock_not_ready"),
        (replace(DOCKED, dock=replace(DOCK, fault=517)), "dock_not_ready"),
        (replace(DOCKED, dock=replace(DOCK, pad_attached=False)), "dock_not_ready"),
        (replace(DOCKED, dock=replace(DOCK, pad_wash=None)), "dock_not_ready"),
        (replace(DOCKED, dock=replace(DOCK, evacuation=302)), "dock_not_ready"),
        (replace(DOCKED, dock=replace(DOCK, pad_dry=707)), "dock_not_ready"),
    ],
)
def test_wash_is_blocked_when_the_dock_is_busy_or_not_ready(state, key):
    with pytest.raises(ControlError, match=key):
        prepare_control(Command.WASH_MOP, state, PROFILE)


def test_ongoing_wash_is_already_confirmed_without_a_second_start():
    running = replace(DOCKED, dock=replace(DOCK, pad_wash=602))
    assert prepare_control(Command.WASH_MOP, running, PROFILE).already_confirmed


def test_empty_bin_requires_the_dustbin_to_be_installed():
    with pytest.raises(ControlError, match="bin_missing"):
        prepare_control(Command.EMPTY_BIN, replace(DOCKED, bin_present=False), PROFILE)


def test_automatic_refill_only_dock_does_not_offer_manual_command():
    automatic = replace(DOCKED, dock=replace(DOCK, capabilities=replace(CAPS, manual_refill=False)))
    with pytest.raises(ControlError, match="unsupported_dock_action"):
        prepare_control(Command.REFILL, automatic, PROFILE)
    assert not DOCK.allows(Command.REFILL, OPERATIONS[Command.STOP_DRYING])
    with pytest.raises(ControlError, match="dock_not_ready"):
        prepare_control(
            Command.REFILL, replace(DOCKED, dock=replace(DOCK, tank_present=False)), PROFILE
        )


def test_mop_start_is_rejected_while_a_dock_fault_is_reported():
    modes = CleaningCapabilities(frozenset({CleaningMode.MOP}))
    state = replace(DOCKED, capabilities=modes, dock=replace(DOCK, fault=517))
    with pytest.raises(ControlError, match="dock_not_ready"):
        prepare_control(Command.VACUUM, state, CleaningProfile(CleaningMode.MOP))


def test_resume_of_paused_mop_is_also_blocked_during_a_dock_fault():
    state = replace(
        DOCKED,
        activity="paused",
        mission_active=True,
        mode=CleaningMode.MOP,
        dock=replace(DOCK, fault=517),
    )
    with pytest.raises(ControlError, match="dock_not_ready"):
        prepare_control(Command.VACUUM, state, PROFILE)


@pytest.mark.parametrize("command", [Command.VACUUM, Command.RESUME])
@pytest.mark.parametrize(
    "changed,key",
    [
        ({"pad_attached": False}, "mop_not_ready"),
        ({"tank_present": False}, "mop_not_ready"),
        ({"pad_wash": 654}, "dock_not_ready"),
        ({"refill": 451}, "dock_not_ready"),
        ({"pad_wash": None, "refill": 670}, "dock_not_ready"),
        ({"pad_dry": 707}, "dock_not_ready"),
    ],
)
def test_wet_missions_require_installed_equipment_and_no_water_system_fault(command, changed, key):
    mode = CleaningMode.VACUUM_MOP
    state = replace(
        DOCKED,
        capabilities=CleaningCapabilities(frozenset(CleaningMode)),
        dock=replace(DOCK, **changed),
        mode=mode,
    )
    if command is Command.RESUME:
        state = replace(state, activity="paused", mission_active=True)
    with pytest.raises(ControlError, match=key):
        prepare_control(command, state, CleaningProfile(mode))
    assert (
        prepare_control(command, replace(state, mode=CleaningMode.VACUUM), PROFILE).command
        is command
    )


def test_mixed_region_mission_checks_every_selected_mode_for_wet_readiness():
    state = replace(
        DOCKED,
        capabilities=CleaningCapabilities(frozenset(CleaningMode)),
        dock=replace(DOCK, pad_wash=654),
    )
    with pytest.raises(ControlError, match="dock_not_ready"):
        prepare_control(
            Command.VACUUM,
            state,
            PROFILE,
            new_mission=True,
            area_profiles=(PROFILE, CleaningProfile(CleaningMode.MOP)),
        )


def test_missing_telemetry_and_component_faults_unrelated_to_water_are_not_mop_faults():
    mode = CleaningMode.MOP
    state = replace(
        DOCKED,
        capabilities=CleaningCapabilities(frozenset({mode})),
        dock=DockSnapshot(evacuation=353, pad_dry=750),
    )
    assert prepare_control(Command.VACUUM, state, CleaningProfile(mode)).expected_mode is mode


def test_stale_states_for_unsupported_components_cannot_block_supported_actions():
    dock = replace(
        DOCK,
        capabilities=replace(CAPS, refill=False, wash=False, dry=False),
        refill=451,
        pad_wash=654,
        pad_dry=707,
    )
    state = replace(
        DOCKED, capabilities=CleaningCapabilities(frozenset({CleaningMode.MOP})), dock=dock
    )
    assert prepare_control(Command.VACUUM, state, CleaningProfile(CleaningMode.MOP))
    assert prepare_control(Command.EMPTY_BIN, state, PROFILE)


def test_drying_can_be_stopped_while_dock_reports_an_active_cycle():
    state = replace(DOCKED, mission_active=True, dock=replace(DOCK, pad_dry=702, fault=517))
    assert prepare_control(Command.STOP_DRYING, state, PROFILE).command is Command.STOP_DRYING


def test_locate_requires_capability_evidence():
    with pytest.raises(ControlError, match="unsupported_command"):
        prepare_control(Command.LOCATE, DOCKED, PROFILE)
    plan = prepare_control(Command.LOCATE, replace(DOCKED, locate=True), PROFILE)
    assert not plan.already_confirmed
