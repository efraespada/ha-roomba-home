"""Vacuum controls backed by verified native commands."""

from homeassistant.components.vacuum import (
    Segment,
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)

from .coordinator import action_error
from .core.cleaning import CleaningMode
from .core.commands import Command
from .entity import RoombaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities([RoombaVacuum(coordinator, key) for key in coordinator.data])


class RoombaVacuum(RoombaEntity, StateVacuumEntity):
    _attr_name = None

    def __init__(self, coordinator, robot_id):
        super().__init__(coordinator, robot_id, "vacuum")

    @property
    def activity(self):
        value = self.robot.activity if self.robot else None
        return VacuumActivity(value) if value else None

    @property
    def supported_features(self):
        features = VacuumEntityFeature.STATE
        if not self.robot:
            return features
        if self.robot.capabilities.cleaning.modes:
            features |= (
                VacuumEntityFeature.START | VacuumEntityFeature.PAUSE | VacuumEntityFeature.STOP
            )
        if self.robot.capabilities.docking is True:
            features |= VacuumEntityFeature.RETURN_HOME
        if self.fan_speed_list:
            features |= VacuumEntityFeature.FAN_SPEED
        if self.robot.capabilities.locate is True:
            features |= VacuumEntityFeature.LOCATE
        if any(item.regions for item in self.account.maps_for_robot(self.robot_id)):
            features |= VacuumEntityFeature.CLEAN_AREA
        return features

    @property
    def fan_speed_list(self):
        maximum = (
            self.robot.capabilities.cleaning.maximum_level("suction_level") if self.robot else 0
        )
        return [str(level) for level in range(1, maximum + 1)]

    @property
    def fan_speed(self):
        if not self.robot:
            return None
        selected = self.account.profile(self.robot_id).suction_level
        value = str(selected if selected is not None else self.robot.telemetry.get("suction_level"))
        return value if value in self.fan_speed_list else None

    async def async_set_fan_speed(self, fan_speed, **kwargs):
        if fan_speed not in self.fan_speed_list:
            raise action_error("unsupported_profile", "Cleaning level is not supported")
        await self.account.async_set_profile(self.robot_id, suction_level=int(fan_speed))

    async def async_get_segments(self):
        maps = self.account.maps_for_robot(self.robot_id)
        return [
            Segment(region.segment_id(item.map_id), region.name or region.region_id, item.name)
            for item in maps
            for region in item.regions
        ]

    async def async_clean_segments(self, segment_ids, **kwargs):
        await self.account.async_command(self.robot_id, Command.VACUUM, segments=segment_ids)

    async def async_clean_point(self, region_id, x, y):
        await self.account.async_clean_point(self.robot_id, region_id, x, y)

    async def async_list_cleaning_regions(self):
        return {
            "regions": [
                {"id": segment.id, "name": segment.name, "map": segment.group}
                for segment in await self.async_get_segments()
            ]
        }

    async def async_list_cleaning_estimates(self, regions):
        return await self.account.async_list_cleaning_estimates(self.robot_id, regions)

    async def async_list_cleaning_schedules(self):
        return await self.account.async_schedule_action(self.robot_id)

    async def async_update_cleaning_schedule(self, schedule_id, weekdays, time):
        return await self.account.async_schedule_action(
            self.robot_id, schedule_id, weekdays=weekdays, time=time
        )

    async def async_set_cleaning_schedule_enabled(self, schedule_id, enabled):
        return await self.account.async_schedule_action(self.robot_id, schedule_id, enabled=enabled)

    async def async_create_cleaning_schedule(self, name, weekdays, time, regions):
        identifiers, overrides = self._region_selections(regions)
        return await self.account.async_create_cleaning_schedule(
            self.robot_id, name, weekdays, time, identifiers, overrides
        )

    async def async_remove_cleaning_schedule(self, schedule_id):
        return await self.account.async_remove_cleaning_schedule(self.robot_id, schedule_id)

    async def async_list_cleaning_routines(self):
        return await self.account.async_list_cleaning_routines(self.robot_id)

    async def async_create_cleaning_routine(self, name, regions):
        return await self.account.async_create_cleaning_routine(
            self.robot_id, name, self._region_selections(regions)
        )

    async def async_update_cleaning_routine(self, routine_id, name=None, regions=None):
        selections = self._region_selections(regions) if regions is not None else None
        return await self.account.async_update_cleaning_routine(
            self.robot_id, routine_id, name, selections
        )

    async def async_remove_cleaning_routine(self, routine_id):
        return await self.account.async_remove_cleaning_routine(self.robot_id, routine_id)

    async def async_clean_regions(self, regions, **kwargs):
        identifiers, overrides = self._region_selections(regions)
        await self.account.async_command(
            self.robot_id, Command.VACUUM, segments=identifiers, overrides=overrides
        )

    async def async_clean_map_selection(self, map_id, version, regions):
        if not self.account.show_maps:
            raise action_error("map_unavailable", "Floor maps are disabled for this account")
        await self.account.async_command(
            self.robot_id, Command.VACUUM, segments=regions, map_revision=(map_id, version)
        )

    @staticmethod
    def _region_selections(regions):
        identifiers = []
        overrides = []
        for region in regions:
            selection = dict(region)
            identifiers.append(selection.pop("id"))
            if "mode" in selection:
                selection["mode"] = CleaningMode(selection["mode"])
            overrides.append(selection)
        return identifiers, overrides

    @property
    def extra_state_attributes(self):
        state = self.robot
        return {
            "mission_phase": state.phase if state else None,
            "mission_cycle": state.cycle if state else None,
            "last_command_result": self.account.command_status.get(self.robot_id),
            "next_cleaning_mode": self.account.profile(self.robot_id).mode.value,
        }

    async def async_start(self):
        await self.account.async_command(self.robot_id, Command.VACUUM)

    async def async_locate(self, **kwargs):
        await self.account.async_command(self.robot_id, Command.LOCATE)

    async def async_pause(self):
        await self.account.async_command(self.robot_id, Command.PAUSE)

    async def async_stop(self, **kwargs):
        await self.account.async_command(self.robot_id, Command.CANCEL)

    async def async_return_to_base(self, **kwargs):
        await self.account.async_command(self.robot_id, Command.DOCK)
