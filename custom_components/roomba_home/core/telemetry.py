"""Allowlisted, typed telemetry. Raw shadows never become entity attributes."""

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime

MISSING = object()
FAST_SHADOWS = ("ro-currentstate", "rw-constatus")
DETAIL_SHADOWS = ("rw-settings", "rw-software", "ro-stats", "rw-schedule")
PARTS = {
    "67": "side_brush",
    "71": "main_brushes",
    "72": "filter",
    "147": "dust_bag",
    "148": "mop_roller",
    "202": "dock_washing_system",
    "212": "mop_washing_system",
}
DOCK_PARTS = frozenset({"147", "202"})
COUNT_UNITS = {
    "minutes": "min",
    "missions": None,
    "combo_missions": None,
    "evacs": None,
    "pad_washes_used": None,
    "sqft": "m²",
}
PART_COUNT_TYPES = {
    "67": "minutes",
    "71": "minutes",
    "72": "minutes",
    "147": "evacs",
    "148": "combo_missions",
    "202": "pad_washes_used",
    "212": "sqft",
}


@dataclass(frozen=True)
class Metric:
    key: str
    shadow: str
    path: str
    kind: str = "int"
    unit: str | None = None
    diagnostic: bool = False
    total: bool = False


MISSION_INITIATORS = frozenset(
    {
        "unknown",
        "rmtApp",
        "schedule",
        "localApp",
        "manual",
        "dockBtn",
        "dockButton",
        "alexa",
        "alismart",
        "bosch",
        "cloud",
        "google",
        "homey",
        "ifttt",
        "iftttc",
        "internal",
        "internal_",
        "loclAuto",
        "matter",
        "openHAB",
        "rmtAuto",
        "shell",
        "simAuto",
        "siri",
        "swisscom",
        "team",
        "yonomi",
        "wifi",
    }
)


