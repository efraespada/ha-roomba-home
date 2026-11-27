"""Robot control use case over semantic ports, independent of HA and MQTT."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from .actions import Command
from .capabilities import DigitalSpotCapability, SkipCapability, supports_point_clean
from .cleaning import CleaningCapabilities, CleaningMode, CleaningProfile
from .dock import OPERATIONS, DockSnapshot
from .errors import AuthenticationError

PREPARATION_CONFIRMATION_SECONDS = 300
COMMAND_CONFIRMATION_SECONDS = {Command.DOCK: 120, Command.REBOOT: 180}
DOCK_WASH_CONFIRMATION_SECONDS = 300
MISSION_COMMANDS = (Command.PAUSE, Command.RESUME, Command.CANCEL, Command.DOCK)


class ControlError(Exception):
    """Stable application error key; adapters provide localized presentation."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(key)


type SkipReview = tuple[tuple[int, datetime], str, tuple[str, str, str]]


@dataclass(frozen=True)
class SkipAreaEvent:
    kind: str
    identity: tuple[str, str, str]
    timestamp: int


@dataclass(frozen=True)
class SkipObservation:
    destination: SkipAreaEvent | None
    skipped: frozenset[SkipAreaEvent]
    directed: bool


@dataclass(frozen=True)
class ControlState:
    connected: bool | None
    activity: str | None
    mission_active: bool | None
    mode: CleaningMode | None
    capabilities: CleaningCapabilities
    ready: bool | None = None
    dock: DockSnapshot = field(default_factory=DockSnapshot)
    locate: bool = False
    docking: bool | None = None
    bin_present: bool | None = None
    preparing_mop: bool = False
    mission_identity: tuple[int, datetime] | None = None
    digital_spot: DigitalSpotCapability | None = None
    mission_initiator: str | None = None
    skip_capability: SkipCapability | None = None
    skip_observation: SkipObservation | None = None
    mapping_supported: bool = False
    mapping: bool = False
    pause_before_return: bool = False
    refresh_failed: bool = False


def _skip_error(state: ControlState) -> str | None:
    if state.skip_capability in (None, SkipCapability.UNSUPPORTED):
        return "unsupported_skip"
    if (
        state.activity != "cleaning"
        or state.mission_active is not True
        or state.preparing_mop
        or state.mission_identity is None
        or state.skip_observation is None
        or state.skip_observation.destination is None
        or (
            state.skip_capability is SkipCapability.DIRECTED_ONLY
            and not state.skip_observation.directed
        )
    ):
        return "skip_requires_destination"
    return None


def skip_review(state: ControlState) -> SkipReview | None:
    if state.connected is not True or _skip_error(state):
        return None
    destination = state.skip_observation.destination
    return state.mission_identity, destination.kind, destination.identity


def mission_commands(state: ControlState) -> tuple[Command, ...]:
    """Offer operations for the identified mission and robot activity."""
    activity = state.activity
    if state.connected is not True or state.mission_identity is None:
        return ()
    if state.mission_active is False and activity == "idle" and state.docking is True:
        return (Command.DOCK,)
    if state.mission_active is not True or activity not in {
        "cleaning",
        "paused",
        "returning",
        "docked",
        "error",
    }:
        return ()
    commands = []
    if activity == "cleaning" and not state.preparing_mop:
        commands.append(Command.PAUSE)
    elif activity == "paused":
        commands.append(Command.RESUME)
    commands.append(Command.CANCEL)
    if activity in {"cleaning", "paused"} and not state.preparing_mop and state.docking is True:
        commands.append(Command.DOCK)
    return tuple(commands)


def _confirmed_skip(before: ControlState, state: ControlState) -> bool:
    if state.mission_identity != before.mission_identity or state.skip_observation is None:
        return False
    previous = before.skip_observation
    target = previous.destination
    return any(
        area.kind == target.kind
        and area.identity == target.identity
        and area.timestamp >= target.timestamp
        for area in state.skip_observation.skipped - previous.skipped
    )


