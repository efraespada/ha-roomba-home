"""Useful values have their own stable sensor, units and history."""

from datetime import UTC, datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory

from .core.cleaning import CleaningMode
from .core.cleaning_protocol import reported_cleaning_mode
from .core.dock import DOCK_COMPONENT_CAPABILITIES, DOCK_FIELDS
from .core.history import HISTORY_COMMANDS, HISTORY_TARGETS, OUTCOMES
from .core.problems import FIRMWARE_STATES, dock_status_meaning, observations, reason
from .core.telemetry import BY_KEY, COUNT_UNITS, DOCK_PARTS, PART_COUNT_TYPES, PARTS
from .entity import RoombaEntity, discover_entities

DOCK_STATE_SOURCES = {key: source for source, (key, _, _) in DOCK_FIELDS.items()}
DOCK_ERROR_SOURCES = {f"{source}_error": source for source in DOCK_FIELDS}
DERIVED_METRICS = {
    "connection_updated_at": (None, SensorDeviceClass.TIMESTAMP),
    "current_room": (None, None),
    "position_updated": (None, SensorDeviceClass.TIMESTAMP),
    "live_timeline_updated": (None, SensorDeviceClass.TIMESTAMP),
    "schedule_count": (None, None),
    "cloud_schedule_count": (None, None),
    "cloud_enabled_schedule_count": (None, None),
    "next_cloud_schedule": (None, SensorDeviceClass.TIMESTAMP),
    "map_count": (None, None),
    "room_count": (None, None),
    "zone_count": (None, None),
    "history_count": (None, None),
    "last_mission_rooms": (None, None),
    "last_mission_started": (None, SensorDeviceClass.TIMESTAMP),
    "last_mission_finished": (None, SensorDeviceClass.TIMESTAMP),
    "last_mission_duration": ("min", SensorDeviceClass.DURATION),
    "last_mission_active_duration": ("min", SensorDeviceClass.DURATION),
    "last_mission_pause_duration": ("min", SensorDeviceClass.DURATION),
    "last_mission_charge_duration": ("min", SensorDeviceClass.DURATION),
    "last_mission_recharges": (None, None),
    "last_mission_evacuations": (None, None),
    "last_mission_area": ("m²", SensorDeviceClass.AREA),
    "last_mission_initiator": (None, None),
    "last_mission_command": (None, SensorDeviceClass.ENUM),
    "last_mission_target": (None, SensorDeviceClass.ENUM),
    "last_mission_error": (None, None),
    "last_mission_outcome": (None, SensorDeviceClass.ENUM),
}


def _dock_metric(key):
    return key.startswith("dock_") or key in DOCK_STATE_SOURCES or key in DOCK_ERROR_SOURCES


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [
            entity(coordinator, key)
            for key in coordinator.data
            for entity in (RoombaBattery, RoombaMissionError, RoombaLastCommand, RoombaCloudRead)
        ]
    )
    discover_entities(entry, async_add_entities, sensor_candidates)


def sensor_candidates(state):
    dock_recognized = state.capabilities.dock.recognized is True
    for key in state.telemetry:
        if (
            key in BY_KEY
            and BY_KEY[key].kind not in {"bool", "flag"}
            and (dock_recognized or not _dock_metric(key))
        ):
            yield key, RoombaMetricSensor
    if "mission_started" in state.telemetry:
        yield "mission_elapsed", RoombaMetricSensor
    if "operating_mode" in state.telemetry:
        yield "reported_cleaning_mode", RoombaCleaningModeSensor
    if "not_ready_conditions" in state.telemetry:
        yield "not_ready_condition_count", RoombaMetricSensor
    for key in DERIVED_METRICS:
        if key in state.telemetry:
            yield key, RoombaMetricSensor
    if dock_recognized:
        codes = observations(state)
        for source, (key, _, _) in DOCK_FIELDS.items():
            if getattr(
                state.capabilities.dock, DOCK_COMPONENT_CAPABILITIES[source]
            ) is not False and (key in state.telemetry or codes[source] is not None):
                yield source + "_error", RoombaMetricSensor
    for part in PARTS:
        if part in DOCK_PARTS and not dock_recognized:
            continue
        for suffix in ("usage", "remaining", "used"):
            key = f"part_{part}_{suffix}"
            if key in state.telemetry:
                yield key, RoombaMetricSensor


class RoombaBattery(RoombaEntity, SensorEntity):
    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, robot_id):
        super().__init__(coordinator, robot_id, "battery")

    @property
    def native_value(self):
        return self.robot.battery if self.robot else None


class RoombaMissionError(RoombaEntity, SensorEntity):
    _attr_translation_key = "mission_error"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, robot_id):
        super().__init__(coordinator, robot_id, "mission_error")

    @property
    def native_value(self):
        return self.robot.error if self.robot else None

    @property
    def extra_state_attributes(self):
        code = self.native_value
        return {"meaning": reason("mission", code)} if code else None


class RoombaLastCommand(RoombaEntity, SensorEntity):
    _attr_translation_key = "last_command"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["pending", "submitted", "confirmed", "unconfirmed"]

    def __init__(self, coordinator, robot_id):
        super().__init__(coordinator, robot_id, "last_command")

    @property
    def native_value(self):
        return self.account.command_status.get(self.robot_id)


