"""Project capabilities from their native sources without guessing unknown values."""

from .capabilities import (
    DeviceCapabilities,
    DigitalSpotCapability,
    DockCapabilities,
    SkipCapability,
)
from .cleaning_protocol import cleaning_capabilities
from .telemetry import at, connection_status, integer, reported

DIGITAL_SPOT_CAPABILITIES = {
    0: DigitalSpotCapability.UNSUPPORTED,
    1: DigitalSpotCapability.SUPPORTED,
    2: DigitalSpotCapability.HEATED_WATER,
}
SKIP_CAPABILITIES = {
    0: SkipCapability.UNSUPPORTED,
    1: SkipCapability.DIRECTED_ONLY,
    2: SkipCapability.DIRECTED_AND_WHOLE_MAP,
    3: SkipCapability.CURRENT_AREA,
}


def project_capabilities(details: dict, shadows: dict) -> DeviceCapabilities:
    robot = details.get("cap")
    robot = robot if isinstance(robot, dict) else {}
    digital = details.get("digiCap")
    digital = digital if isinstance(digital, dict) else {}
    current = reported(shadows.get("ro-currentstate"))
    dock = current.get("dock")
    dock = dock if isinstance(dock, dict) else {}
    recognized = dock.get("known")
    recognized = recognized if type(recognized) is bool else None
    dock_codes = dock.get("cap")
    dock_codes = dock_codes if isinstance(dock_codes, dict) else {}

    def dock_support(field: str, known: frozenset[int]) -> bool | None:
        if recognized is False:
            return False
        code = integer(dock_codes.get(field))
        return code in known if recognized is True and code in (known | {0}) else None

    maps = integer(robot.get("p2maps"))
    timeline = integer(digital.get("timeline"), 1)
    refill = dock_support("fr", frozenset({1, 2}))
    phase = at(current, "cleanMissionStatus.phase")
    schedule = integer(robot.get("sched"), 2)
    return DeviceCapabilities(
        cleaning=cleaning_capabilities(robot),
        dock=DockCapabilities(
            recognized=recognized,
            evacuation=dock_support("evac", frozenset({1})),
            wash=dock_support("pw", frozenset({1, 2, 3, 4})),
            dry=dock_support("pd", frozenset({1, 2, 3})),
            refill=refill,
            manual_refill=refill and dock_codes["fr"] == 1,
        ),
        docking=(
            True
            if recognized is True
            or isinstance(phase, str)
            and phase in {"charge", "hmUsrDock", "hmPostMsn", "hmMidMsn"}
            else None
        ),
        persistent_maps=bool(maps & 1) if maps is not None else None,
        schedules=(
            True
            if isinstance(reported(shadows.get("rw-schedule")).get("cleanSchedule2"), list)
            else bool(schedule)
            if schedule is not None
            else None
        ),
        history=bool(timeline) if timeline is not None else None,
        statistics=True if reported(shadows.get("ro-stats")) else None,
        firmware=True if isinstance(details.get("softwareVer"), str) else None,
        connectivity=(
            True if connection_status(reported(shadows.get("rw-constatus"))) is not None else None
        ),
        water_tank=True if type(current.get("tankPresent")) is bool else None,
        diagnostics=True if current else None,
        digital_spot=DIGITAL_SPOT_CAPABILITIES.get(integer(robot.get("dSpot"), 2)),
        skip=SKIP_CAPABILITIES.get(integer(robot.get("mc"), 3)),
        routine_presets=integer(digital.get("cleaningProfiles"), 2) in (1, 2),
        locate=True
        if integer(at(reported(shadows.get("rw-settings")), "audio.volume")) is not None
        else None,
    )