@dataclass(frozen=True)
class ControlPlan:
    command: Command
    profile: CleaningProfile | None = None
    expected_mode: CleaningMode | None = None
    already_confirmed: bool = False
    previous_component_state: int | None = None
    expected_modes: frozenset[CleaningMode] = frozenset()
    mapping: bool = False

    def _matches_cleaning(self, state: ControlState) -> bool:
        if state.activity != "cleaning" or state.mission_active is not True or state.mapping:
            return False
        if self.expected_modes:
            return state.mode in self.expected_modes
        return self.expected_mode is None or state.mode is self.expected_mode

    def observes_preparation(self, state: ControlState) -> bool:
        return (
            self.command in {Command.VACUUM, Command.RESUME}
            and state.preparing_mop
            and state.mode is not None
            and state.mode.mops
            and self._matches_cleaning(state)
        )

    def observes_area_sequence(self, before: ControlState, state: ControlState) -> bool:
        return (
            state.mission_identity is not None
            and state.mission_identity != before.mission_identity
            and state.mission_initiator == "rmtApp"
            and state.activity == "cleaning"
            and state.mission_active is True
            and not state.preparing_mop
            and state.mode in self.expected_modes | {CleaningMode.VACUUM, CleaningMode.MOP}
        )

    def observes_return_wash(self, before: ControlState, state: ControlState) -> bool:
        return (
            self.command is Command.DOCK
            and not before.preparing_mop
            and before.mission_identity is not None
            and state.mission_identity == before.mission_identity
            and state.preparing_mop
            and state.dock.pad_wash in OPERATIONS[Command.WASH_MOP].running_states
            and not state.dock.wet_cleaning_blocked
        )

    def confirms(self, state: ControlState) -> bool:
        if state.connected is not True:
            return False
        if operation := OPERATIONS.get(self.command):
            current = state.dock.status(operation)
            return current != self.previous_component_state and current in operation.result_states
        if self.command is Command.START_MAPPING or self.mapping:
            return state.mapping and state.activity == "cleaning" and state.mission_active is True
        if self.command in {Command.VACUUM, Command.RESUME}:
            return not state.preparing_mop and self._matches_cleaning(state)
        if self.command is Command.PAUSE:
            return state.activity == "paused" and state.mission_active is True
        if self.command is Command.CANCEL:
            return state.activity in {"idle", "docked"} and state.mission_active is False
        return (
            self.command is Command.DOCK
            and state.activity == "docked"
            and state.mission_active is False
        )


@dataclass(frozen=True)
class PreparationConfirmation:
    plan: ControlPlan
    mission_identity: tuple[int, datetime] | None
    expires_at: float

    def result(self, state: ControlState | None, now: float) -> str | None:
        if now >= self.expires_at:
            return "unconfirmed"
        if state is None or state.connected is not True:
            return None
        if (
            state.activity == "error"
            or state.mission_active is False
            or state.dock.wet_cleaning_blocked
        ):
            return "unconfirmed"
        if self.mission_identity is None or state.mission_identity is None:
            return None
        if state.mission_identity != self.mission_identity:
            return "unconfirmed"
        return "confirmed" if self.plan.confirms(state) else None


def _check_mop_readiness(dock: DockSnapshot) -> None:
    if dock.pad_attached is False or dock.tank_present is False:
        raise ControlError("mop_not_ready")
    if dock.wet_cleaning_blocked:
        raise ControlError("dock_not_ready")


