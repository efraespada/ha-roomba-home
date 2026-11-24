"""Restorable problem and mission events for robots and docks."""

from dataclasses import dataclass

from homeassistant.components.event import EventEntity, EventExtraStoredData
from homeassistant.core import callback

from .core.problems import DOCK_PROBLEM_SOURCES, ProblemTracker, observations
from .core.telemetry import integer
from .entity import RoombaEntity, discover_entities


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [RoombaProblemEvent(entry.runtime_data, key, "problems") for key in entry.runtime_data.data]
    )
    discover_entities(entry, async_add_entities, event_candidates)


def event_candidates(state):
    if state.capabilities.dock.recognized is True:
        yield "dock_problems", RoombaProblemEvent
    if state.capabilities.history is True:
        yield "mission_finished", RoombaMissionFinished


class RoombaProblemEvent(RoombaEntity, EventEntity):
    _attr_event_types = ["problem_detected", "problem_changed", "problem_cleared"]

    def __init__(self, coordinator, robot_id, key):
        super().__init__(coordinator, robot_id, key, dock=key == "dock_problems")
        self._attr_translation_key = key
        self.tracker = ProblemTracker()

    @property
    def available(self):
        return (
            self.coordinator.last_update_success
            and self.robot is not None
            and (not self._dock or self.robot.capabilities.dock.recognized is True)
        )

    @property
    def extra_state_attributes(self):
        return {"problem_codes": dict(self.tracker.codes)}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        restored = await self.async_get_last_state()
        self.tracker = ProblemTracker(
            restored.attributes.get("problem_codes") if restored else None
        )
        self._observe()

    @callback
    def _observe(self):
        if self.available:
            values = observations(self.robot)
            if self._dock:
                values = {source: values[source] for source in DOCK_PROBLEM_SOURCES}
            for change in self.tracker.observe(values):
                self._trigger_event(change.event_type, change.attributes())
                self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self):
        self._observe()
        super()._handle_coordinator_update()


@dataclass
class MissionEventStoredData(EventExtraStoredData):
    history_seen: bool
    last_finish: int | None


class RoombaMissionFinished(RoombaEntity, EventEntity):
    _attr_event_types = ["mission_finished"]
    _attr_translation_key = "mission_finished"

    def __init__(self, coordinator, robot_id, key):
        super().__init__(coordinator, robot_id, key)
        self._history_seen = False
        self._last_finish = None

    @property
    def available(self):
        return self.coordinator.last_update_success and self.robot is not None

    @property
    def extra_restore_state_data(self):
        data = super().extra_restore_state_data
        return MissionEventStoredData(
            data.last_event_type,
            data.last_event_attributes,
            self._history_seen,
            self._last_finish,
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if restored := await self.async_get_last_extra_data():
            data = restored.as_dict()
            self._history_seen = data.get("history_seen") is True
            self._last_finish = integer(data.get("last_finish"), 32_503_680_000)
        self._observe()

    @callback
    def _observe(self):
        if not self.available:
            return
        values = self.robot.telemetry
        if values.get("history_available") is not True:
            return
        finished = values.get("last_mission_finished")
        stamp = int(finished.timestamp()) if finished is not None else None
        if not self._history_seen:
            self._history_seen = True
            self._last_finish = stamp
            return
        if stamp is None or (self._last_finish is not None and stamp <= self._last_finish):
            return
        if values.get("last_mission_outcome") is None:
            return
        self._last_finish = stamp
        fields = {
            "outcome": "last_mission_outcome",
            "duration_minutes": "last_mission_duration",
            "area_m2": "last_mission_area",
            "cleaning_modes": "last_mission_modes",
            "error_code": "last_mission_error",
        }
        attributes = {
            key: values[field] for key, field in fields.items() if values.get(field) is not None
        }
        self._trigger_event("mission_finished", attributes)

    @callback
    def _handle_coordinator_update(self):
        self._observe()
        super()._handle_coordinator_update()
