"""Observed problem codes and deterministic, restorable change detection.

Mappings are protocol facts contrasted with the official app SDK 3.4.1.
They are not evidence that every physical failure was induced and tested.
"""

from dataclasses import dataclass

from .dock import DOCK_COMPONENT_CAPABILITIES, DOCK_FIELDS, component_fault
from .telemetry import DOCK_PARTS, PARTS, PHASE_PROBLEMS, PHASES, integer

READINESS_CONDITIONS = "readiness_conditions"
FLAG_REASONS = {
    "stuck": "robot_stuck",
    "charging_problem": "charging_failed",
    "bin_missing": "bin_missing",
    "bin_full": "bin_full",
}

SOURCES = (
    "connection",
    "mission",
    "firmware",
    "readiness",
    READINESS_CONDITIONS,
    *FLAG_REASONS,
    "dock",
    "evacuation",
    "refill",
    "pad_wash",
    "pad_dry",
) + tuple("part_" + key for key in PARTS)
DOCK_PROBLEM_SOURCES = frozenset({"dock", *DOCK_FIELDS, *(f"part_{part}" for part in DOCK_PARTS)})


def reason(source, code):
    if source == "connection":
        return "disconnected"
    if source.startswith("part_"):
        return "maintenance_due"
    if source in FLAG_REASONS:
        return FLAG_REASONS[source]
    if source == READINESS_CONDITIONS:
        return "reported_conditions"
    if source == "mission":
        if code in DOCUMENTED_DOCK_MESSAGE_CODES:
            return ERROR_NAMES[code]
        return MISSION_ERROR_NAMES.get(code, "provider_code")
    if source == "firmware":
        return FIRMWARE_ERROR_NAMES.get(code, "unknown_code")
    if source == "readiness":
        return "provider_code"
    return ERROR_NAMES.get(code, "unknown_code")


def dock_status_meaning(source, code):
    if source == "dock" and code == 0:
        return "ok"
    if source == "dock" or component_fault(source, code):
        return reason(source, code)
    return DOCK_STATES[source].get(code, "unknown_code")


def _problem_value(source, value):
    if source != READINESS_CONDITIONS:
        return integer(value)
    if not isinstance(value, (list, tuple)) or any(integer(code) is None for code in value):
        return None
    return tuple(sorted(set(value[:32])))


def _bool_problem(value, active_value):
    return int(value is active_value) if type(value) is bool else None


def observations(state):
    """None is missing evidence; readiness conditions retain all reported codes."""
    result = {source: None for source in SOURCES}
    result["connection"] = None if state.connected is None else int(not state.connected)
    if state.connected is not True:
        return result
    values = state.telemetry
    result["mission"] = integer(state.error)
    deployment = integer(values.get("software_deployment_state"))
    if deployment in FIRMWARE_STATES:
        result["firmware"] = 0
    elif deployment is not None and deployment >= 100:
        result["firmware"] = deployment
    result["readiness"] = integer(values.get("not_ready_code"))
    result[READINESS_CONDITIONS] = _problem_value(
        READINESS_CONDITIONS, values.get("not_ready_conditions")
    )
    if state.phase in PHASES:
        for source, phases in PHASE_PROBLEMS.items():
            result[source] = int(state.phase in phases)
    result["bin_missing"] = _bool_problem(values.get("bin_present"), False)
    result["bin_full"] = _bool_problem(values.get("bin_full"), True)
    if values.get("dock_known") is True and state.capabilities.dock.recognized is not False:
        raw = integer(values.get("dock_error"))
        # SDK classifies 510 as an update in progress, rather than an equipment failure.
        result["dock"] = 0 if raw == 510 else raw
        capabilities = state.capabilities.dock
        shared = values.get("refill_state")
        for source, (key, _, _) in DOCK_FIELDS.items():
            if getattr(capabilities, DOCK_COMPONENT_CAPABILITIES[source]) is False:
                continue
            # Without a dedicated field, older docks share refill, wash and dry status.
            fallback = shared if source in ("pad_wash", "pad_dry") else None
            raw = integer(values.get(key, fallback))
            if component_fault(source, raw):
                result[source] = raw
            elif raw in DOCK_STATES[source] and DOCK_STATES[source][raw] != "unknown":
                result[source] = 0
    for part in PARTS:
        usage = values.get(f"part_{part}_usage")
        remaining = values.get(f"part_{part}_remaining")
        if usage is not None or remaining is not None:
            result["part_" + part] = int((usage is not None and usage >= 100) or remaining == 0)
    return result


