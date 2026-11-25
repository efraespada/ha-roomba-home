"""Connectivity reports explicit false independently of vacuum availability."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory

from .core.problems import dock_has_problem, has_problem, observations
from .core.telemetry import BY_KEY, DOCK_PARTS, PARTS, PHASE_PROBLEMS, PHASES
from .entity import RoombaEntity, discover_entities

DOCK_BINARY_SENSORS = {"dock_problem", "dock_clean_water", "dock_maintenance_required"}
SOURCE_AVAILABILITY = {
    "details_available",
    "history_available",
    "maps_available",
    "parts_available",
    "schedules_available",
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [
            kind(coordinator, key)
            for key in coordinator.data
            for kind in (RoombaConnected, RoombaProblem)
        ]
    )
    discover_entities(entry, async_add_entities, binary_candidates)


def binary_candidates(state):
    for key in state.telemetry:
        if key in BY_KEY and BY_KEY[key].kind in {"bool", "flag"}:
            yield key, RoombaMetricBinary
        elif key in SOURCE_AVAILABILITY:
            yield key, RoombaMetricBinary
    if "not_ready_code" in state.telemetry or "not_ready_conditions" in state.telemetry:
        yield "ready", RoombaMetricBinary
    if state.phase in PHASES:
        for key in PHASE_PROBLEMS:
            yield key, RoombaMetricBinary
    if "detected_pad" in state.telemetry:
        yield "mop_attached", RoombaMetricBinary
    if state.preparing_mop is not None and any(
        mode.mops for mode in (state.capabilities.cleaning.modes or ())
    ):
        yield "preparing_mop", RoombaMetricBinary
    if state.capabilities.docking is True and state.mission_at_dock is not None:
        yield "mission_at_dock", RoombaMetricBinary
    if state.capabilities.persistent_maps is True and state.mapping is not None:
        yield "mapping", RoombaMetricBinary
    if state.capabilities.maintenance is True:
        yield "maintenance_required", RoombaMetricBinary
    if state.capabilities.dock.recognized is True:
        yield "dock_problem", RoombaMetricBinary
        if state.capabilities.dock.refill is True or state.capabilities.dock.wash is True:
            yield "dock_clean_water", RoombaMetricBinary
        codes = observations(state)
        if any(codes[f"part_{part}"] is not None for part in DOCK_PARTS):
            yield "dock_maintenance_required", RoombaMetricBinary


class RoombaConnected(RoombaEntity, BinarySensorEntity):
    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, robot_id):
        super().__init__(coordinator, robot_id, "connection")

    @property
    def available(self):
        return self.coordinator.last_update_success and self.robot is not None

    @property
    def is_on(self):
        return self.robot.connected if self.robot else None


class RoombaProblem(RoombaConnected):
    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, robot_id):
        RoombaEntity.__init__(self, coordinator, robot_id, "problem")

    @property
    def is_on(self):
        return has_problem(self.robot) if self.robot else None


class RoombaMetricBinary(RoombaEntity, BinarySensorEntity):
    def __init__(self, coordinator, robot_id, key):
        super().__init__(coordinator, robot_id, key, dock=key in DOCK_BINARY_SENSORS)
        self.key = key
        self._attr_translation_key = key
        metric = BY_KEY.get(key)
        if (metric and metric.diagnostic) or key in SOURCE_AVAILABILITY:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if key in {"maintenance_required", *DOCK_BINARY_SENSORS, *PHASE_PROBLEMS}:
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        if not self.robot:
            return None
        if self.key == "ready":
            return self.robot.ready
        if self.key == "mop_attached":
            return self.robot.mop_attached
        if self.key == "preparing_mop":
            return self.robot.preparing_mop
        if self.key == "mission_at_dock":
            return self.robot.mission_at_dock
        if self.key == "mapping":
            return self.robot.mapping
        if self.key in PHASE_PROBLEMS:
            code = observations(self.robot)[self.key]
            return bool(code) if code is not None else None
        if self.key in {"maintenance_required", "dock_maintenance_required"}:
            codes = observations(self.robot)
            parts = DOCK_PARTS if self.key == "dock_maintenance_required" else PARTS
            known = [code for part in parts if (code := codes[f"part_{part}"]) is not None]
            return any(known) if known else None
        if self.key == "dock_problem":
            return dock_has_problem(self.robot)
        if self.key == "dock_clean_water":
            codes = observations(self.robot)
            caps = self.robot.capabilities.dock
            values = [
                codes[key]
                for key, supported in (("refill", caps.refill), ("pad_wash", caps.wash))
                if supported is not False
            ]
            if any(code in {450, 451, 650, 651, 671} for code in values):
                return True
            return None if not values or None in values else False
        return self.robot.telemetry.get(self.key)