def prepare_control(
    command: Command,
    state: ControlState,
    profile: CleaningProfile,
    *,
    new_mission: bool = False,
    area_profiles: tuple[CleaningProfile, ...] = (),
) -> ControlPlan:
    if not isinstance(command, Command):
        raise ControlError("unsupported_command")
    if state.connected is not True:
        raise ControlError("robot_unavailable")
    if command is Command.DOCK and state.docking is not True:
        raise ControlError("unsupported_command")
    if command is Command.LOCATE:
        if not state.locate:
            raise ControlError("unsupported_command")
        return ControlPlan(command)
    if command is Command.SKIP:
        if error := _skip_error(state):
            raise ControlError(error)
        return ControlPlan(command)
    if command is Command.START_MAPPING:
        if not state.mapping_supported:
            raise ControlError("mapping_unsupported")
        if state.activity != "docked" or state.mission_active is not False:
            raise ControlError("mapping_requires_dock")
        if state.ready is False:
            raise ControlError("robot_not_ready")
        return ControlPlan(command)
    if (
        command in {Command.VACUUM, Command.POINT_CLEAN, Command.RESUME}
        and state.activity == "error"
    ):
        raise ControlError("robot_not_ready")
    if operation := OPERATIONS.get(command):
        if not state.dock.supports(operation):
            raise ControlError("unsupported_dock_action")
        status = state.dock.status(operation)
        if status in operation.running_states:
            return ControlPlan(command, already_confirmed=True)
        if command is Command.EMPTY_BIN and state.bin_present is False:
            raise ControlError("bin_missing")
        at_rest = state.activity == "docked" and state.mission_active is False
        if (not at_rest and command is not Command.STOP_DRYING) or not state.dock.allows(
            command, operation
        ):
            raise ControlError("dock_not_ready")
        return ControlPlan(command, previous_component_state=status)
    if command is Command.POINT_CLEAN:
        if not supports_point_clean(state.digital_spot):
            raise ControlError("unsupported_point")
        new_mission = True
    if command in {Command.VACUUM, Command.POINT_CLEAN}:
        if not new_mission and state.activity == "paused" and state.mission_active is True:
            return prepare_control(Command.RESUME, state, profile)
        if state.mapping:
            raise ControlError("mapping_in_progress")
        if not new_mission and state.activity == "cleaning" and state.mission_active is True:
            # A next-mission preference never replaces an active mission.
            if state.preparing_mop:
                _check_mop_readiness(state.dock)
            return ControlPlan(command, expected_mode=state.mode, already_confirmed=True)
        if state.activity not in {"idle", "docked"} or state.mission_active is not False:
            raise ControlError("unsupported_start")
        profiles = area_profiles or (profile,)
        modes = frozenset(value.mode for value in profiles)
        try:
            for selection in profiles:
                selection.validate(state.capabilities)
        except ValueError:
            raise ControlError("unsupported_profile") from None
        if state.bin_present is False and any(mode.vacuums for mode in modes):
            raise ControlError("bin_missing")
        if any(mode.mops for mode in modes):
            _check_mop_readiness(state.dock)
        if state.ready is False:
            raise ControlError("robot_not_ready")
        if command is Command.POINT_CLEAN and profile.mode is CleaningMode.VACUUM_THEN_MOP:
            modes |= {CleaningMode.VACUUM, CleaningMode.MOP}
        return ControlPlan(command, profile, profile.mode, expected_modes=modes)
    if command is Command.RESUME:
        if state.activity != "paused" or state.mission_active is not True:
            raise ControlError("resume_requires_pause")
        if state.mapping:
            return ControlPlan(command, mapping=True)
        if state.mode is not None:
            if state.bin_present is False and state.mode.vacuums:
                raise ControlError("bin_missing")
            if state.mode.mops:
                _check_mop_readiness(state.dock)
        return ControlPlan(command, expected_mode=state.mode)
    plan = ControlPlan(command)
    if plan.confirms(state):
        return ControlPlan(command, already_confirmed=True)
    if command is Command.PAUSE and (
        state.activity != "cleaning" or state.mission_active is not True or state.preparing_mop
    ):
        raise ControlError("pause_requires_cleaning")
    return plan


class ControlPort(Protocol):
    """A bound robot, supplied by composition; no provider DTO crosses this port."""

    @property
    def active(self) -> bool: ...

    async def refresh(self) -> ControlState: ...

    async def send(self, command: Command, profile: CleaningProfile | None) -> None: ...

    def report(self, status: str) -> None: ...

    def defer_preparation(self, plan: ControlPlan, state: ControlState) -> None: ...

    async def wait(self, seconds: float) -> None: ...

    def clock(self) -> float: ...


async def _pause_for_return(
    port: ControlPort, before: ControlState, plan: ControlPlan
) -> ControlState:
    if before.mission_identity is None:
        raise ControlError("command_unconfirmed")
    pause = ControlPlan(Command.PAUSE)
    await port.send(pause.command, None)
    deadline = port.clock() + 40
    while port.active and port.clock() < deadline:
        await port.wait(5)
        state = await port.refresh()
        if state.refresh_failed or state.connected is False:
            break
        if state.connected is None:
            continue
        if plan.confirms(state) or state.activity == "returning":
            return state
        if state.mission_identity != before.mission_identity:
            break
        # A short cleaning area can finish while the pause is in flight.
        if state.docking is True and (
            pause.confirms(state) or (state.activity == "idle" and state.mission_active is False)
        ):
            return state
        if state.activity != "cleaning":
            break
    raise ControlError("command_unconfirmed")