METRICS = (
    Metric("mission_phase", "ro-currentstate", "cleanMissionStatus.phase", "phase"),
    Metric("mission_cycle", "ro-currentstate", "cleanMissionStatus.cycle", "cycle"),
    Metric(
        "mission_initiator",
        "ro-currentstate",
        "cleanMissionStatus.initiator",
        "initiator",
        diagnostic=True,
    ),
    Metric("operating_mode", "ro-currentstate", "cleanMissionStatus.operatingMode"),
    Metric("mission_area", "ro-currentstate", "cleanMissionStatus.sqft", "area", "m²"),
    Metric("mission_started", "ro-currentstate", "cleanMissionStatus.mssnStrtTm", "timestamp"),
    Metric("mission_number", "ro-currentstate", "cleanMissionStatus.nMssn", diagnostic=True),
    Metric("not_ready_code", "ro-currentstate", "cleanMissionStatus.notReady", diagnostic=True),
    Metric("bin_present", "ro-currentstate", "bin.present", "bool"),
    Metric("bin_full", "ro-currentstate", "bin.full", "bool"),
    Metric("tank_present", "ro-currentstate", "tankPresent", "bool"),
    Metric("detected_pad", "ro-currentstate", "detectedPad", "pad"),
    Metric("dock_known", "ro-currentstate", "dock.known", "bool", diagnostic=True),
    Metric("dock_error", "ro-currentstate", "dock.error", diagnostic=True),
    Metric("evacuation_state", "ro-currentstate", "dock.state"),
    Metric("refill_state", "ro-currentstate", "dock.frState"),
    Metric("pad_wash_state", "ro-currentstate", "dock.pwState"),
    Metric("pad_dry_state", "ro-currentstate", "dock.pdState"),
    Metric("dock_firmware", "ro-currentstate", "dock.fwVer", "version", diagnostic=True),
    Metric("dock_tank_level", "ro-currentstate", "dock.tankLvl"),
    Metric("runtime_hours", "ro-currentstate", "runtimeStats.hr", unit="h", diagnostic=True),
    Metric("runtime_minutes", "ro-currentstate", "runtimeStats.min", unit="min", diagnostic=True),
    Metric("connection_code", "rw-constatus", "connectedv2", diagnostic=True),
    Metric("software_version", "rw-software", "softwareVer", "version", diagnostic=True),
    Metric("controller_firmware", "rw-software", "subModSwVer.con", "version", diagnostic=True),
    Metric("mcu_firmware", "rw-software", "subModSwVer.mcu", "version", diagnostic=True),
    Metric("navigation_firmware", "rw-software", "subModSwVer.nav", "version", diagnostic=True),
    Metric("software_deployment_state", "rw-software", "deploymentState", diagnostic=True),
    Metric("charging_errors", "ro-stats", "bbchg.nChgErr", diagnostic=True, total=True),
    Metric("successful_charges", "ro-stats", "bbchg.nChgOk", diagnostic=True, total=True),
    Metric("hours_on_dock", "ro-stats", "bbchg3.hOnDock", unit="h", diagnostic=True, total=True),
    Metric("total_missions", "ro-stats", "bbmssn.nMssn", total=True),
    Metric("mission_counter_c", "ro-stats", "bbmssn.nMssnC", diagnostic=True, total=True),
    Metric("mission_counter_f", "ro-stats", "bbmssn.nMssnF", diagnostic=True, total=True),
    Metric("successful_missions", "ro-stats", "bbmssn.nMssnOk", total=True),
    Metric("navigation_resets", "ro-stats", "bbrstinfo.nNavRst", diagnostic=True, total=True),
    Metric("system_hours", "ro-stats", "bbsys.hr", unit="h", diagnostic=True),
    Metric("system_minutes", "ro-stats", "bbsys.min", unit="min", diagnostic=True),
    Metric("audio_volume", "rw-settings", "audio.volume"),
    Metric("robot_timezone", "rw-settings", "timezone", "timezone", diagnostic=True),
    Metric("auto_evacuation_frequency", "rw-settings", "autoevacFreq"),
    Metric("carpet_boost", "rw-settings", "carpetBoost", "bool"),
    Metric("child_lock", "rw-settings", "childLock", "bool"),
    Metric("eco_charge", "rw-settings", "ecoCharge", "bool"),
    Metric("evacuation_allowed", "rw-settings", "evacAllowed", "bool"),
    Metric("map_upload_allowed", "rw-settings", "mapUploadAllowed", "bool", diagnostic=True),
    Metric("no_auto_passes", "rw-settings", "noAutoPasses", "bool"),
    Metric("obstacle_avoidance_mode", "rw-settings", "odoaMode"),
    Metric("pad_dry_allowed", "rw-settings", "padDryAllowed", "flag"),
    Metric("pad_dry_duration", "rw-settings", "padDryDur"),
    Metric("pad_wash_allowed", "rw-settings", "padWashAllowed", "flag"),
    Metric("pad_wetness", "rw-settings", "padWetness.padPlate"),
    Metric("pad_wash_area_interval", "rw-settings", "pwAreaInterval"),
    Metric("pad_wash_heat", "rw-settings", "pwHeat"),
    Metric("pad_wash_return", "rw-settings", "pwReturn"),
    Metric("pad_wash_time_interval", "rw-settings", "pwTimeInterval"),
    Metric("schedule_on_hold", "rw-settings", "schedHold", "bool"),
    Metric("suction_level", "rw-settings", "suctionLevel"),
    Metric("scrub_setting", "rw-settings", "swScrub"),
    Metric("two_pass", "rw-settings", "twoPass", "bool"),
    Metric("detergent_setting", "rw-settings", "detergent"),
    Metric("voice_language", "rw-settings", "langs2.sLang", "language"),
    Metric("dock_capability_evac", "ro-currentstate", "dock.cap.evac", diagnostic=True),
    Metric("dock_capability_refill", "ro-currentstate", "dock.cap.fr", diagnostic=True),
    Metric("dock_capability_dry", "ro-currentstate", "dock.cap.pd", diagnostic=True),
    Metric("dock_capability_wash", "ro-currentstate", "dock.cap.pw", diagnostic=True),
    Metric("dock_capability_pwo", "ro-currentstate", "dock.cap.pwo", diagnostic=True),
    Metric("dock_capability_detergent", "ro-currentstate", "dock.cap.detergent", diagnostic=True),
)
BY_KEY = {m.key: m for m in METRICS}
PHASES = frozenset(
    {
        "run",
        "charge",
        "stop",
        "stuck",
        "chgerr",
        "chargingerror",
        "hmUsrDock",
        "hmUsrChrg",
        "hmPostMsn",
        "hmMidMsn",
        "evac",
        "refill",
        "padWash",
        "padDry",
        "mapupd",
    }
)
PHASE_PROBLEMS = {
    "stuck": frozenset({"stuck"}),
    "charging_problem": frozenset({"chgerr", "chargingerror"}),
}
MOP_PREPARATION_PHASES = frozenset({"padWash", "refill"})
CLEANING_CYCLES = frozenset({"clean", "quick", "spot", "tidy"})
CYCLES = CLEANING_CYCLES | {
    "none",
    "dock",
    "evacuate",
    "evac",
    "train",
    "manual",
    "dock_upgrade",
    "monitor",
    "wash",
    "dry",
}
PADS = {
    "padPlate",
    "none",
    "invalid",
    "disposableWet",
    "disposableDry",
    "reusableWet",
    "reusableDry",
}


