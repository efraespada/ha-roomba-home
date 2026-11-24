"""Robot control use case over semantic ports, independent of HA and MQTT."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from .actions import Command
from .capabilities import DigitalSpotCapability, supports_point_clean
from .cleaning import CleaningCapabilities, CleaningMode, CleaningProfile
from .dock import OPERATIONS, DockSnapshot
from .errors import AuthenticationError

PREPARATION_CONFIRMATION_SECONDS = 300


class ControlError(Exception):
    """Stable application error key; adapters provide localized presentation."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(key)


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


@dataclass(frozen=True)
class ControlPlan:
    command: Command
    profile: CleaningProfile | None = None
    expected_mode: CleaningMode | None = None
    already_confirmed: bool = False
    previous_component_state: int | None = None
    expected_modes: frozenset[CleaningMode] = frozenset()

    def _matches_cleaning(self, state: ControlState) -> bool:
        if state.activity != "cleaning" or state.mission_active is not True:
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

    def confirms(self, state: ControlState) -> bool:
        if state.connected is not True:
            return False
        if operation := OPERATIONS.get(self.command):
            current = state.dock.status(operation)
            return current != self.previous_component_state and current in operation.result_states
        if self.command in {Command.VACUUM, Command.RESUME}:
            return not state.preparing_mop and self._matches_cleaning(state)
        if self.command is Command.PAUSE:
            return state.activity == "paused" and state.mission_active is True
        if self.command is Command.CANCEL:
            return state.activity in {"idle", "docked"} and state.mission_active is False
        return state.activity == "docked" and state.mission_active is False


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
        if not new_mission and state.activity == "cleaning" and state.mission_active is True:
            # A next-mission preference never replaces an active mission.
            if state.preparing_mop:
                _check_mop_readiness(state.dock)
            return ControlPlan(command, expected_mode=state.mode, already_confirmed=True)
        if state.activity not in {"idle", "docked"} or state.mission_active is not False:
            raise ControlError("unsupported_start")
        profiles = area_profiles or (profile,)
        modes = frozenset(value.mode for value in profiles)
        if new_mission and CleaningMode.VACUUM_THEN_MOP in modes:
            raise ControlError("unsupported_area_mode")
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
        return ControlPlan(command, profile, profile.mode, expected_modes=modes)
    if command is Command.RESUME:
        if state.activity != "paused" or state.mission_active is not True:
            raise ControlError("resume_requires_pause")
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


async def execute_control(
    port: ControlPort,
    command: Command,
    profile: CleaningProfile,
    *,
    new_mission: bool = False,
    area_profiles: tuple[CleaningProfile, ...] = (),
) -> None:
    """Read, validate, send once, then confirm; transport ACK is insufficient."""
    if not port.active:
        raise ControlError("not_configured")
    try:
        before = await port.refresh()
    except AuthenticationError:
        raise
    except Exception:
        raise ControlError("robot_unavailable") from None
    plan = prepare_control(
        command, before, profile, new_mission=new_mission, area_profiles=area_profiles
    )
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
        await port.send(plan.command, plan.profile)
        if plan.command is Command.LOCATE:
            port.report("submitted")
            return
        deadline = port.clock() + (120 if plan.command is Command.DOCK else 40)
        while port.active and port.clock() < deadline:
            await port.wait(5)
            state = await port.refresh()
            if state.connected is not True:
                break
            if plan.command is Command.POINT_CLEAN:
                # Live state describes a regular vacuum mission. Its exact target
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
            if plan.confirms(state):
                port.report("confirmed")
                return
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
    except AuthenticationError, asyncio.CancelledError:
        port.report("unconfirmed")
        raise
    except Exception:
        port.report("unconfirmed")
        raise ControlError("command_unconfirmed") from None