async def execute_control(
    port: ControlPort,
    command: Command,
    profile: CleaningProfile,
    *,
    new_mission: bool = False,
    area_profiles: tuple[CleaningProfile, ...] = (),
    reviewed_skip: SkipReview | None = None,
    reviewed_mission: tuple[int, datetime] | None = None,
) -> None:
    """Validate each command step and confirm the result with robot state."""
    if not port.active:
        raise ControlError("not_configured")
    try:
        before = await port.refresh()
    except AuthenticationError:
        raise
    except Exception:
        raise ControlError("robot_unavailable") from None
    if reviewed_mission is not None and (
        before.mission_identity != reviewed_mission or command not in mission_commands(before)
    ):
        raise ControlError("mission_changed")
    plan = prepare_control(
        command, before, profile, new_mission=new_mission, area_profiles=area_profiles
    )
    if (
        command is Command.SKIP
        and reviewed_skip is not None
        and skip_review(before) != reviewed_skip
    ):
        raise ControlError("skip_destination_changed")
    if plan.already_confirmed:
        if plan.command is Command.VACUUM and before.preparing_mop:
            port.defer_preparation(plan, before)
        else:
            port.report("confirmed")
        return
    port.report("pending")
    try:
        if not port.active:
            raise ControlError("command_unconfirmed")
        if (
            plan.command is Command.DOCK
            and before.pause_before_return
            and before.activity == "cleaning"
            and before.mission_active is True
            and not before.preparing_mop
            and not before.mapping
        ):
            state = await _pause_for_return(port, before, plan)
            if not port.active:
                raise ControlError("command_unconfirmed")
            if plan.confirms(state):
                port.report("confirmed")
                return
            if state.activity in {"paused", "idle"}:
                await port.send(plan.command, plan.profile)
        else:
            await port.send(plan.command, plan.profile)
        if plan.command is Command.LOCATE:
            port.report("submitted")
            return
        deadline = port.clock() + COMMAND_CONFIRMATION_SECONDS.get(plan.command, 40)
        disconnected = False
        return_wash_observed = False
        while port.active and port.clock() < deadline:
            await port.wait(5)
            state = await port.refresh()
            if plan.command is Command.REBOOT:
                if state.connected is True and disconnected:
                    port.report("confirmed")
                    return
                disconnected |= state.connected is False
                continue
            if state.refresh_failed or state.connected is False:
                break
            if state.connected is None:
                continue
            if (
                reviewed_mission is not None
                and state.mission_active is True
                and state.mission_identity != reviewed_mission
            ):
                break
            if plan.command is Command.SKIP:
                if _confirmed_skip(before, state):
                    port.report("confirmed")
                    return
                continue
            if plan.command is Command.START_MAPPING and state.mission_initiator != "rmtApp":
                continue
            if plan.command is Command.POINT_CLEAN:
                if profile.mode.mops and state.dock.wet_cleaning_blocked:
                    raise ControlError("dock_not_ready")
                # Live state describes a regular cleaning mission. Its exact target
                # is only visible in mission history when the run ends.
                if (
                    plan._matches_cleaning(state)
                    and state.mission_initiator == "rmtApp"
                    and state.mission_identity is not None
                    and state.mission_identity != before.mission_identity
                ):
                    port.report("submitted")
                    return
                continue
            if (
                new_mission
                and plan.command is Command.VACUUM
                and CleaningMode.VACUUM_THEN_MOP in plan.expected_modes
            ):
                if plan.observes_area_sequence(before, state):
                    port.report("submitted")
                    return
                continue
            if plan.confirms(state):
                port.report("confirmed")
                return
            if return_wash_observed:
                if (
                    state.activity == "error"
                    or state.dock.wet_cleaning_blocked
                    or state.mission_identity not in (None, before.mission_identity)
                ):
                    break
            elif plan.observes_return_wash(before, state):
                return_wash_observed = True
                deadline = port.clock() + DOCK_WASH_CONFIRMATION_SECONDS
            if plan.observes_preparation(state):
                if state.dock.wet_cleaning_blocked:
                    break
                port.defer_preparation(plan, state)
                return
            if (
                plan.command is Command.VACUUM
                and plan.expected_mode is CleaningMode.VACUUM_THEN_MOP
                and state.mode is CleaningMode.VACUUM
                and state.activity == "cleaning"
                and state.mission_active is True
                and not state.preparing_mop
            ):
                port.report("submitted")
                return
        raise ControlError("command_unconfirmed")
    except AuthenticationError, asyncio.CancelledError, ControlError:
        port.report("unconfirmed")
        raise
    except Exception:
        port.report("unconfirmed")
        raise ControlError("command_unconfirmed") from None