def _dock_health(capabilities, codes):
    if capabilities.recognized is False:
        return None
    values = [codes["dock"]]
    values.extend(
        codes[source]
        for source, cap in DOCK_COMPONENT_CAPABILITIES.items()
        if getattr(capabilities, cap) is not False
    )
    return True if any(values) else None if None in values else False


def dock_has_problem(state):
    return _dock_health(state.capabilities.dock, observations(state))


def has_problem(state):
    codes = observations(state)
    if any(codes.values()):
        return True
    if state.connected is not True or state.error is None:
        return None
    if state.telemetry.get("parts_available") is False:
        return None
    if (
        "not_ready_conditions" in state.telemetry
        and state.telemetry["not_ready_conditions"] is None
    ):
        return None
    if state.telemetry.get("dock_known") is True:
        if _dock_health(state.capabilities.dock, codes) is None:
            return None
    return False


@dataclass(frozen=True)
class ProblemChange:
    event_type: str
    source: str
    code: int | tuple[int, ...]
    previous_code: int | tuple[int, ...] | None

    def attributes(self):
        result = {
            "source": self.source,
            "code": self.code,
            "previous_code": self.previous_code,
            "reason": reason(self.source, self.code or self.previous_code),
        }
        if isinstance(self.code, tuple):
            previous = self.previous_code
            result.update(
                code=len(self.code),
                previous_code=len(previous) if previous is not None else None,
                condition_codes=list(self.code),
                previous_condition_codes=list(previous) if previous is not None else None,
            )
        return result


class ProblemTracker:
    def __init__(self, restored=None):
        self.codes = {
            key: parsed
            for key, value in (restored.items() if isinstance(restored, dict) else ())
            if key in SOURCES and (parsed := _problem_value(key, value)) is not None
        }

    def observe(self, values):
        changes = []
        for source in SOURCES:
            code = _problem_value(source, values.get(source))
            if code is None:
                continue
            previous = self.codes.get(source)
            self.codes[source] = code
            if code == previous or (not code and not previous):
                continue
            event_type = (
                "problem_cleared"
                if not code
                else "problem_changed"
                if previous
                else "problem_detected"
            )
            changes.append(ProblemChange(event_type, source, code, previous))
        return changes


# iRobot support chart 10502, entries applicable to the modern Max 700 series.
MISSION_ERROR_NAMES = {
    2: "main_brush_stalled",
    4: "left_wheel_jammed",
    5: "right_wheel_jammed",
    6: "cliff_sensor",
    9: "bumper_jammed",
    14: "bin_missing",
    16: "navigation_failed",
    19: "undocking_failed",
    26: "low_airflow",
    29: "robot_updating",
    32: "map_version_mismatch",
    33: "robot_stuck",
    35: "pad_detection_failed",
    44: "robot_water_pump_failed",
    46: "low_battery",
    48: "path_blocked",
    69: "localization_failed",
    101: "battery_missing",
    102: "battery_fault",
    103: "charging_system_fault",
    104: "no_charging_current",
    105: "low_charging_current",
    106: "battery_too_hot",
    107: "battery_too_cold",
    109: "permanent_battery_fault",
    110: "battery_cell_imbalance",
    111: "battery_hardware_fault",
    114: "internal_battery_error",
    115: "battery_cell_failed",
    117: "battery_unrecognized",
    119: "docked_charging_failed",
    120: "battery_fault",
    121: "discharging_on_dock",
    266: "app_setup_required",
    1000: "left_side_brush_stalled",
    1001: "side_brush_stalled",
    1008: "pad_actuator_stall",
    1010: "navigation_failed",
    1025: "lidar_fault",
    1026: "mop_stuck",
    1029: "incompatible_map",
    1030: "stuck_in_no_mop_zone",
}


# SDK DeploymentState and DeploymentStateError. These codes are not mission codes.
FIRMWARE_STATES = {0: "idle", 1: "pending", 2: "ready", 3: "downloading", 4: "installing"}
FIRMWARE_ERROR_NAMES = {
    101: "legacy_certificate_authentication",
    102: "user_aborted",
    103: "wifi_timeout",
    104: "wifi_failure",
    105: "uart_busy",
    106: "hardware_not_suitable",
    107: "hardware_incompatible",
    111: "install_failed",
    130: "invalid_metapackage_size",
    131: "invalid_metapackage_header",
    132: "invalid_metapackage_signature",
    133: "invalid_package_data",
    134: "update_timeout",
    135: "invalid_package_header",
    136: "invalid_package_label",
    137: "invalid_package_signature",
}


