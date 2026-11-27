"""Pure state projection: retain unknown values and separate connectivity facts."""

from dataclasses import dataclass, field
from datetime import datetime

from .capabilities import DeviceCapabilities
from .capability_protocol import project_capabilities
from .telemetry import (
    CLEANING_CYCLES,
    CYCLES,
    MOP_PREPARATION_PHASES,
    PHASE_PROBLEMS,
    PHASES,
    connection_status,
    convert,
    integer,
    project_telemetry,
)


@dataclass(frozen=True, repr=False)
class RobotState:
    robot_id: str
    name: str
    sku: str
    connected: bool | None
    battery: int | None
    phase: str | None
    cycle: str | None
    mode: int | None
    error: int | None
    telemetry: dict = field(default_factory=dict)
    observed_at: datetime | None = None
    capabilities: DeviceCapabilities = field(default_factory=DeviceCapabilities)
    reported_name: str | None = None

    @property
    def ready(self) -> bool | None:
        code = self.telemetry.get("not_ready_code")
        conditions = self.telemetry.get("not_ready_conditions", ())
        if code or conditions or self.activity == "error" or self.manual_pad_wash:
            return False
        if conditions is None or code is None:
            return None
        return True

    @property
    def mop_attached(self) -> bool | None:
        pad = self.telemetry.get("detected_pad")
        return pad not in {"none", "invalid"} if pad is not None else None

    @property
    def manual_pad_wash(self) -> bool:
        return (
            self.phase == "padWash"
            and self.cycle == "none"
            and self.capabilities.dock.recognized is True
            and self.telemetry.get("pad_wash_state") == 602
        )

    @property
    def mapping(self) -> bool | None:
        return self.cycle == "train" if self.cycle in CYCLES else None

    @property
    def mission_at_dock(self) -> bool | None:
        if self.phase not in PHASES or self.cycle not in CYCLES:
            return None
        return self.activity == "docked" and self.cycle in CLEANING_CYCLES

    @property
    def preparing_mop(self) -> bool | None:
        if self.phase not in PHASES or self.cycle not in CYCLES:
            return None
        return (
            not self.error
            and self.phase in MOP_PREPARATION_PHASES
            and self.cycle in CLEANING_CYCLES
        )

    @property
    def activity(self) -> str | None:
        if self.error or any(self.phase in phases for phases in PHASE_PROBLEMS.values()):
            return "error"
        if self.phase == "run" or self.preparing_mop:
            return "cleaning"
        if self.phase == "charge" or self.manual_pad_wash:
            return "docked"
        if self.phase in {"hmUsrDock", "hmUsrChrg", "hmPostMsn", "hmMidMsn"}:
            return "returning"
        if self.phase == "stop":
            if self.cycle == "none":
                return "idle"
            if self.cycle in CLEANING_CYCLES or self.mapping is True:
                return "paused"
        return None

    def confirms(self, command: str) -> bool:
        if self.connected is not True:
            return False
        if command == "start":
            return self.activity == "cleaning" and self.mode == 2
        if command == "pause":
            return self.activity == "paused"
        if command == "stop":
            return self.cycle == "none" and self.activity in {"idle", "docked"}
        if command == "dock":
            return self.activity == "docked" and self.cycle == "none"
        return False

    def mission_elapsed(self, now: datetime) -> int | None:
        started = self.telemetry.get("mission_started")
        if started is None or self.cycle in {None, "none"}:
            return None
        return max(0, int((now - started).total_seconds()))


def project_state(robot_id: str, details: dict, shadows: dict) -> RobotState:
    def reported(name):
        value = shadows.get(name, {})
        if not isinstance(value, dict):
            return {}
        state = value.get("state", {})
        value = state.get("reported", {}) if isinstance(state, dict) else {}
        return value if isinstance(value, dict) else {}

    current, connection = reported("ro-currentstate"), reported("rw-constatus")
    mission = current.get("cleanMissionStatus", {})
    if not isinstance(mission, dict):
        mission = {}
    battery = current.get("batPct")
    if type(battery) is not int or not 0 <= battery <= 100:
        battery = None
    connected = connection_status(connection)
    telemetry = project_telemetry(shadows)
    reported_name = convert("robot_name", reported("rw-settings").get("name"))
    return RobotState(
        robot_id,
        reported_name or details.get("name") or "Roomba",
        details.get("sku", "unknown"),
        connected,
        battery,
        telemetry.get("mission_phase"),
        telemetry.get("mission_cycle"),
        mission.get("operatingMode") if type(mission.get("operatingMode")) is int else None,
        integer(mission.get("error")),
        telemetry,
        capabilities=project_capabilities(details, shadows),
        reported_name=reported_name,
    )
