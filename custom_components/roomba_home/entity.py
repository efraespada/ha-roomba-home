"""Shared identity and availability for robot and dock entities."""

from homeassistant.helpers import device_registry
from homeassistant.helpers.typing import UNDEFINED
from homeassistant.helpers.update_coordinator import BaseCoordinatorEntity

from .const import DOMAIN
from .robot_updates import RobotUpdates


def discover_entities(entry, async_add_entities, candidates):
    """Keep discovered entity identities when optional fields later disappear."""
    known = set()

    def discover():
        entities = []
        for robot_id, state in (entry.runtime_data.data or {}).items():
            for key, factory in candidates(state):
                identity = (robot_id, key)
                if identity not in known:
                    known.add(identity)
                    entities.append(factory(entry.runtime_data, robot_id, key))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(entry.runtime_data.async_add_listener(discover))


class RoombaEntity(BaseCoordinatorEntity[RobotUpdates]):
    _attr_has_entity_name = True

    def __init__(self, coordinator, robot_id, suffix, *, dock=False):
        super().__init__(coordinator.robot_updates(robot_id))
        self.account = coordinator
        self.robot_id = robot_id
        self._dock = dock
        entry = coordinator.config_entry
        identifier = f"{entry.unique_id}_{robot_id}"
        self._attr_unique_id = f"{identifier}_{suffix}"
        state = coordinator.data[robot_id]
        robot_info = device_registry.DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            manufacturer="iRobot",
            model=state.sku,
            name=state.name,
            sw_version=state.telemetry.get("software_version"),
            serial_number=coordinator.robot_serial_number(robot_id) or UNDEFINED,
        )
        self._attr_device_info = robot_info
        if dock:
            registry = device_registry.async_get(coordinator.hass)
            parent = registry.async_get_device_by_identifier((DOMAIN, identifier), entry.entry_id)
            if parent is None:
                # Platforms can add dock telemetry before the vacuum entity.
                parent = registry.async_get_or_create_from_info(
                    config_entry_id=entry.entry_id, device_info=robot_info
                )
            self._attr_device_info = device_registry.ChildDeviceInfo(
                identifiers={(DOMAIN, f"{identifier}_dock")},
                parent_device_id=parent.id,
                translation_key="dock",
            )

    @property
    def robot(self):
        return self.coordinator.state

    @property
    def available(self):
        return (
            self.coordinator.last_update_success
            and self.robot is not None
            and self.robot.connected is True
            and (not self._dock or self.robot.capabilities.dock.recognized is True)
        )

    async def async_update(self):
        if self.enabled:
            await self.coordinator.async_request_refresh()