class RoombaCleaningModeSensor(RoombaEntity, SensorEntity):
    _attr_translation_key = "reported_cleaning_mode"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [mode.value for mode in CleaningMode]

    def __init__(self, coordinator, robot_id, key):
        super().__init__(coordinator, robot_id, key)

    @property
    def native_value(self):
        mode = reported_cleaning_mode(self.robot.mode) if self.robot else None
        return mode.value if mode else None


class RoombaCloudRead(RoombaEntity, SensorEntity):
    _attr_translation_key = "cloud_read"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, robot_id):
        super().__init__(coordinator, robot_id, "cloud_read")

    @property
    def available(self):
        return self.coordinator.last_update_success and self.robot is not None

    @property
    def native_value(self):
        return self.robot.observed_at if self.robot else None


class RoombaMetricSensor(RoombaEntity, SensorEntity):
    def __init__(self, coordinator, robot_id, key):
        part = key.split("_")[1] if key.startswith("part_") else None
        super().__init__(coordinator, robot_id, key, dock=_dock_metric(key) or part in DOCK_PARTS)
        self.key = key
        self._attr_translation_key = key
        self._attr_icon = "mdi:robot-vacuum"
        metric = BY_KEY.get(key)
        if key in DERIVED_METRICS:
            self._attr_native_unit_of_measurement, self._attr_device_class = DERIVED_METRICS[key]
        if key in {"connection_updated_at", "last_mission_initiator", "last_mission_error"}:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if key == "last_mission_outcome":
            self._attr_options = list(OUTCOMES.values())
        if key == "last_mission_command":
            self._attr_options = list(HISTORY_COMMANDS)
        if key == "last_mission_target":
            self._attr_options = list(HISTORY_TARGETS)
        if metric:
            self._attr_native_unit_of_measurement = metric.unit
            if metric.diagnostic:
                self._attr_entity_category = EntityCategory.DIAGNOSTIC
            if metric.total:
                self._attr_state_class = SensorStateClass.TOTAL_INCREASING
            if metric.kind == "timestamp":
                self._attr_device_class = SensorDeviceClass.TIMESTAMP
        if key.startswith("part_"):
            _, part, suffix = key.split("_")
            self._attr_native_unit_of_measurement = (
                "%" if suffix == "usage" else COUNT_UNITS[PART_COUNT_TYPES[part]]
            )
        if key == "mission_elapsed":
            self._attr_native_unit_of_measurement = "s"
        unit = self.native_unit_of_measurement
        if unit in {"min", "s", "h"}:
            self._attr_device_class = SensorDeviceClass.DURATION
        elif unit == "m²":
            self._attr_device_class = SensorDeviceClass.AREA

    @property
    def available(self):
        if self.key == "connection_updated_at":
            return self.coordinator.last_update_success and self.robot is not None
        return super().available

    @property
    def native_value(self):
        state = self.robot
        if not state:
            return None
        if self.key == "mission_elapsed":
            started = state.telemetry.get("mission_started")
            return (
                max(0, int((datetime.now(UTC) - started).total_seconds()))
                if started and state.cycle not in {None, "none"}
                else None
            )
        if self.key == "not_ready_condition_count":
            conditions = state.telemetry.get("not_ready_conditions")
            return len(conditions) if conditions is not None else None
        if self.key == "last_mission_rooms":
            rooms = state.telemetry.get(self.key)
            return len(rooms) if rooms is not None else None
        if self.key in DOCK_ERROR_SOURCES:
            return observations(state)[DOCK_ERROR_SOURCES[self.key]]
        return state.telemetry.get(self.key)

    @property
    def extra_state_attributes(self):
        values = self.robot.telemetry if self.robot else {}
        if self.key == "dock_error":
            return {"meaning": dock_status_meaning("dock", self.native_value)}
        if self.key in DOCK_STATE_SOURCES:
            return {"meaning": dock_status_meaning(DOCK_STATE_SOURCES[self.key], self.native_value)}
        if self.key in DOCK_ERROR_SOURCES:
            code = self.native_value
            return {"meaning": "ok" if code == 0 else reason(DOCK_ERROR_SOURCES[self.key], code)}
        if self.key == "software_deployment_state":
            code = self.native_value
            return {"meaning": FIRMWARE_STATES.get(code, reason("firmware", code))}
        if self.key == "not_ready_condition_count":
            conditions = values.get("not_ready_conditions")
            return {"condition_codes": list(conditions) if conditions is not None else None}
        if self.key == "last_mission_outcome":
            return {
                "cleaning_modes": values.get("last_mission_modes"),
                "mode_statistics": values.get("last_mission_mode_statistics"),
                "started_at_dock": values.get("last_mission_started_at_dock"),
            }
        if self.key == "last_mission_rooms":
            return {"rooms": values.get(self.key)}
        if self.key == "live_timeline_updated":
            return {
                "stage": values.get("live_timeline_stage"),
                "rooms": values.get("live_timeline_rooms"),
                "active_rooms": values.get("live_timeline_active_rooms"),
            }
        if self.key == "last_mission_error":
            code = self.native_value
            return {"meaning": reason("mission", code)} if code else {}
        if self.key == "last_mission_target":
            count = values.get("last_mission_target_count")
            return {"region_count": count} if count is not None else {}
        if self.key == "cloud_schedule_count":
            return {"weekly_times": values.get("cloud_schedule_times")}
        if self.key.startswith("part_"):
            part = self.key.split("_")[1]
            return {
                "count_type": values.get(f"part_{part}_count_type"),
                "category": values.get(f"part_{part}_category"),
            }
        return {}