def reported(shadow):
    if not isinstance(shadow, dict) or not isinstance(shadow.get("state"), dict):
        return {}
    value = shadow["state"].get("reported")
    return value if isinstance(value, dict) else {}


def _connection_field(connection):
    if integer(connection.get("connectedv2"), 1) is not None:
        return "connectedv2"
    if type(connection.get("connected")) is bool:
        return "connected"
    return None


def connection_status(connection):
    """Use the SDK's typed cloud connection state and the legacy boolean fallback."""
    field = _connection_field(connection)
    return bool(connection[field]) if field else None


def at(value, path):
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return MISSING
        value = value[key]
    return value


def integer(value, maximum=2**53 - 1):
    return value if type(value) is int and 0 <= value <= maximum else None


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def convert(kind, value):
    if kind == "bool":
        return value if type(value) is bool else None
    if kind == "flag":
        return bool(value) if type(value) is int and value in (0, 1) else None
    if kind in {"phase", "cycle", "pad", "initiator"}:
        choices = {"phase": PHASES, "cycle": CYCLES, "pad": PADS, "initiator": MISSION_INITIATORS}[
            kind
        ]
        return value if isinstance(value, str) and value in choices else None
    if kind == "version":
        return (
            value
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.+-]{1,80}", value)
            else None
        )
    if kind == "language":
        return (
            value
            if isinstance(value, str) and re.fullmatch(r"[a-z]{2}(?:[-_][A-Za-z]{2})?", value)
            else None
        )
    if kind == "timezone":
        return (
            value
            if isinstance(value, str)
            and len(value) <= 80
            and re.fullmatch(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*", value)
            else None
        )
    if kind == "area":
        return round(value * 0.09290304, 2) if number(value) is not None else None
    if kind == "timestamp":
        return datetime.fromtimestamp(value, UTC) if integer(value, 32_503_680_000) else None
    return integer(value)


def project_telemetry(shadows):
    result = {}
    for metric in METRICS:
        raw = at(reported(shadows.get(metric.shadow)), metric.path)
        if raw is not MISSING:
            result[metric.key] = convert(metric.kind, raw)
    connection = shadows.get("rw-constatus")
    if field := _connection_field(reported(connection)):
        updated = convert("timestamp", at(connection, f"metadata.reported.{field}.timestamp"))
        if updated is not None:
            result["connection_updated_at"] = updated
    mission = reported(shadows.get("ro-currentstate")).get("cleanMissionStatus", {})
    conditions = at(mission, "condNotReady")
    if isinstance(conditions, list) and all(integer(x) is not None for x in conditions):
        result["not_ready_conditions"] = tuple(conditions[:32])
    elif conditions is not MISSING:
        result["not_ready_conditions"] = None
    schedules = reported(shadows.get("rw-schedule")).get("cleanSchedule2")
    if isinstance(schedules, list):
        result["schedule_count"] = len(schedules)
    return result


def project_parts(document, catalog=None):
    """Project catalog IDs, never robot_id, URLs, reset author or timestamps."""
    if not isinstance(document, dict) or not isinstance(document.get("parts"), list):
        return {}
    catalog = catalog if isinstance(catalog, dict) else {}
    catalog_parts = catalog.get("parts")
    metadata = {
        p["part_id"]: p
        for p in (catalog_parts if isinstance(catalog_parts, list) else [])
        if isinstance(p, dict) and isinstance(p.get("part_id"), str) and p["part_id"] in PARTS
    }
    result = {}
    for part in document["parts"]:
        if (
            not isinstance(part, dict)
            or not isinstance(part.get("part_id"), str)
            or part["part_id"] not in PARTS
        ):
            continue
        part_id = part["part_id"]
        # The observed catalog explicitly disables the dust-bag counter.
        enabled = metadata.get(part_id, {}).get("counter_enabled", part_id != "147") is not False
        count_type = part.get("count_type")
        valid_type = isinstance(count_type, str) and count_type == PART_COUNT_TYPES[part_id]
        values = {"usage": integer(part.get("counter"), 100)}
        for key in ("remaining", "used"):
            raw = part.get("count_" + key)
            values[key] = (
                (convert("area", raw) if count_type == "sqft" else integer(raw))
                if valid_type
                else None
            )
        for key, value in values.items():
            result[f"part_{part_id}_{key}"] = value if enabled else None
        result[f"part_{part_id}_unit"] = COUNT_UNITS.get(count_type) if valid_type else None
        result[f"part_{part_id}_count_type"] = count_type if valid_type else None
        category = part.get("counter_category")
        result[f"part_{part_id}_category"] = (
            category
            if isinstance(category, str) and category in {"replacement", "maintenance"}
            else None
        )
    return result