# Keep the SDK enums separate. A value from another component cannot clear a fault.
DOCK_STATES = {
    "evacuation": {
        300: "unknown",
        301: "ok",
        302: "evacuation_in_progress",
        303: "evacuation_complete",
        304: "evacuation_stopping",
        305: "dock_upgrading",
    },
    "refill": {
        400: "unknown",
        401: "okay",
        402: "replenishment_positioning",
        403: "replenishment_filling",
        404: "replenishment_complete",
        405: "replenishment_complete_with_not_enough_fluid",
        406: "dock_updating",
    },
    "pad_wash": {
        600: "unknown",
        601: "okay",
        602: "pad_washing_in_progress",
        603: "pad_washing_complete_with_success",
        606: "dock_updating",
        607: "flushing_sluice",
        608: "flushing_of_sluice_complete",
    },
    "pad_dry": {
        700: "unknown",
        701: "okay",
        702: "pad_drying_in_progress",
        703: "pad_drying_complete",
        704: "pad_drying_interrupted_by_robot",
        705: "pad_drying_interrupted_by_mission",
        706: "pad_drying_ended_by_customer",
        707: "dock_updating",
    },
}

# The public Max 700 error chart also lists dock-related messages that can end a routine.
DOCUMENTED_DOCK_MESSAGE_CODES = frozenset(
    {
        350,
        353,
        360,
        365,
        450,
        451,
        455,
        457,
        510,
        513,
        517,
        520,
        653,
        654,
        660,
        668,
        669,
        670,
        671,
        672,
        751,
        752,
        756,
        757,
    }
)

ERROR_NAMES = {
    350: "bag_missing",
    351: "clog",
    352: "poor_sealing",
    353: "bag_full",
    354: "motor_failure",
    360: "communication_failure",
    361: "evac_report_comms_failure",
    362: "lifetime_data_report_comms_failure",
    363: "both_reports_comms_failure",
    364: "evac_dock_identified_but_no_communication",
    365: "too_frequent_evacs",
    449: "invalid_dock_state",
    450: "dock_tank_missing",
    451: "dock_tank_level_too_low",
    452: "dock_tank_level_sensor_issue",
    453: "alignment_failure",
    454: "clog",
    455: "pump_failure",
    456: "incorrect_robot_tank",
    457: "communication_failure",
    458: "couldnt_extend_nozzle",
    459: "couldnt_retract_nozzle",
    460: "dock_tank_level_not_decreasing",
    461: "robot_tank_level_not_increasing",
    462: "generic_refill_issue",
    463: "dock_tank_level_decreasing",
    464: "detergent_tank_missing_or_empty",
    500: "reserved",
    501: "buoy_path_occluded",
    502: "coc_communication_failure",
    503: "ble_communication_failure",
    504: "home_switch_failure",
    505: "primary_internal_dock_comms_failure",
    506: "secondary_internal_dock_comms_failure",
    507: "ble_pairing_failure",
    508: "primary_processor_update_failure",
    509: "secondary_processor_update_failure",
    510: "dock_updating",
    511: "grey_water_dock_tank_level_sensor_issue",
    512: "grey_water_evac_clog",
    513: "grey_water_pump_failure",
    515: "grey_water_control_valve_failure",
    516: "sluice_agitator_motor_stall",
    517: "sluice_overflow",
    518: "missing_sluice_agitator",
    519: "not_on_contacts",
    520: "dock_irda_comms_failure",
    649: "invalid_dock_state",
    650: "clear_fluid_dock_tank_missing",
    651: "clear_fluid_dock_tank_level_too_low",
    652: "clear_fluid_dock_tank_level_sensor_issue",
    653: "grey_water_dock_tank_missing",
    654: "grey_water_dock_tank_level_too_full",
    660: "communication_failure",
    661: "clear_fluid_dock_tank_level_not_decreasing",
    662: "grey_water_dock_tank_level_not_increasing",
    663: "clear_fluid_dock_tank_level_decreasing",
    664: "grey_water_dock_tank_level_decreasing",
    665: "hardware_issue",
    668: "no_pad_attached",
    669: "pad_actuator_stall",
    670: "cleaning_tray_out_of_position",
    671: "clear_fluid_tank_empty_or_not_installed",
    672: "grey_water_tank_full_or_not_installed",
    749: "invalid_state",
    750: "pad_drying_motor_stall",
    751: "pad_drying_motor_fail_to_start",
    752: "pad_actuator_stall",
    753: "pad_not_washed",
    754: "fet_fault",
    755: "hardware_issue",
    756: "no_pad_attached",
    757: "communication_failure",
}
