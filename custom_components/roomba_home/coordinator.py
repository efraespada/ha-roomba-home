"""Account coordinator: serialized MQTT work, polling and command confirmation."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from hashlib import sha256
from itertools import batched
from time import monotonic

from aiohttp import ClientError
from homeassistant.const import CONF_COUNTRY, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ACTIVE_POLL_SECONDS,
    ASSET_REFRESH_SECONDS,
    CONF_PROFILE,
    CONF_SHOW_MAPS,
    DETAIL_SECONDS,
    DOMAIN,
    HISTORY_SECONDS,
    LIVE_MAP_RENEW_SECONDS,
    MAPS_SECONDS,
    PARTS_SECONDS,
    POLL_SECONDS,
    SUPPORTED_SKU,
    selected_robots,
)
from .core.application import (
    PREPARATION_CONFIRMATION_SECONDS,
    ControlError,
    ControlState,
    PreparationConfirmation,
    ReturnConfirmation,
    execute_control,
    mission_commands,
    prepare_control,
    skip_review,
)
from .core.capabilities import supports_point_clean
from .core.cleaning import CleaningCapabilities, CleaningMode, CleaningProfile
from .core.cleaning_protocol import reported_cleaning_mode
from .core.client import MapEditAcknowledgement, RoombaClient, check_status
from .core.commands import Command, MqttCommandSender
from .core.dock import DockSnapshot
from .core.errors import (
    AuthenticationError,
    ProgramSelectionChanged,
    ProtocolError,
    RateLimited,
    RoombaError,
    RoutineNotEditable,
    RoutineUpdateUnconfirmed,
    ScheduleNotEditable,
    ScheduleUpdateUnconfirmed,
)
from .core.floor_settings import prepare_floor_settings, prepare_floor_settings_restore
from .core.furniture_edits import (
    confirm_furniture_edit,
    confirm_furniture_restore,
    prepare_furniture_edit,
    prepare_furniture_restore,
)
from .core.furniture_targets import furniture_regions
from .core.help_catalog import current_help_articles, setup_guide_for
from .core.history import (
    DEFAULT_HISTORY_DAYS,
    ended_mission_start,
    history_includes_mission,
    present_rooms,
    present_zones,
)
from .core.live_coverage import MAX_SAMPLES, LiveCoverage
from .core.live_maps import POSITION_ACTIVITIES, MissionPath, resolve_live_floor
from .core.live_route import (
    RAW_ROUTE_MAX_AGE,
    RawRouteReference,
    decode_raw_snapshot,
    reconcile_live_snapshot,
)
from .core.maintenance import parts_catalog_url, project_part_references
from .core.map_programs import (
    capture_map_programs,
    matching_backup_destinations,
    program_selection,
    review_map_program,
    saved_furniture_destinations,
    saved_zone_destinations,
)
from .core.map_snapshots import capture_snapshot, read_snapshot, with_backup_programs
from .core.maps import SAVED_ZONE_IDS, AreaTarget, CleaningRegion, RegionKind, resolve_segments
from .core.mission_map import read_backed_up_floor, read_mission_map, read_requested_floor
from .core.mission_plan import present_mission_plan
from .core.mission_routes import RouteCaptureKey, captured_geometry
from .core.mission_time import (
    estimate_durations,
    estimate_target,
    remaining_plan_duration,
    with_destination_elapsed,
    with_live_area_elapsed,
)
from .core.models import AppProfile, LoginDetails
from .core.mqtt import MqttProfile, MqttShadowReader, live_map_topic
from .core.point_maps import (
    PointTarget,
    read_floor_plan,
    resolve_room_point,
    with_archive_destinations,
)
from .core.preferences import profile_preferences, restore_profile
from .core.problems import observations
from .core.restriction_edits import (
    confirm_restriction_edit,
    prepare_restriction_edit,
    prepare_restriction_restore,
)
from .core.room_edits import edited_revision, prepare_room_edit, review_room_details
from .core.routine_presets import smart_routine_presets
from .core.schedules import next_schedule_start, once_weekday
from .core.settings_protocol import DEVICE_CONFIGURATION_SETTINGS, RobotSetting
from .core.state import RobotState, project_state
from .core.telemetry import (
    CLEANING_CYCLES,
    DETAIL_SHADOWS,
    FAST_SHADOWS,
    RESETTABLE_PARTS,
    convert,
    integer,
    project_parts,
    project_telemetry,
    reported,
)
from .core.time_estimates import routine_time_estimate
from .core.transport import AiohttpTransport
from .core.voice_catalog import VOICE_INSTALL_TIMEOUT, voice_deployment_id, voice_installation
from .core.zone_edits import (
    confirm_zone_edit,
    confirm_zone_restore,
    prepare_zone_edit,
    prepare_zone_restore,
)
from .live_stream import LiveMapStream, MapWatch, live_map_client
from .map_history import map_history
from .mission_route_store import mission_route_store
from .robot_updates import RobotUpdates

_LOGGER = logging.getLogger(__name__)
TIMELINE_INTERVAL = 45
TIMELINE_MAX_AGE = 100
LIVE_ESTIMATE_RETRY_SECONDS = 60
ROUTE_RETRY_SECONDS = 30


@dataclass(frozen=True)
class PendingHistoryRefresh:
    started: datetime
    due: float
    retried: bool = False


def action_error(key, message):
    return HomeAssistantError(message, translation_domain=DOMAIN, translation_key=key)


class RoombaCoordinator(DataUpdateCoordinator[dict[str, RobotState]]):
    def __init__(self, hass, entry):
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=POLL_SECONDS),
        )
        self.client = RoombaClient(
            AiohttpTransport(async_get_clientsession(hass)),
            LoginDetails(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]),
            AppProfile.from_mapping(entry.data[CONF_PROFILE]),
            entry.data[CONF_COUNTRY],
        )
        self.selected = frozenset(selected_robots(entry))
        self.show_maps = entry.options.get(CONF_SHOW_MAPS) is True
        self._floor_plans = {}
        self._live_paths = {}
        self._live_floor_pins = {}
        self._live_coverage = {}
        self._mission_routes = mission_route_store(hass, entry.entry_id)
        self._live_obstacles = {}
        self._stream_route_references = {}
        self._live_stream = LiveMapStream(
            live_map_client(self.client),
            lambda coro: entry.async_create_background_task(hass, coro, "Roomba live positions"),
            hass.async_add_executor_job,
            self._receive_live_map_sample,
        )
        self._live_route_attempts = {}
        self._live_announcements = {}
        self._live_timelines = {}
        self._live_estimates = {}
        self._timeline_due = {}
        self._cancel_live_expiration = None
        self._io_lock = asyncio.Lock()
        self._command_locks = {robot_id: asyncio.Lock() for robot_id in self.selected}
        self._command_refresh_task = None
        self._closed = False
        self.command_status = {}
        self._deferred_commands: dict[str, PreparationConfirmation | ReturnConfirmation] = {}
        self._command_tasks = set()
        self._sleep = asyncio.sleep
        self._clock = monotonic
        self._details_due = 0
        self._parts_due = 0
        self._assets_due = 0
        self._maps_due = 0
        self._maps_retry_until = 0
        self._estimates_retry_until = 0
        self._history_due = 0
        self._history_retry_until = 0
        self._schedules_due = 0
        self._schedules_retry_until = 0
        self._routines_retry_until = 0
        self._read_failures = 0
        self._read_retry_until = 0
        self._details = {}
        self._parts = {}
        self._assets = {}
        self._part_catalog = {}
        self._maps = {}
        self._maps_available = {}
        self._history = {}
        self._history_pending = {}
        self._schedules = {}
        self.source_status = {}
        self.profiles = {}
        self._robot_updates = {}
        saved = entry.options.get("cleaning_profiles", {})
        if isinstance(saved, dict):
            for robot_id, value in saved.items():
                if robot_id in self.selected:
                    try:
                        self.profiles[robot_id] = restore_profile(value)
                    except ValueError:
                        _LOGGER.debug("Invalid saved cleaning preference discarded")

    def robot_updates(self, robot_id):
        if robot_id not in self._robot_updates:
            self._robot_updates[robot_id] = RobotUpdates(self, robot_id)
        return self._robot_updates[robot_id]

    def robot_serial_number(self, robot_id):
        asset = self._assets.get(robot_id)
        return asset.serial_number if asset is not None else None

    def profile(self, robot_id):
        if robot_id in self.profiles:
            return self.profiles[robot_id]
        state = (self.data or {}).get(robot_id)
        modes = (state.capabilities.cleaning.modes or frozenset()) if state else frozenset()
        mode = (
            CleaningMode.VACUUM
            if CleaningMode.VACUUM in modes or not modes
            else next(mode for mode in CleaningMode if mode in modes)
        )
        return CleaningProfile(mode)

    async def async_set_profile(self, robot_id, **changes):
        state = (self.data or {}).get(robot_id)
        if self._closed or robot_id not in self.selected or state is None:
            raise action_error("not_configured", "Robot is not configured")
        try:
            value = replace(self.profile(robot_id), **changes)
            value.validate(state.capabilities.cleaning)
        except TypeError, ValueError:
            raise action_error("unsupported_profile", "Cleaning profile is not supported") from None
        self.profiles[robot_id] = value
        self._save_profiles()

    async def async_reset_profile(self, robot_id):
        if self._closed or robot_id not in self.selected:
            raise action_error("not_configured", "Robot is not configured")
        self.profiles.pop(robot_id, None)
        self._save_profiles()

    def _save_profiles(self):
        saved = self.config_entry.options.get("cleaning_profiles")
        options = {
            **self.config_entry.options,
            "cleaning_profiles": {
                **(
                    {key: value for key, value in saved.items() if key not in self.selected}
                    if isinstance(saved, dict)
                    else {}
                ),
                **{key: profile_preferences(value) for key, value in self.profiles.items()},
            },
        }
        self.hass.config_entries.async_update_entry(self.config_entry, options=options)
        self.async_update_listeners()

    def _read(
        self,
        session,
        shadows=FAST_SHADOWS,
        live=None,
        positions=None,
        pending=None,
        timelines=None,
        raw_routes=None,
    ):
        documents = {}
        received = False
        failure = None
        for index in range(len(session.raw["connection_tokens"])):
            try:
                profile = MqttProfile.from_session(session, index)
                devices = {
                    k: v
                    for k, v in profile.devices.items()
                    if k in self.selected and session.raw["robots"][k].get("sku") == SUPPORTED_SKU
                }
                if not devices:
                    continue
                reader = MqttShadowReader(replace(profile, devices=devices))
                live_topics = (
                    {live[key]: key for key in devices.keys() & live.keys()} if live else {}
                )
                if live_topics:
                    timeline = (
                        {"timeline_requests": pending, "timelines": timelines} if pending else {}
                    )
                    replies = reader.read(
                        shadows,
                        allow_partial=True,
                        live_topics=live_topics,
                        positions=positions,
                        raw_routes=raw_routes,
                        **timeline,
                    )
                else:
                    replies = reader.read(shadows, allow_partial=True)
            except (OSError, ProtocolError) as error:
                failure = error
                continue
            received = True
            for reply in replies:
                if reply.accepted:
                    documents.setdefault(reply.robot_id, {})[reply.shadow] = reply.document
        if failure is not None and not received:
            raise failure
        return documents

    async def _optional_sources(self, session, now):
        if now >= self._details_due:
            self._details_due = now + DETAIL_SECONDS
            try:
                self._details = await self._executor(self._read, session, DETAIL_SHADOWS)
            except AuthenticationError:
                raise
            except RateLimited as error:
                self._details = {}
                self._details_due = max(self._details_due, now + error.retry_after)
                _LOGGER.debug("Optional shadow refresh rate limited")
            except Exception as error:
                self._details = {}
                _LOGGER.debug("Optional shadow refresh failed: %s", type(error).__name__)
        if now >= self._parts_due:
            self._parts_due = now + PARTS_SECONDS
            self._part_catalog = {}
            try:
                response = await self.client.http.request(
                    "GET",
                    parts_catalog_url(
                        self.client.country, self.hass.config.language, SUPPORTED_SKU
                    ),
                )
                check_status(response)
                if isinstance(response.data, dict):
                    self._part_catalog = response.data
            except Exception as error:
                _LOGGER.debug("Part catalog refresh failed: %s", type(error).__name__)
            self._parts = {}
            for robot_id, details in session.raw["robots"].items():
                if robot_id not in self.selected or details.get("sku") != SUPPORTED_SKU:
                    continue
                try:
                    self._parts[robot_id] = await self.client.robot_parts(robot_id)
                except AuthenticationError:
                    raise
                except RateLimited as error:
                    self._parts_due = max(self._parts_due, now + error.retry_after)
                    _LOGGER.debug("Part refresh rate limited")
                    break
                except Exception as error:
                    _LOGGER.debug("Part refresh failed: %s", type(error).__name__)
        if now >= self._assets_due:
            await self._refresh_robot_assets(session, now)

    async def _refresh_robot_assets(self, session, now):
        self._assets_due = now + ASSET_REFRESH_SECONDS
        for robot_id, details in session.raw["robots"].items():
            if robot_id not in self.selected or details.get("sku") != SUPPORTED_SKU:
                continue
            try:
                async with asyncio.timeout(4):
                    asset = await self.client.robot_asset(robot_id)
            except RateLimited as error:
                self._assets_due = now + error.retry_after
                break
            except Exception as error:
                self._assets_due = min(self._assets_due, now + PARTS_SECONDS)
                _LOGGER.debug("Robot asset refresh failed: %s", type(error).__name__)
                continue
            previous = self._assets.get(robot_id)
            if previous is not None and asset.activation_date is None:
                asset = replace(asset, activation_date=previous.activation_date)
            self._assets[robot_id] = asset
            self._sync_robot_device(robot_id, serial_number=asset.serial_number)

    async def _executor(self, function, *args):
        future = self.hass.async_add_executor_job(function, *args)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # A thread cannot be cancelled: wait for its bounded finally/close.
            await asyncio.shield(future)
            raise

    async def _refresh_maps(self, robots, now):
        previous = self.data or {}
        mapping_ended = any(
            state.cycle == "none"
            and (old := previous.get(robot_id)) is not None
            and old.mapping is True
            for robot_id, state in robots.items()
        )
        mission_ended = self.show_maps and any(
            state.capabilities.persistent_maps is True
            and ended_mission_start(previous.get(robot_id), state) is not None
            for robot_id, state in robots.items()
        )
        if now < self._maps_retry_until or (
            now < self._maps_due and not (mission_ended or mapping_ended)
        ):
            return
        # A floor can be published shortly after the mapping cycle returns to the dock.
        self._maps_due = now + (30 if mapping_ended else MAPS_SECONDS)
        self._maps_available = {
            state.robot_id: False
            for state in robots.values()
            if state.capabilities.persistent_maps is True
        }
        self._maps = {
            key: value for key, value in self._maps.items() if key in self._maps_available
        }
        for robot_id in self._maps_available:
            try:
                await self._read_maps(robot_id)
            except AuthenticationError:
                raise
            except RateLimited as error:
                self._defer_maps(self._clock(), error.retry_after)
                break
            except Exception as error:
                _LOGGER.debug("Map discovery failed: %s", type(error).__name__)

    async def _read_maps(self, robot_id):
        self._maps_available[robot_id] = False
        maps = await self.client.maps(robot_id)
        self._maps[robot_id] = maps
        self._maps_available[robot_id] = True
        valid = {floor.geometry_key for floor in maps}
        for owner_id, geometry_key in tuple(self._floor_plans):
            if owner_id == robot_id and geometry_key not in valid:
                del self._floor_plans[owner_id, geometry_key]
        return maps

    async def _floor_plan(self, robot_id, floor):
        key = (robot_id, floor.geometry_key)
        if key not in self._floor_plans:
            bundle = await self._read_map_action(
                self.client.map_geometry, floor.map_id, floor.version_id
            )
            self._floor_plans[key] = await self._executor(read_floor_plan, bundle, floor)
        return self._floor_plans[key]

    async def async_floor_plan(self, robot_id, floor):
        async with self._io_lock:
            if (
                self._closed
                or not self._maps_available.get(robot_id)
                or floor not in self.maps_for_robot(robot_id)
            ):
                return None
            try:
                return await self._floor_plan(robot_id, floor)
            except RoombaError, HomeAssistantError:
                return None

    async def async_capture_map_backup(self, robot_id, map_id, version, inventory_id, settings_id):
        async with self._io_lock:
            state = (self.data or {}).get(robot_id)
            if (
                self._closed
                or robot_id not in self.selected
                or not self.show_maps
                or state is None
                or state.capabilities.persistent_maps is not True
            ):
                raise action_error("map_unavailable", "Floor maps are unavailable")
            floors = await self._read_map_action(self._read_maps, robot_id)
            floor = next((item for item in floors if item.map_id == map_id), None)
            if (
                floor is None
                or floor.version_id != version
                or floor.inventory_id != inventory_id
                or floor.settings_id != settings_id
            ):
                raise action_error("map_changed", "The map changed. Review the current floor.")
            history = map_history(self.hass, self.config_entry.entry_id)
            return await self._save_map_backup(history, robot_id, floor)

    async def _save_map_backup(self, history, robot_id, floor):
        archive = await self._read_map_action(
            self.client.map_geometry, floor.map_id, floor.version_id
        )
        try:
            record, plan = await self._executor(capture_snapshot, floor, archive, datetime.now(UTC))
            sources, unchecked = await self._read_map_programs(
                robot_id, {"routine", "schedule"}, floor_id=floor.map_id
            )
            programs = capture_map_programs(floor, plan, sources, unchecked)
            if programs["items"] or programs["unchecked"]:
                record = await self._executor(with_backup_programs, record, archive, programs)
            return await history.async_capture(robot_id, record)
        except ProtocolError as error:
            raise HomeAssistantError(str(error)) from None

    async def _back_up_before_edit(self, robot_id, floor):
        history = map_history(self.hass, self.config_entry.entry_id)
        try:
            if await history.async_automatic(robot_id):
                await self._save_map_backup(history, robot_id, floor)
        except AuthenticationError:
            raise
        except ProtocolError, HomeAssistantError, OSError:
            raise HomeAssistantError(
                "The automatic map backup failed. Check Map backups before retrying."
            ) from None

    async def async_edit_rooms(
        self,
        robot_id,
        map_id,
        version,
        _inventory_id,
        operation,
        room_ids,
        points,
        name=None,
        room_type=None,
    ):
        active, _ = await self._edit_map(
            robot_id,
            map_id,
            version,
            # Room edits use the active archive even if Roomba's room inventory is still syncing.
            None,
            lambda _floor, plan: prepare_room_edit(
                plan, operation, room_ids, points, name, room_type
            ),
            edited_revision,
        )
        return {"version": active.version_id}

    async def async_edit_zones(
        self, robot_id, map_id, version, inventory_id, operation, zone_id, name, bounds
    ):
        active, edit = await self._edit_map(
            robot_id,
            map_id,
            version,
            inventory_id,
            lambda floor, plan: prepare_zone_edit(floor, plan, operation, zone_id, name, bounds),
            confirm_zone_edit,
        )
        return {
            "version": active.version_id,
            "destination_available": edit.name is not None
            if edit.zone_id in SAVED_ZONE_IDS
            else any(
                region.kind is RegionKind.ZONE and region.region_id == edit.zone_id
                for region in active.regions
            ),
        }

    async def async_edit_restrictions(
        self, robot_id, map_id, version, inventory_id, operation, zone_id, kind, bounds
    ):
        active, _ = await self._edit_map(
            robot_id,
            map_id,
            version,
            inventory_id,
            lambda _floor, plan: prepare_restriction_edit(plan, operation, zone_id, kind, bounds),
            confirm_restriction_edit,
        )
        return {"version": active.version_id}

    async def async_edit_furniture(
        self, robot_id, map_id, version, inventory_id, operation, identifier, kind, pose
    ):
        active, _ = await self._edit_map(
            robot_id,
            map_id,
            version,
            inventory_id,
            lambda _floor, plan: prepare_furniture_edit(plan, operation, identifier, kind, pose),
            confirm_furniture_edit,
        )
        return {"version": active.version_id}

    async def _editable_floor(self, robot_id, map_id, version, inventory_id):
        state = (self.data or {}).get(robot_id)
        if (
            self._closed
            or robot_id not in self.selected
            or not self.show_maps
            or not self.last_update_success
            or state is None
            or state.capabilities.persistent_maps is not True
        ):
            raise HomeAssistantError("Map editing is unavailable.")
        if (
            state.connected is not True
            or state.cycle != "none"
            or state.activity not in {"idle", "docked"}
        ):
            raise HomeAssistantError("Finish the active mission before editing the map.")
        floors = await self._read_map_action(self._read_maps, robot_id)
        floor = next((item for item in floors if item.map_id == map_id), None)
        if (
            floor is None
            or floor.version_id != version
            or (inventory_id is not None and floor.inventory_id != inventory_id)
        ):
            raise action_error("map_changed", "The map changed. Review your selection.")
        return floor

    async def async_edit_floor_settings(
        self, robot_id, map_id, version, inventory_id, operation, settings_id, name, quarter_turns
    ):
        async with self._io_lock:
            floor = await self._reviewed_settings_floor(
                robot_id, map_id, version, inventory_id, settings_id
            )
            try:
                edit = prepare_floor_settings(floor, operation, name, quarter_turns)
            except ValueError as error:
                raise HomeAssistantError(str(error)) from None
            if edit.matches(floor, floor):
                return
            await self._back_up_before_edit(robot_id, floor)
            await self._write_floor_settings(robot_id, floor, edit)

    async def async_restore_map_settings(
        self, robot_id, backup_id, map_id, version, inventory_id, settings_id, *, confirmed=False
    ):
        async with self._io_lock:
            history = map_history(self.hass, self.config_entry.entry_id)
            record = await history.async_read(robot_id, backup_id)
            saved, plan = await self._executor(read_snapshot, record)
            if plan.source_format != "picea":
                raise HomeAssistantError("Floor settings are unavailable for this backup format.")
            floor = await self._reviewed_settings_floor(
                robot_id, map_id, version, inventory_id, settings_id
            )
            try:
                edit = prepare_floor_settings_restore(floor, saved)
            except ValueError as error:
                raise HomeAssistantError(str(error)) from None
            changes = {
                key: {"from": getattr(floor, key), "to": value}
                for key in ("name", "orientation")
                if (value := getattr(edit, key)) is not None
            }
            if confirmed and changes:
                await self._back_up_before_edit(robot_id, floor)
                active = await self._reviewed_settings_floor(
                    robot_id, map_id, version, inventory_id, settings_id
                )
                await self._write_floor_settings(robot_id, active, edit)
            return {"changes": changes, "applied": confirmed and bool(changes)}

    async def async_restore_map_zones(
        self,
        robot_id,
        backup_id,
        map_id,
        version,
        inventory_id,
        settings_id,
        *,
        confirmed=False,
        review_id=None,
    ):
        return await self._restore_map_geometry(
            robot_id,
            backup_id,
            map_id,
            version,
            inventory_id,
            settings_id,
            prepare_zone_restore,
            confirm_zone_restore,
            confirmed,
            review_id,
            RegionKind.ZONE,
        )

    async def async_restore_map_room_details(
        self,
        robot_id,
        backup_id,
        map_id,
        version,
        inventory_id,
        settings_id,
        *,
        confirmed=False,
        room_id=None,
        review_id=None,
    ):
        async with self._io_lock:
            history = map_history(self.hass, self.config_entry.entry_id)
            record = await history.async_read(robot_id, backup_id)
            saved, archived = await self._executor(read_snapshot, record)
            if saved.map_id != map_id:
                raise HomeAssistantError("Select the active floor for this backup.")
            scope = (map_id, version, inventory_id, settings_id)
            floor = await self._reviewed_settings_floor(robot_id, *scope)
            plan = await self._floor_plan(robot_id, floor)
            try:
                entries = await self._executor(review_room_details, archived, plan)
            except ValueError as error:
                raise HomeAssistantError(str(error)) from None
            ready = {}
            for row, edit in entries:
                if edit is not None:
                    authorized = sha256(
                        json.dumps(
                            {
                                "backup": backup_id,
                                "floor": scope,
                                "room": row,
                            },
                            sort_keys=True,
                        ).encode()
                    ).hexdigest()
                    row["review_id"] = authorized
                    ready[row["id"]] = (authorized, edit)
            if not confirmed:
                return {"rooms": [row for row, _ in entries], "applied": False}
            selected = ready.get(room_id)
            if selected is None or selected[0] != review_id:
                raise action_error(
                    "map_changed", "The room recovery review changed. Open it again."
                )
            await self._back_up_before_edit(robot_id, floor)
            active = await self._reviewed_settings_floor(robot_id, *scope)
            await self._write_map_edit(robot_id, active, plan, selected[1], edited_revision)
            return {"applied": True}

    async def async_restore_map_restrictions(
        self,
        robot_id,
        backup_id,
        map_id,
        version,
        inventory_id,
        settings_id,
        *,
        confirmed=False,
        review_id=None,
    ):
        return await self._restore_map_geometry(
            robot_id,
            backup_id,
            map_id,
            version,
            inventory_id,
            settings_id,
            prepare_restriction_restore,
            confirm_restriction_edit,
            confirmed,
            review_id,
        )

    async def async_restore_map_furniture(
        self,
        robot_id,
        backup_id,
        map_id,
        version,
        inventory_id,
        settings_id,
        *,
        confirmed=False,
        review_id=None,
    ):
        return await self._restore_map_geometry(
            robot_id,
            backup_id,
            map_id,
            version,
            inventory_id,
            settings_id,
            prepare_furniture_restore,
            confirm_furniture_restore,
            confirmed,
            review_id,
            RegionKind.FURNITURE,
        )

    async def _restore_map_geometry(
        self,
        robot_id,
        backup_id,
        map_id,
        version,
        inventory_id,
        settings_id,
        prepare,
        confirm,
        confirmed,
        review_id,
        dependency_kind=None,
    ):
        async with self._io_lock:
            history = map_history(self.hass, self.config_entry.entry_id)
            record = await history.async_read(robot_id, backup_id)
            saved, archived = await self._executor(read_snapshot, record)
            if saved.map_id != map_id:
                raise HomeAssistantError("Select the active floor for this backup.")
            floor = await self._reviewed_settings_floor(
                robot_id, map_id, version, inventory_id, settings_id
            )
            plan = await self._floor_plan(robot_id, floor)
            try:
                edit = prepare(archived, plan)
            except ValueError as error:
                raise HomeAssistantError(str(error)) from None
            changes = edit.changes(plan)
            preview = {"changes": changes}
            if dependency_kind is not None:
                linked, unchecked = await self._map_restore_dependencies(
                    robot_id, map_id, dependency_kind, changes
                )
                preview.update(dependencies=linked, unchecked=unchecked)
            digest = sha256(
                json.dumps(
                    {
                        "preview": preview,
                        "backup": backup_id,
                        "edit": asdict(edit),
                        "floor": (map_id, version, inventory_id, settings_id),
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            if not confirmed or not changes:
                return {**preview, "review_id": digest, "applied": False}
            if review_id != digest:
                raise action_error(
                    "map_changed", "The map recovery review changed. Review it again."
                )
            await self._back_up_before_edit(robot_id, floor)
            active = await self._reviewed_settings_floor(
                robot_id, map_id, version, inventory_id, settings_id
            )
            await self._write_map_edit(robot_id, active, plan, edit, confirm)
            return {**preview, "review_id": digest, "applied": True}

    async def _map_restore_dependencies(self, robot_id, map_id, region_kind, changes):
        if not changes:
            return [], []
        targets = {f"{map_id}:{region_kind}:{row['id']}": row["id"] for row in changes}
        key = "zones" if region_kind is RegionKind.ZONE else "objects"
        sources, unchecked = await self._read_map_programs(robot_id, {"routine", "schedule"})
        dependencies = []
        for kind, programs in sources.items():
            if any(not row.get("regions") for row in programs):
                unchecked.append(kind)
            for row in programs:
                linked = sorted(
                    targets[region] for region in (row.get("regions") or ()) if region in targets
                )
                if linked:
                    dependencies.append({"kind": kind, "name": row.get("name"), key: linked})
        dependencies.sort(key=lambda item: (item["kind"], item["name"] or "", item[key]))
        return dependencies, sorted(unchecked)

    async def _read_map_programs(self, robot_id, kinds, *, floor_id=None):
        sources, unchecked = {}, []
        filters = {"floor_id": floor_id} if floor_id is not None else {}
        for kind, read, retry_field in (
            ("routine", self.client.list_cleaning_routines, "_routines_retry_until"),
            ("schedule", self.client.list_cleaning_schedules, "_schedules_retry_until"),
        ):
            if kind not in kinds:
                continue
            if self._clock() < getattr(self, retry_field):
                unchecked.append(kind)
                continue
            try:
                async with asyncio.timeout(5):
                    sources[kind] = await read(robot_id, **filters)
            except AuthenticationError:
                raise
            except RateLimited as error:
                setattr(self, retry_field, self._clock() + error.retry_after)
                unchecked.append(kind)
            except RoombaError, ClientError, OSError:
                unchecked.append(kind)
        return sources, unchecked

    async def async_restore_map_programs(
        self,
        robot_id,
        backup_id,
        map_id,
        version,
        inventory_id,
        settings_id,
        *,
        confirmed=False,
        kind=None,
        program_id=None,
        review_id=None,
    ):
        async with self._io_lock:
            history = map_history(self.hass, self.config_entry.entry_id)
            record = await history.async_read(robot_id, backup_id)
            saved, archived = await self._executor(read_snapshot, record)
            if saved.map_id != map_id:
                raise HomeAssistantError("Select the active floor for this backup.")
            floor = await self._reviewed_settings_floor(
                robot_id, map_id, version, inventory_id, settings_id
            )
            backup = record.get("programs", {"items": [], "unchecked": []})
            sources, unchecked = await self._read_map_programs(
                robot_id, {item["kind"] for item in backup["items"]}
            )
            plan = await self._floor_plan(robot_id, floor)
            current_areas = saved_zone_destinations(
                floor.map_id, plan
            ) | saved_furniture_destinations(floor.map_id, plan)
            saved_areas = saved_zone_destinations(
                saved.map_id, archived
            ) | saved_furniture_destinations(saved.map_id, archived)
            matching = matching_backup_destinations(archived, plan, saved_areas, current_areas)
            destinations = with_archive_destinations(floor, plan)
            destinations = replace(
                destinations, regions=(*destinations.regions, *furniture_regions(plan))
            )
            capabilities = self.data[robot_id].capabilities.cleaning
            reviews, ready = [], {}
            for item in backup["items"]:
                source, identity = item["kind"], item["id"]
                current = next(
                    (row for row in sources.get(source, ()) if row["id"] == identity), None
                )
                if source in unchecked:
                    status, target, areas = "source_unavailable", None, []
                else:
                    status, target, areas = review_map_program(
                        item, current, saved_areas, matching, destinations, capabilities
                    )
                review = {
                    "kind": source,
                    "id": identity,
                    "name": current["name"] if current is not None else item["name"],
                    "ordered": item["ordered"],
                    "status": status,
                    "destinations": areas,
                }
                if target is not None:
                    digest = sha256(
                        json.dumps(
                            {
                                "backup": backup_id,
                                "floor": (map_id, version, inventory_id, settings_id),
                                "program": review,
                            },
                            sort_keys=True,
                        ).encode()
                    ).hexdigest()
                    review["review_id"] = digest
                    ready[source, identity] = (digest, target, program_selection(current))
                reviews.append(review)
            if not confirmed:
                return {"programs": reviews, "unchecked": backup["unchecked"], "applied": False}
            selected = ready.get((kind, program_id))
            if selected is None or selected[0] != review_id:
                raise action_error("map_changed", "The program recovery changed. Review it again.")
            await self._reviewed_settings_floor(
                robot_id, map_id, version, inventory_id, settings_id
            )
            return await self._restore_backup_program(robot_id, kind, program_id, *selected[1:])

    async def _restore_backup_program(self, robot_id, kind, program_id, target, expected):
        try:
            if kind == "routine":
                await self.client.update_cleaning_routine(
                    robot_id, program_id, None, target, expected_selection=expected
                )
            else:
                self._schedules_due = min(self._schedules_due, self._clock())
                await self.client.update_cleaning_schedule(
                    robot_id, program_id, target=target, expected_selection=expected
                )
        except AuthenticationError:
            raise
        except ProgramSelectionChanged:
            raise action_error("map_changed", "The program changed. Review it again.") from None
        except RateLimited as error:
            if kind == "routine":
                self._routines_retry_until = self._clock() + error.retry_after
            else:
                self._schedules_retry_until = self._clock() + error.retry_after
            raise HomeAssistantError("Roomba rate limited this update. Try again later.") from None
        except RoombaError, ClientError, OSError:
            raise HomeAssistantError(
                "The program update could not be confirmed. Open it again to check."
            ) from None
        return {"applied": True}

    async def _reviewed_settings_floor(self, robot_id, map_id, version, inventory_id, settings_id):
        floor = await self._editable_floor(robot_id, map_id, version, inventory_id)
        if floor.settings_id != settings_id:
            raise action_error("map_changed", "The floor settings changed. Open the editor again.")
        plan = await self._floor_plan(robot_id, floor)
        if plan.source_format != "picea":
            raise HomeAssistantError("Floor settings are unavailable for this map format.")
        return floor

    async def _write_floor_settings(self, robot_id, floor, edit):
        self._maps_due = min(self._maps_due, self._clock())
        # Only the map-list reads may be retried if the write result is lost.
        with suppress(HomeAssistantError):
            await self._read_map_action(self.client.update_floor_settings, robot_id, floor, edit)
        try:
            for delay in (0, 0.5, 1.5):
                if delay:
                    await asyncio.sleep(delay)
                floors = await self._read_map_action(self._read_maps, robot_id)
                active = next((item for item in floors if item.map_id == floor.map_id), None)
                if active is None or active.geometry_key != floor.geometry_key:
                    break
                if edit.matches(floor, active):
                    self.async_update_listeners()
                    return
        except HomeAssistantError:
            pass
        raise HomeAssistantError(
            "Save could not be confirmed. Refresh the map before trying again."
        )

    async def _floor_for_removal(self, robot_id, map_id, version, inventory_id, settings_id):
        floor = await self._editable_floor(robot_id, map_id, version, inventory_id)
        if floor.settings_id != settings_id:
            raise action_error("map_changed", "The floor settings changed. Review the map again.")
        return floor

    async def async_review_floor_removal(
        self, robot_id, map_id, version, inventory_id, settings_id
    ):
        async with self._io_lock:
            floor = await self._floor_for_removal(
                robot_id, map_id, version, inventory_id, settings_id
            )
            sources, unchecked = await self._read_map_programs(
                robot_id, {"routine", "schedule"}, floor_id=floor.map_id
            )
        programs = []
        for kind, rows in sources.items():
            for row in rows:
                item = {"kind": kind, "name": row.get("name")}
                if kind == "schedule":
                    item["enabled"] = row["enabled"]
                programs.append(item)
        return {"programs": programs, "unchecked": unchecked}

    async def async_remove_floor(
        self, robot_id, map_id, version, inventory_id, settings_id, remap=False
    ):
        async with self._robot_operation(robot_id):
            if not remap:
                await self._remove_floor(robot_id, map_id, version, inventory_id, settings_id)
                return
            adapter = RobotControlAdapter(self, robot_id)
            profile = self.profile(robot_id)
            try:
                prepare_control(Command.START_MAPPING, await adapter.refresh(), profile)
            except ControlError as error:
                raise action_error(error.key, error.key) from None
            await self._remove_floor(robot_id, map_id, version, inventory_id, settings_id)
            try:
                await execute_control(adapter, Command.START_MAPPING, profile)
            except AuthenticationError, ControlError:
                raise action_error(
                    "floor_removed_mapping_unconfirmed",
                    "Roomba removed the floor. The replacement mapping run was not confirmed.",
                ) from None

    async def _remove_floor(self, robot_id, map_id, version, inventory_id, settings_id):
        async with self._io_lock:
            floor = await self._floor_for_removal(
                robot_id, map_id, version, inventory_id, settings_id
            )
            await self._back_up_before_edit(robot_id, floor)
            self._maps_due = min(self._maps_due, self._clock())
            # A timed-out write may still have reached Roomba. Check the list without retrying it.
            with suppress(HomeAssistantError):
                await self._read_map_action(self.client.remove_floor, map_id)
            try:
                for delay in (0, 1, 2):
                    await self._sleep(delay)
                    floors = await self._read_map_action(self._read_maps, robot_id)
                    if all(item.map_id != map_id for item in floors):
                        self.data[robot_id] = self._add_map_capabilities(self.data[robot_id])
                        self.async_update_listeners()
                        return
            except HomeAssistantError:
                pass
            raise HomeAssistantError("Removal could not be confirmed. Refresh the floor list.")

    async def _edit_map(self, robot_id, map_id, version, inventory_id, prepare, confirm):
        async with self._io_lock:
            floor = await self._editable_floor(robot_id, map_id, version, inventory_id)
            plan = await self._floor_plan(robot_id, floor)
            try:
                edit = prepare(floor, plan)
            except ValueError as error:
                raise HomeAssistantError(str(error)) from None
            await self._back_up_before_edit(robot_id, floor)
            active = await self._write_map_edit(robot_id, floor, plan, edit, confirm)
            return active, edit

    async def _write_map_edit(self, robot_id, floor, plan, edit, confirm):
        self._maps_due = min(self._maps_due, self._clock())
        try:
            response = await self._read_map_action(self.client.edit_map, floor.map_id, edit)
            needs_archive = isinstance(response, MapEditAcknowledgement)
            edited = (
                response.version
                if needs_archive
                else await self._executor(confirm, response, floor, plan, edit)
            )
            for delay in (0, 0.5, 1.5):
                if delay:
                    await asyncio.sleep(delay)
                floors = await self._read_map_action(self._read_maps, robot_id)
                active = next((item for item in floors if item.map_id == floor.map_id), None)
                if active and active.version_id == edited:
                    if needs_archive:
                        archive = await self._read_map_action(
                            self.client.map_geometry, active.map_id, edited
                        )
                        if await self._executor(confirm, archive, floor, plan, edit) != edited:
                            break
                    self.async_update_listeners()
                    return active
                if active is None or active.version_id != floor.version_id:
                    break
        except HomeAssistantError, ProtocolError:
            pass
        raise HomeAssistantError(
            "Save could not be confirmed. Refresh the map before trying again."
        )

    def live_path(self, robot_id):
        return self._live_paths.get(robot_id)

    def live_coverage_rows(self, robot_id, path):
        scope, coverage = self._live_coverage.get(robot_id, (None, None))
        if path is not None and scope == (path.started, path.map_version):
            return coverage.rows()
        return {}

    def live_obstacles(self, robot_id, path, now):
        scope, timestamp, points = self._live_obstacles.get(robot_id, (None, 0, ()))
        if (
            path is not None
            and scope == (path.started, path.map_version)
            and now.timestamp() < timestamp + RAW_ROUTE_MAX_AGE
        ):
            return points
        return ()

    def _record_live_coverage(self, robot_id, path, points):
        requested = path.started, path.map_version
        scope, coverage = self._live_coverage.get(robot_id, (None, None))
        if requested != scope:
            coverage = LiveCoverage()
            self._live_coverage[robot_id] = requested, coverage
        coverage.observe(points)

    async def _checkpoint_mission_route(self, state, path, now, *, final=False):
        if state is None or path.started != state.telemetry.get("mission_started"):
            return
        number = integer(state.telemetry.get("mission_number"))
        robot_id = state.robot_id
        scope, coverage = self._live_coverage.get(robot_id, (None, None))
        if number is None or scope != (path.started, path.map_version):
            return
        try:
            await self._mission_routes.async_checkpoint(
                robot_id,
                RouteCaptureKey(path.started, number, path.map_version),
                now.timestamp(),
                coverage.samples(),
                final=final,
            )
        except OSError, ProtocolError:
            _LOGGER.debug("Local Roomba mission route checkpoint failed")

    def live_point(self, robot_id, now):
        state = (self.data or {}).get(robot_id)
        if state is None:
            return None
        report = self._current_timeline(state, now)
        if report is None or report.point is None:
            return None
        return report.point, report.observed_at.timestamp() + TIMELINE_MAX_AGE

    def live_plan(self, state, floor, now):
        report = self._current_timeline(state, now)
        if (
            report is None
            or report.plan is None
            or report.plan.scope != (floor.map_id, floor.version_id)
        ):
            return None
        plan = state.telemetry.get("live_timeline_plan")
        if plan is None:
            return None
        stage = self._estimate_stage(state, report)
        started = self._live_mission(state)
        stage_started = self._stage_started_during_mission(report, started, now)
        plan = self._plan_with_elapsed(plan, report, state, started, stage_started, now)
        if "estimated_remaining_seconds" in plan:
            plan = {
                **plan,
                "estimated_remaining_seconds": remaining_plan_duration(
                    plan, stage, stage_started, now
                ),
            }
        return with_live_area_elapsed(plan, stage, stage_started, now)

    @staticmethod
    def _estimate_stage(state, report):
        if report.stage == "pause":
            return "pause" if state.activity == "paused" else None
        return report.stage if state.phase == "run" else None

    @staticmethod
    def _plan_with_elapsed(plan, report, state, started, stage_started, now):
        interval = None
        stage = RoombaCoordinator._estimate_stage(state, report)
        area = None
        if stage == "room" and stage_started is not None:
            area = report.running_room(stage_started)
        elif stage == "zone" or (stage == "pause" and report.active_zones):
            area = report.timed_destination(stage_started)
        if area is not None:
            until = stage_started if stage == "pause" else now
            interval = (area, int(until.timestamp()))
        return with_destination_elapsed(
            plan,
            report.timing.elapsed(
                report.plan, started, now, interval, observed_rooms=report.room_timing
            ),
        )

    @staticmethod
    def _stage_started_during_mission(report, started, now):
        stage_started = report.stage_started_at
        return (
            stage_started if stage_started is not None and started <= stage_started <= now else None
        )

    @staticmethod
    def _live_mission(state):
        if (
            state.connected is True
            and state.cycle in CLEANING_CYCLES
            and (
                state.activity in {"cleaning", "paused", "returning"}
                or state.mission_at_dock is True
            )
        ):
            return state.telemetry.get("mission_started")
        return None

    async def _live_topics(self, session):
        topics = {}
        for key, state in (self.data or {}).items():
            started = self._live_mission(state)
            if not started or key not in session.raw["robots"] or not self.maps_for_robot(key):
                self._live_announcements.pop(key, None)
                continue
            topic = live_map_topic(session, key)
            if not topic:
                self._live_announcements.pop(key, None)
                continue
            scope = started, topic
            previous, retry_at, authorized = self._live_announcements.get(key, (None, 0, False))
            if previous != scope or self._clock() >= retry_at:
                authorized = previous == scope and authorized
                retry_at = self._clock() + POLL_SECONDS
                try:
                    async with asyncio.timeout(3):
                        announced = await self.client.live_map_topic(key)
                except RateLimited as error:
                    retry_at = max(retry_at, self._clock() + error.retry_after)
                except AuthenticationError:
                    authorized = False
                except RoombaError, OSError, TimeoutError:
                    pass
                else:
                    authorized = announced == topic
                    if authorized:
                        retry_at = self._clock() + LIVE_MAP_RENEW_SECONDS
                self._live_announcements[key] = (scope, retry_at, authorized)
            if authorized:
                topics[key] = topic
        return topics

    def _timeline_requests(self, topics, now):
        requests = {}
        for key in topics:
            state = self.data[key]
            number = state.telemetry.get("mission_number")
            started = self._live_mission(state)
            previous, due = self._timeline_due.get(key, (None, 0))
            if number is not None and (previous != started or now >= due):
                requests[key] = number
                self._timeline_due[key] = (started, now + TIMELINE_INTERVAL)
        return requests

    async def _timeline_metrics(self, state, report, now):
        key = state.robot_id
        started = self._live_mission(state)
        number = state.telemetry.get("mission_number")
        if not started:
            self._live_timelines.pop(key, None)
            self._live_estimates.pop(key, None)
            self._timeline_due.pop(key, None)
            return {}
        if report is not None and report.mission_number == number:
            previous = self._current_timeline(state)
            if previous is not None and report.plan == previous.plan:
                report = replace(report, room_timing=previous.room_timing)
            self._live_timelines[key] = (started, report)
        recent = self._current_timeline(state, now)
        if recent is None:
            return {}
        maps = self.maps_for_robot(key)
        destinations = recent.plan.destinations if recent.plan else ()
        zone_maps = await self._zone_label_maps(
            key, (*recent.zones, *recent.active_zones, *destinations)
        )
        stage_started = self._stage_started_during_mission(recent, started, now)
        observed = recent.observe_room_timing(
            self._estimate_stage(state, recent), started, stage_started
        )
        if observed is not recent:
            recent = observed
            self._live_timelines[key] = (started, recent)
        active_zone = recent.timed_destination(stage_started) if recent.stage == "zone" else None
        metrics = {
            "live_timeline_updated": recent.observed_at,
            "live_timeline_stage": recent.stage,
            "live_timeline_stage_started": (
                stage_started.isoformat() if stage_started is not None else None
            ),
            "live_timeline_rooms": present_rooms(recent.rooms, maps),
            "live_timeline_active_rooms": present_rooms(recent.active_rooms, maps),
            "live_timeline_zones": present_zones(recent.zones, zone_maps),
            "live_timeline_active_zones": present_zones(
                recent.active_zones, zone_maps, active=active_zone
            ),
        }
        if recent.plan is not None:
            active = {"room": recent.active_rooms, "zone": recent.active_zones}
            paused = recent.stage == "pause"
            if paused and (paused_area := recent.timed_destination(stage_started)) is not None:
                active["pause"] = (paused_area,)
            plan = present_mission_plan(
                recent.plan,
                (*recent.rooms, *recent.zones),
                active.get(recent.stage, ()),
                recent.travelling_to,
                zone_maps,
                paused=paused,
                active_pass=active_zone,
            )
            metrics.update(
                live_timeline_plan=plan,
                live_destinations_completed=plan["completed"],
            )
            if (
                durations := await self._live_room_estimates(state, started, recent, maps)
            ) is not None:
                for destination, seconds in zip(plan["destinations"], durations, strict=True):
                    if seconds is not None:
                        destination["estimated_duration_seconds"] = seconds
                if all(seconds is not None for seconds in durations):
                    plan["estimated_duration_seconds"] = sum(durations)
                remaining = remaining_plan_duration(
                    self._plan_with_elapsed(plan, recent, state, started, stage_started, now),
                    self._estimate_stage(state, recent),
                    stage_started,
                    now,
                )
                plan["estimated_remaining_seconds"] = remaining
                metrics["live_estimated_remaining"] = remaining
        return metrics

    async def _live_room_estimates(self, state, started, report, maps):
        robot_id = state.robot_id
        plan = report.plan
        floor = next((item for item in maps if (item.map_id, item.version_id) == plan.scope), None)
        if floor is None or (target := estimate_target(plan, floor)) is None:
            return None
        scope = started, report.mission_number, plan
        clock = self._clock()
        previous, retry_at, cached = self._live_estimates.get(robot_id, (None, 0, None))
        if scope == previous and (cached is not None or clock < retry_at):
            return cached
        if clock < self._estimates_retry_until:
            return None
        self._live_estimates[robot_id] = scope, clock + LIVE_ESTIMATE_RETRY_SECONDS, None
        try:
            async with asyncio.timeout(5):
                matrix = await self.client.cleaning_time_estimates(
                    robot_id, target, state.capabilities.cleaning
                )
                current = await self.client.maps(robot_id)
        except RateLimited as error:
            self._estimates_retry_until = max(
                self._estimates_retry_until, clock + error.retry_after
            )
            return None
        except Exception as error:
            _LOGGER.debug("Live room estimate unavailable: %s", type(error).__name__)
            return None
        if not any((item.map_id, item.version_id) == plan.scope for item in current):
            return None
        reading = routine_time_estimate(target, matrix, self._estimate_defaults(state))
        cached = estimate_durations(plan, reading)
        self._live_estimates[robot_id] = scope, 0, cached
        return cached

    def _current_timeline(self, state, now=None):
        """Read the same mission's timeline, optionally requiring fresh telemetry."""
        started, report = self._live_timelines.get(state.robot_id, (None, None))
        if (
            report is not None
            and started == self._live_mission(state)
            and report.mission_number == state.telemetry.get("mission_number")
            and (now is None or (now - report.observed_at).total_seconds() <= TIMELINE_MAX_AGE)
        ):
            return report
        return None

    def _skip_review(self, robot_id):
        state = (self.data or {}).get(robot_id)
        if state is None or not self.last_update_success:
            return None
        timeline = self._current_timeline(state, datetime.now(UTC))
        return skip_review(control_snapshot(state, timeline))

    def skip_review_for_robot(self, robot_id):
        return _skip_review_id(self._skip_review(robot_id))

    def _zone_labels_from_archive(self, robot_id, floor):
        plan = self._floor_plans.get((robot_id, floor.geometry_key))
        if plan is None:
            return floor
        regions = {(region.kind, region.region_id): region for region in floor.regions}
        for zone in plan.zone_outlines:
            if zone.region_id and zone.name:
                regions[RegionKind.ZONE, zone.region_id] = CleaningRegion(
                    zone.region_id, RegionKind.ZONE, zone.name
                )
        return replace(floor, regions=(*regions.values(), *furniture_regions(plan)))

    async def _zone_label_maps(self, robot_id, zones):
        maps = self.maps_for_robot(robot_id) if self.show_maps else ()
        revisions = {
            zone.identity[:2] for zone in zones if zone.kind in {"furniture", "saved_zone"}
        }
        associated = {floor.map_id: floor for floor in maps}
        labeled = list(maps)
        for map_id, version in revisions:
            if (floor := associated.get(map_id)) is None:
                continue
            if floor.version_id != version:
                # Historical labels come from that archive, even if the target was removed.
                floor = replace(floor, version_id=version, regions=())
                labeled.append(floor)
            with suppress(HomeAssistantError, RoombaError):
                await self._floor_plan(robot_id, floor)
        return tuple(self._zone_labels_from_archive(robot_id, floor) for floor in labeled)

    async def _recover_live_route(self, key, path, reference, now):
        if reference is None:
            return path
        if (
            not max(path.started.timestamp(), now.timestamp() - RAW_ROUTE_MAX_AGE)
            <= reference.timestamp
            <= now.timestamp()
        ):
            return path
        scope = path.started, path.map_version
        layer_scope, timestamp, _ = self._live_obstacles.get(key, (None, 0, ()))
        if scope == layer_scope and reference.timestamp <= timestamp:
            return path
        previous_scope, retry_at = self._live_route_attempts.get(key, (None, 0))
        elapsed = self._clock()
        if scope == previous_scope and elapsed < retry_at:
            return path
        self._live_route_attempts[key] = scope, elapsed + ROUTE_RETRY_SECONDS
        try:
            async with asyncio.timeout(4):
                archive = await self.client.raw_live_route(reference)
            snapshot = await self._executor(decode_raw_snapshot, archive, MAX_SAMPLES)
        except RoombaError, OSError, TimeoutError:
            return path
        path, supplement, obstacles = await self._executor(reconcile_live_snapshot, path, snapshot)
        if obstacles is not None:
            self._live_obstacles[key] = scope, reference.timestamp, obstacles
        for points in batched(supplement, 64, strict=False):
            self._record_live_coverage(key, path, points)
            await asyncio.sleep(0)
        return path

    async def _update_live_paths(self, robots, positions, now, raw_routes=None):
        raw_routes = raw_routes or {}
        for key, state in robots.items():
            started = self._live_mission(state)
            if started is None:
                self._live_floor_pins.pop(key, None)
            floor = self.live_floor(state)
            path = self._live_paths.get(key)
            version = (floor.map_id, floor.version_id) if floor is not None else None
            if path is not None and (path.started, path.map_version) != (started, version):
                await self._checkpoint_mission_route(
                    (self.data or {}).get(key), path, now, final=True
                )
                self._live_paths.pop(key, None)
                path = None
            if floor is None:
                self._live_coverage.pop(key, None)
                self._live_obstacles.pop(key, None)
                self._live_route_attempts.pop(key, None)
                self._stream_route_references.pop(key, None)
                continue
            report = self._current_timeline(state)
            if report is not None and (report.requested_floor or report.localized_maps):
                self._live_floor_pins[key] = (started, report.mission_number), version
            batches = positions.get(key, ())
            for batch in batches:
                if not batch.belongs_to(started, now):
                    continue
                path = (path or MissionPath(version, started, batch, ())).append(batch)
            if path is None:
                continue
            try:
                await self._floor_plan(key, floor)
            except RoombaError, HomeAssistantError:
                self._live_paths.pop(key, None)
                continue
            watch, streamed_reference = self._stream_route_references.get(key, (None, None))
            reference = raw_routes.get(key)
            if watch == MapWatch(key, started, version) and (
                reference is None or reference.timestamp < streamed_reference.timestamp
            ):
                reference = streamed_reference
            path = await self._recover_live_route(key, path, reference, now)
            live = self._live_paths.get(key)
            if live is not None and (live.started, live.map_version) == (started, version):
                path = path.merge(live)
            self._live_paths[key] = path
            self._record_live_coverage(key, path, path.points)
            await self._checkpoint_mission_route(state, path, now)
            if self.show_maps and now.timestamp() < path.latest.expires:
                robots[key] = self._with_live_position(state, floor, path.latest)
        self._schedule_live_expiration(now)

    def _with_live_position(self, state, floor, batch):
        point = batch.positions[-1]
        coordinates = (point.x, point.y)
        geometry = self._floor_plans.get((state.robot_id, floor.geometry_key))
        return replace(
            state,
            telemetry={
                **state.telemetry,
                "current_room": geometry.room_at(coordinates) if geometry else None,
                "on_mapped_carpet": geometry.mapped_carpet_at(coordinates) if geometry else None,
                "live_route_activity": POSITION_ACTIVITIES.get(point.modes),
                "position_updated": datetime.fromtimestamp(batch.timestamp, UTC),
            },
        )

    def live_floor(self, state):
        robot_id = state.robot_id
        started = self._live_mission(state)
        if started is None or not self._maps_available.get(robot_id):
            return None
        generation, pinned = self._live_floor_pins.get(robot_id, (None, None))
        if generation != (started, state.telemetry.get("mission_number")):
            pinned = None
        return resolve_live_floor(
            self._maps.get(robot_id, ()), self._current_timeline(state), pinned
        )

    def _map_watch(self, state):
        if not self.show_maps or (floor := self.live_floor(state)) is None:
            return None
        return MapWatch(state.robot_id, self._live_mission(state), (floor.map_id, floor.version_id))

    @callback
    def _receive_live_map_sample(self, watch, sample):
        robot_id = watch.robot_id
        state = (self.data or {}).get(robot_id)
        if self._closed or state is None or self._map_watch(state) != watch:
            return
        if isinstance(sample, RawRouteReference):
            scope, previous = self._stream_route_references.get(robot_id, (None, None))
            if scope != watch or previous.timestamp < sample.timestamp:
                self._stream_route_references[robot_id] = watch, sample
            return
        now = datetime.now(UTC)
        if not sample.belongs_to(watch.started, now):
            return
        previous = self._live_paths.get(robot_id)
        if previous is None or (previous.started, previous.map_version) != (
            watch.started,
            watch.map_version,
        ):
            previous = MissionPath(watch.map_version, watch.started, sample, ())
        path = previous.append(sample)
        if path == previous:
            return
        self._live_paths[robot_id] = path
        self._record_live_coverage(robot_id, path, enumerate(sample.positions, start=sample.index))
        self.data[robot_id] = self._with_live_position(state, self.live_floor(state), path.latest)
        self._schedule_live_expiration(now)
        self.async_update_listeners()

    def _schedule_live_expiration(self, now):
        if self._cancel_live_expiration is not None:
            self._cancel_live_expiration()
            self._cancel_live_expiration = None
        observed = now.timestamp()
        active = [
            path.latest.expires
            for path in self._live_paths.values()
            if path.latest.expires > observed
        ]
        active.extend(
            timestamp + RAW_ROUTE_MAX_AGE
            for _, timestamp, points in self._live_obstacles.values()
            if points and timestamp + RAW_ROUTE_MAX_AGE > observed
        )
        if active:
            self._cancel_live_expiration = async_track_point_in_utc_time(
                self.hass, self._expire_live_positions, datetime.fromtimestamp(min(active), UTC)
            )

    @callback
    def _expire_live_positions(self, now):
        self._cancel_live_expiration = None
        for key, path in self._live_paths.items():
            if path.latest.expires <= now.timestamp() and (state := self.data.get(key)):
                values = dict(state.telemetry)
                values.pop("current_room", None)
                values.pop("on_mapped_carpet", None)
                values.pop("live_route_activity", None)
                values.pop("position_updated", None)
                self.data[key] = replace(state, telemetry=values)
        self._schedule_live_expiration(now)
        self.async_update_listeners()

    def _defer_maps(self, now, delay):
        self._maps_retry_until = now + delay
        self._maps_due = max(self._maps_due, self._maps_retry_until)

    def _add_map_capabilities(self, state):
        available = self._maps_available.get(state.robot_id)
        if available is None or state.capabilities.persistent_maps is False:
            return state
        telemetry = {**state.telemetry, "maps_available": available}
        if not available:
            return replace(state, telemetry=telemetry)
        maps = self._maps[state.robot_id]
        regions = tuple(region for item in maps for region in item.regions)
        rooms = sum(region.kind is RegionKind.ROOM for region in regions)
        zones = sum(region.kind is RegionKind.ZONE for region in regions)
        return replace(
            state,
            capabilities=replace(
                state.capabilities,
                map_selection=len(maps) > 1,
                room_regions=bool(rooms),
                zone_regions=bool(zones),
                room_cleaning=bool(rooms),
                zone_cleaning=bool(zones),
            ),
            telemetry={
                **telemetry,
                "map_count": len(maps),
                "room_count": rooms,
                "zone_count": zones,
            },
        )

    async def _refresh_history(self, robots, now):
        previous = self.data or {}
        supported = [state for state in robots.values() if state.capabilities.history is True]
        for state in supported:
            robot_id = state.robot_id
            started = ended_mission_start(previous.get(robot_id), state)
            if started is None or history_includes_mission(
                self._history.get(robot_id, {}), started
            ):
                continue
            pending = self._history_pending.get(robot_id)
            if pending is None or started > pending.started:
                self._history_pending[robot_id] = PendingHistoryRefresh(started, now)
        if now < self._history_retry_until:
            return
        full = now >= self._history_due
        if full:
            self._history_due = now + HISTORY_SECONDS
            self._history = {}
        for state in supported:
            robot_id = state.robot_id
            pending = self._history_pending.get(robot_id)
            if not full and (pending is None or now < pending.due):
                continue
            try:
                self._history[robot_id] = await self.client.mission_history(robot_id)
            except AuthenticationError:
                raise
            except RateLimited as error:
                self._history_retry_until = now + error.retry_after
                self._history_due = max(self._history_due, self._history_retry_until)
                break
            except Exception as error:
                _LOGGER.debug("Mission history refresh failed: %s", type(error).__name__)
            if pending is not None:
                if history_includes_mission(self._history.get(robot_id, {}), pending.started):
                    del self._history_pending[robot_id]
                elif now >= pending.due:
                    if pending.retried:
                        del self._history_pending[robot_id]
                    else:
                        self._history_pending[robot_id] = replace(
                            pending, due=now + POLL_SECONDS, retried=True
                        )

    async def _refresh_schedules(self, robots, now):
        if now < self._schedules_due:
            return
        self._schedules_due = now + DETAIL_SECONDS
        self._schedules = {}
        supported = frozenset(
            key for key, state in robots.items() if state.capabilities.schedules is True
        )
        if not supported:
            return
        try:
            self._schedules = await self.client.cloud_schedules(supported)
        except AuthenticationError:
            raise
        except RateLimited as error:
            self._schedules_retry_until = now + error.retry_after
            self._schedules_due = max(self._schedules_due, self._schedules_retry_until)
        except Exception as error:
            _LOGGER.debug("Schedule refresh failed: %s", type(error).__name__)

    async def _async_update_data(self):
        async with self._io_lock:
            if self._closed:
                raise UpdateFailed("Integration unloaded")
            remaining = self._read_retry_until - self._clock()
            if remaining > 0:
                raise UpdateFailed("Waiting to retry Roomba Home", retry_after=remaining)
            try:
                result = await self._read_account_state()
            except AuthenticationError as error:
                raise ConfigEntryAuthFailed("Authentication required") from error
            except RateLimited as error:
                self._read_retry_until = self._clock() + error.retry_after
                raise UpdateFailed(
                    "Roomba Home rate limited the request", retry_after=error.retry_after
                ) from None
            except Exception as error:
                _LOGGER.debug("Refresh failed: %s", type(error).__name__)
                self._read_failures = min(self._read_failures + 1, 5)
                delay = min(900, POLL_SECONDS * 2 ** (self._read_failures - 1))
                self._read_retry_until = self._clock() + delay
                raise UpdateFailed(
                    "Roomba Home state could not be refreshed", retry_after=delay
                ) from None
            self._read_failures = 0
            self._read_retry_until = 0
            for robot_id, state in result.items():
                if state.reported_name is not None:
                    self._sync_robot_device(robot_id, name=state.reported_name)
            self._live_stream.update(
                {
                    robot_id: watch
                    for robot_id, state in result.items()
                    if (watch := self._map_watch(state)) is not None
                }
            )
            return result

    async def _read_account_state(self):
        session = await self.client.ensure_session()
        positions = {}
        timelines = {}
        raw_routes = {}
        if self.show_maps and (topics := await self._live_topics(session)):
            pending = self._timeline_requests(topics, self._clock())
            documents = await self._executor(
                self._read, session, FAST_SHADOWS, topics, positions, pending, timelines, raw_routes
            )
        else:
            documents = await self._executor(self._read, session)
        observed_at = datetime.now(UTC)
        await self._optional_sources(session, self._clock())
        part_references = project_part_references(
            self._part_catalog, self.client.country, model=SUPPORTED_SKU
        )
        result = {}
        for robot_id, details in session.raw["robots"].items():
            if robot_id not in self.selected or details.get("sku") != SUPPORTED_SKU:
                continue
            live = documents.get(robot_id, {})
            state = project_state(
                robot_id,
                details,
                {**self._details.get(robot_id, {}), **live},
            )
            previous = (self.data or {}).get(robot_id)
            last_observed = previous.observed_at if previous else None
            if (
                state.capabilities.docking is None
                and previous
                and previous.capabilities.docking is True
            ):
                state = replace(state, capabilities=replace(state.capabilities, docking=True))
            telemetry = {
                **state.telemetry,
                **project_parts(self._parts.get(robot_id), self._part_catalog),
                "part_references": part_references,
                "details_available": bool(self._details.get(robot_id)),
                "parts_available": bool(self._parts.get(robot_id)),
            }
            asset = self._assets.get(robot_id)
            if asset is not None and asset.activation_date is not None:
                telemetry["activation_date"] = asset.activation_date
            result[robot_id] = replace(
                state,
                telemetry=telemetry,
                observed_at=observed_at if live else last_observed,
                capabilities=replace(
                    state.capabilities,
                    maintenance=True if self._parts.get(robot_id) else None,
                ),
            )
        await self._refresh_maps(result, self._clock())
        await self._refresh_history(result, self._clock())
        await self._refresh_schedules(result, self._clock())
        now = dt_util.utcnow()
        for key, state in result.items():
            telemetry = dict(state.telemetry)
            for name, supported, snapshots in (
                ("history", state.capabilities.history, self._history),
                ("schedules", state.capabilities.schedules, self._schedules),
            ):
                if supported is True:
                    snapshot = snapshots.get(key)
                    telemetry[f"{name}_available"] = snapshot is not None
                    telemetry.update(snapshot or {})
            if rooms := telemetry.pop("last_mission_room_results", ()):
                floor_names = self.maps_for_robot(key) if self.show_maps else ()
                telemetry["last_mission_rooms"] = present_rooms(rooms, floor_names)
            if zones := telemetry.pop("last_mission_zone_results", ()):
                zone_maps = await self._zone_label_maps(key, zones)
                telemetry["last_mission_zones"] = present_zones(zones, zone_maps)
            if self.show_maps:
                telemetry.update(await self._timeline_metrics(state, timelines.get(key), now))
            else:
                telemetry.pop("last_cleaning_by_floor", None)
            if zone_name := telemetry.get("robot_timezone"):
                zone = await dt_util.async_get_time_zone(zone_name)
                if zone is None:
                    telemetry["robot_timezone"] = None
                if "cloud_schedule_times" in telemetry:
                    telemetry["next_cloud_schedule"] = (
                        next_schedule_start(telemetry, zone, now) if zone is not None else None
                    )
            result[key] = self._add_map_capabilities(replace(state, telemetry=telemetry))
        if self.show_maps:
            await self._update_live_paths(result, positions, now, raw_routes)
        active = any(
            state.activity in {"cleaning", "paused", "returning"}
            or state.mission_at_dock is True
            or state.telemetry.get("evacuation_state") in {302, 304}
            or state.telemetry.get("refill_state") in {402, 403}
            or state.telemetry.get("pad_wash_state") in {602, 607}
            or state.telemetry.get("pad_dry_state") == 702
            for state in result.values()
        )
        self.update_interval = timedelta(seconds=ACTIVE_POLL_SECONDS if active else POLL_SECONDS)
        self.source_status = {
            name: sum(state.telemetry.get(f"{name}_available") is True for state in result.values())
            for name in ("details", "parts", "maps", "history", "schedules")
        }
        self._reconcile_deferred_commands(result)
        return result

    def _reconcile_deferred_commands(self, robots):
        for robot_id, confirmation in tuple(self._deferred_commands.items()):
            state = robots.get(robot_id)
            outcome = confirmation.result(control_snapshot(state) if state else None, self._clock())
            if outcome is not None:
                self.command_status[robot_id] = outcome
                del self._deferred_commands[robot_id]

    def _notify_status(self, robot_id, value):
        if value != "submitted":
            self._deferred_commands.pop(robot_id, None)
        self.command_status[robot_id] = value
        self.async_update_listeners()

    async def _refresh_for_command(self):
        task = self._command_refresh_task
        if task is None or task.done():
            self._command_refresh_task = task = self.config_entry.async_create_task(
                self.hass, self.async_refresh(), name="Update Roomba command status"
            )
        await asyncio.shield(task)

    def maps_for_robot(self, robot_id):
        state = (self.data or {}).get(robot_id)
        if state is not None and state.capabilities.persistent_maps is False:
            return ()
        return self._maps.get(robot_id, ())

    def cleaning_maps_for_robot(self, robot_id):
        maps = self.maps_for_robot(robot_id)
        return tuple(
            with_archive_destinations(floor, plan)
            if (plan := self._floor_plans.get((robot_id, floor.geometry_key))) is not None
            else floor
            for floor in maps
        )

    async def _resolve_areas(
        self, robot_id, segments, reviewed_map=None, *, include_furniture=False
    ):
        async with self._io_lock:
            return await self._resolve_current_areas(
                robot_id, segments, reviewed_map, include_furniture=include_furniture
            )

    async def _resolve_current_areas(
        self, robot_id, segments, reviewed_map=None, *, include_furniture=False
    ):
        state = (self.data or {}).get(robot_id)
        if not state or state.capabilities.persistent_maps is not True:
            raise action_error("unsupported_areas", "This robot has no available cleaning map")
        maps = await self._read_map_action(self._read_maps, robot_id)
        inventory_id = raw_inventory = reviewed_selection = None
        if reviewed_map is not None:
            map_id, version, inventory_id = reviewed_map
            maps = tuple(
                floor for floor in maps if (floor.map_id, floor.version_id) == (map_id, version)
            )
            if not maps:
                raise action_error("map_changed", "The map changed. Review your selection.")
            raw_inventory = maps[0].inventory_id
        if self.show_maps and segments and isinstance(segments[0], str):
            map_id = segments[0].partition(":")[0]
            floor = next((item for item in maps if item.map_id == map_id), None)
            if floor is not None:
                try:
                    plan = await self._floor_plan(robot_id, floor)
                except HomeAssistantError, ProtocolError:
                    regions = tuple(
                        region
                        for region in floor.regions
                        if region.kind is not RegionKind.ZONE
                        or region.region_id not in SAVED_ZONE_IDS
                    )
                    maps = (replace(floor, regions=regions),)
                else:
                    floor = with_archive_destinations(floor, plan)
                    if include_furniture:
                        if inventory_id is not None:
                            reviewed_selection = floor.selection_id
                        floor = replace(floor, regions=(*floor.regions, *furniture_regions(plan)))
                    maps = (floor,)
        if inventory_id is not None and inventory_id not in (
            raw_inventory,
            reviewed_selection,
            maps[0].selection_id,
        ):
            raise action_error("map_changed", "The map changed. Review your selection.")
        try:
            return resolve_segments(maps, segments)
        except ValueError:
            raise action_error("unsupported_areas", "Select areas on one current map") from None

    async def _read_map_action(self, read, *args, **kwargs):
        now = self._clock()
        if now < self._read_retry_until:
            raise action_error("robot_unavailable", "Waiting to retry Roomba Home")
        if now < self._maps_retry_until:
            raise action_error("map_rate_limited", "Roomba Home rate limited map requests")
        try:
            return await read(*args, **kwargs)
        except AuthenticationError:
            raise
        except RateLimited as error:
            self._defer_maps(self._clock(), error.retry_after)
            raise action_error(
                "map_rate_limited", "Roomba Home rate limited map requests"
            ) from None
        except Exception:
            raise action_error("map_unavailable", "Could not read the current map") from None

    async def _readable_floor(self, robot_id, map_id, version):
        if (
            self._closed
            or not self.show_maps
            or robot_id not in self.selected
            or not self.last_update_success
            or not self._maps_available.get(robot_id)
        ):
            raise action_error("map_unavailable", "Floor maps are unavailable")
        maps = self.maps_for_robot(robot_id)
        if map_id is None and len(maps) > 1:
            raise action_error("map_selection_required", "Select a floor")
        floor = next((item for item in maps if map_id in (None, item.map_id)), None)
        if floor is None or version not in (None, floor.version_id):
            raise action_error("map_changed", "Select the current floor")
        try:
            plan = await self._floor_plan(robot_id, floor)
        except ProtocolError:
            raise action_error("map_unavailable", "Could not read the current map") from None
        return floor, plan

    async def async_map_cleaning_scores(self, robot_id, map_id=None, version=None):
        async with self._io_lock:
            floor, plan = await self._readable_floor(robot_id, map_id, version)
            scores = await self._read_map_action(
                self.client.map_cleaning_scores, robot_id, with_archive_destinations(floor, plan)
            )
            state = (self.data or {}).get(robot_id)
            if state is not None and (
                presets := smart_routine_presets(state.sku, state.capabilities, scores["rooms"])
            ):
                return {**scores, "smart_presets": presets}
            return scores

    async def async_list_map_routines(
        self, robot_id, map_id=None, version=None, *, include_saved=False
    ):
        async with self._io_lock:
            floor, plan = await self._readable_floor(robot_id, map_id, version)
            state = (self.data or {}).get(robot_id)
            if state is None:
                raise action_error("map_unavailable", "Floor maps are unavailable")
            mapped = with_archive_destinations(floor, plan)
            mapped = replace(mapped, regions=(*mapped.regions, *furniture_regions(plan)))
            found = await self._read_map_action(
                self.client.map_quick_routines,
                robot_id,
                mapped,
                state.capabilities,
                include_saved=include_saved,
            )
            current = await self._read_map_action(self._read_maps, robot_id)
            if floor not in current:
                raise action_error("map_changed", "Select the current floor")
            return found

    async def async_mission_history(
        self,
        robot_id,
        report_id=None,
        map_index=0,
        *,
        include_short_canceled=False,
        history_days=DEFAULT_HISTORY_DAYS,
    ):
        async with self._io_lock:
            if self._closed or not self.show_maps or robot_id not in self.selected:
                raise action_error("history_unavailable", "Cleaning history is unavailable")
            reports = await self._read_map_action(
                self.client.mission_reports,
                robot_id,
                include_short_canceled=include_short_canceled,
                history_days=history_days,
            )
            if report_id is None:
                return {"missions": [report.summary() for report in reports]}
            report = next((row for row in reports if row.key == report_id), None)
            if report is None or not 0 <= map_index < max(1, len(report.maps)):
                raise action_error(
                    "report_not_found", "The requested cleaning report is no longer available"
                )
            scope = report.maps[map_index] if report.maps else None
            archive = None
            if scope is not None:
                try:
                    archive = await self._read_map_action(self.client.map_geometry, *scope)
                except HomeAssistantError as error:
                    if error.translation_key != "map_unavailable":
                        raise
        floors, geometry = (), None
        if archive is not None:
            try:
                floor, geometry = await self._executor(read_mission_map, archive, *scope)
                floors = (floor,)
            except ProtocolError:
                pass
        geometry_source = "mission_archive" if geometry is not None else None
        detail = report.detail(floors)
        requested = report.requested_scope
        if scope is not None and requested is not None and requested[0] != scope[0]:
            requested = None
        capture = None
        started = report.metrics.get("last_mission_started")
        if geometry is None and started is not None and report.mission_number is not None:
            try:
                capture = await self._mission_routes.async_lookup(
                    robot_id,
                    started,
                    report.mission_number,
                    requested,
                    scope,
                )
            except OSError, ProtocolError:
                _LOGGER.debug("Local Roomba mission route unavailable")
            if capture is not None and requested is None:
                requested = tuple(capture["key"][2:])
        backup_floor = False
        if geometry is None or (
            requested is not None
            and requested != scope
            and report.plan is not None
            and any(
                row["name"] is None and row["kind"] != "temporary_zone"
                for row in detail["plan"]["destinations"]
            )
        ):
            context = await self._history_floor_context(
                robot_id, report, requested, scope, need_geometry=geometry is None
            )
            if context is not None:
                base, base_geometry, base_scope, local = context
                detail = report.detail(floors, requested_floor=base)
                if geometry is None:
                    geometry = base_geometry
                    backup_floor = local
                    geometry_source = "backup_floor" if local else "requested_floor"
                    if capture is not None and tuple(capture["key"][2:]) == base_scope:
                        geometry.update(await self._executor(captured_geometry, capture["points"]))
                        geometry_source = "local_capture"
        return {
            **detail,
            "geometry": geometry,
            "geometry_source": geometry_source,
            **({"floor_source": "local_backup"} if backup_floor else {}),
            "map_index": map_index,
        }

    async def _history_floor_context(self, robot_id, report, requested, archive, *, need_geometry):
        if requested is not None and requested != archive:
            try:
                async with self._io_lock:
                    bundle = await self._read_map_action(self.client.map_geometry, *requested)
                floor, geometry = await self._executor(
                    read_requested_floor,
                    bundle,
                    *requested,
                    report.plan,
                    report.requested_footprints,
                )
            except HomeAssistantError, AuthenticationError, ProtocolError:
                pass
            else:
                return floor, geometry, requested, False
        scopes = tuple(
            dict.fromkeys(
                scope for scope in (requested, archive if need_geometry else None) if scope
            )
        )
        if not scopes:
            return None
        history = map_history(self.hass, self.config_entry.entry_id)
        try:
            candidates = await history.async_matching_revisions(robot_id, scopes)
        except OSError, ProtocolError:
            return None
        for scope, snapshot in candidates:
            try:
                floor, geometry = await self._executor(
                    read_backed_up_floor, snapshot, scope, report.plan, report.requested_footprints
                )
            except ProtocolError:
                continue
            return floor, geometry, scope, True
        return None

    async def _resolve_point(self, robot_id, region_id, x, y, reviewed_map, mops):
        async with self._io_lock:
            state = (self.data or {}).get(robot_id)
            if not state or not supports_point_clean(state.capabilities.digital_spot):
                raise action_error("unsupported_point", "This robot cannot clean a mapped point")
            area = await self._resolve_current_areas(robot_id, [region_id], reviewed_map)
            if area.regions[0].kind is not RegionKind.ROOM:
                raise action_error("point_requires_room", "Select a mapped room")
            bundle = await self._read_map_action(
                self.client.map_geometry, area.map_id, area.version_id
            )
        try:
            return await self._executor(partial(resolve_room_point, mops=mops), bundle, area, x, y)
        except ProtocolError:
            raise action_error("map_unavailable", "Could not read the current map") from None
        except ValueError:
            raise action_error(
                "invalid_map_point", "Select an allowed point within the room"
            ) from None

    async def async_clean_point(
        self, robot_id, region_id, x, y, reviewed_map=None, *, mode=CleaningMode.VACUUM
    ):
        async with self._robot_operation(robot_id):
            try:
                target = await self._resolve_point(
                    robot_id, region_id, x, y, reviewed_map, mode.mops
                )
                await execute_control(
                    RobotControlAdapter(self, robot_id, target),
                    Command.POINT_CLEAN,
                    CleaningProfile(mode),
                )
            except AuthenticationError as error:
                self._notify_status(robot_id, "unconfirmed")
                raise ConfigEntryAuthFailed("Authentication required") from error
            except ControlError as error:
                raise action_error(error.key, error.key) from None

    async def async_reset_maintenance_counter(self, robot_id, part):
        async with self._robot_operation(robot_id):
            async with self._io_lock:
                robot = (self.data or {}).get(robot_id)
                part_id = RESETTABLE_PARTS.get(part)
                if robot is None or not self.last_update_success or part_id is None:
                    raise action_error("part_reset_unavailable", "Part counter unavailable")
                usage_key = f"part_{part_id}_usage"
                try:
                    current = await self.client.robot_parts(robot_id)
                    current_metrics = project_parts(current, self._part_catalog)
                    if current_metrics.get(usage_key) is None:
                        raise action_error("part_reset_unavailable", "Part counter unavailable")
                    # The POST can change the confirmed provider state even if the reply is lost.
                    self._parts_due = self._clock()
                    await self.client.reset_part(robot_id, part_id)
                    for delay in (0, 1, 2):
                        await self._sleep(delay)
                        document = await self.client.robot_parts(robot_id)
                        metrics = project_parts(document, self._part_catalog)
                        if metrics.get(usage_key) == 0:
                            self._parts[robot_id] = document
                            self.data[robot_id] = replace(
                                robot, telemetry={**robot.telemetry, **metrics}
                            )
                            self.async_update_listeners()
                            return
                except AuthenticationError as error:
                    raise ConfigEntryAuthFailed("Authentication required") from error
                except OSError, RoombaError:
                    pass
                raise action_error("part_reset_unconfirmed", "Roomba did not confirm the reset")

    async def async_get_software_status(self, robot_id, *, allow_unavailable_catalog=False):
        if self._closed or robot_id not in self.selected:
            raise action_error("not_configured", "Robot is not configured")
        state = (self.data or {}).get(robot_id)
        if state is None or not self.last_update_success:
            raise action_error("software_status_unavailable", "Robot software is unavailable")
        installed = state.telemetry.get("software_version")
        if installed is None:
            raise action_error("software_status_unavailable", "Robot software is unavailable")
        dock = state.telemetry.get("dock_firmware")
        updated = state.telemetry.get("software_updated_at")
        report = {
            "installed_version": installed,
            "last_installed_at": updated.isoformat() if updated is not None else None,
            "dock_version": dock,
            "status": "unavailable",
            "catalog_versions": [],
        }
        try:
            candidates = await self.client.firmware_candidates(state.sku, installed, dock)
        except OSError, RoombaError:
            if allow_unavailable_catalog:
                return report
            raise action_error(
                "software_status_unavailable", "Could not read software status"
            ) from None
        return report | {
            "status": "catalog_candidates" if candidates else "up_to_date",
            "catalog_versions": list(candidates),
        }

    async def async_get_robot_help(self, robot_id):
        if self._closed or robot_id not in self.selected:
            raise action_error("not_configured", "Robot is not configured")
        state = (self.data or {}).get(robot_id)
        if state is None:
            raise action_error("robot_help_unavailable", "Robot help is unavailable")
        try:
            catalog = await self.client.robot_help(state.sku, self.hass.config.language)
        except ClientError, OSError, RoombaError:
            raise action_error(
                "robot_help_unavailable", "Could not read Roomba robot help"
            ) from None
        latest = (self.data or {}).get(robot_id)
        problems = observations(latest) if latest is not None and self.last_update_success else {}
        return {
            "robot": state.name,
            **catalog,
            "setup_guide": setup_guide_for(state.sku),
            "current_articles": current_help_articles(catalog["articles"], problems),
        }

    async def async_list_voice_languages(self, robot_id):
        if self._closed or robot_id not in self.selected:
            raise action_error("not_configured", "Robot is not configured")
        state = (self.data or {}).get(robot_id)
        if state is None or not self.last_update_success:
            raise action_error("voice_catalog_unavailable", "Robot voice settings are unavailable")
        installed = {code.lower() for code in state.telemetry.get("installed_voice_languages", ())}
        if not installed:
            raise action_error("voice_catalog_unavailable", "Robot voice settings are unavailable")
        try:
            catalog = await self.client.voice_catalog(state.sku)
        except OSError, RoombaError:
            raise action_error("voice_catalog_unavailable", "Could not read robot voices") from None
        selected = state.telemetry.get("voice_language")
        return {
            "current": selected.lower() if selected else None,
            "installed": sorted(installed),
            "downloadable": sorted(set(catalog) - installed),
        }

    async def async_voice_downloads(self, robot_id):
        report = await self.async_list_voice_languages(robot_id)
        robot = (self.data or {}).get(robot_id)
        details = self._details.get(robot_id, {})
        observed = voice_installation(
            details.get("rw-settings", {}), details.get("rw-software", {})
        )
        current = observed.selected.lower() if observed.selected else None
        status = "unavailable"
        if (
            robot is not None
            and self.last_update_success
            and sorted({code.lower() for code in observed.installed}) == report["installed"]
            and current == report["current"]
        ):
            status = (
                observed.download_status
                if robot.connected is True
                and robot.activity == "docked"
                and robot_settings_idle(robot)
                else "dock_required"
            )
        additional = sorted({code.lower() for code in observed.additional})
        return report | {
            "status": status,
            "reviewed_inventory": observed.inventory_id if status == "ready" else None,
            "replaces": additional[0] if observed.slots == 1 and len(additional) == 1 else None,
        }

    async def async_install_voice_language(self, robot_id, language, *, reviewed_inventory=None):
        async with self._robot_operation(robot_id):
            await self._refresh_for_command()
            try:
                await self._install_voice_language(robot_id, language, reviewed_inventory)
            except AuthenticationError as error:
                raise ConfigEntryAuthFailed("Authentication required") from error
            except OSError, RoombaError:
                raise action_error(
                    "voice_install_unavailable", "Voice installation unavailable"
                ) from None

    async def _install_voice_language(self, robot_id, language, reviewed_inventory):
        async with self._io_lock:
            robot = (self.data or {}).get(robot_id)
            if robot is None or not self.last_update_success or robot.connected is not True:
                raise action_error("voice_install_unavailable", "Robot settings are unavailable")
            if robot.activity != "docked" or robot.cycle != "none":
                raise action_error(
                    "voice_install_requires_dock", "Dock the robot before installing"
                )
            session = await self.client.ensure_session()
            sender = MqttCommandSender(session, robot_id)
            observed = await self._read_voice_installation(robot_id, sender)
            if reviewed_inventory is not None and reviewed_inventory != observed.inventory_id:
                raise action_error(
                    "voice_inventory_changed", "The installed voices changed. Review again."
                )
            # Selecting an already installed voice must not start another deployment.
            installed = next(
                (code for code in observed.installed if code.lower() == language), None
            )
            if installed is None:
                if observed.download_status == "unavailable":
                    raise action_error(
                        "voice_install_unavailable", "Voice installation unavailable"
                    )
                if observed.download_status == "busy":
                    raise action_error("voice_install_busy", "A software deployment is in progress")
                pack = await self.client.voice_pack(robot.sku, language)
                if pack is None:
                    raise action_error("unsupported_voice_pack", "Voice pack is unavailable")
                identifier = voice_deployment_id(datetime.now(UTC))
                self._notify_status(robot_id, "pending")
                try:
                    await self._executor(sender.install_voice_pack, identifier, pack)
                except asyncio.CancelledError:
                    self._notify_status(robot_id, "unconfirmed")
                    raise
                except (OSError, ProtocolError) as error:
                    # A lost acknowledgement does not justify a second deployment.
                    _LOGGER.debug("Voice install write not acknowledged: %s", type(error).__name__)
        if installed is not None:
            await self._write_robot_setting(robot_id, RobotSetting.VOICE_LANGUAGE, installed)
            return
        try:
            state = await self._wait_for_voice_installation(robot_id, identifier, pack.language)
            if state.selected != pack.language:
                await self._write_robot_setting(
                    robot_id, RobotSetting.VOICE_LANGUAGE, pack.language
                )
        except Exception, asyncio.CancelledError:
            self._notify_status(robot_id, "unconfirmed")
            raise
        self._notify_status(robot_id, "confirmed")

    async def _wait_for_voice_installation(self, robot_id, identifier, language):
        deadline = self._clock() + VOICE_INSTALL_TIMEOUT
        while not self._closed and self._clock() < deadline:
            async with self._io_lock:
                try:
                    session = await self.client.ensure_session()
                    sender = MqttCommandSender(session, robot_id)
                    state = await self._read_voice_installation(robot_id, sender)
                except OSError, ProtocolError:
                    pass
                else:
                    match state.result(identifier, language):
                        case "installed":
                            return state
                        case "failed":
                            raise HomeAssistantError(
                                f"Voice installation failed ({state.state})",
                                translation_domain=DOMAIN,
                                translation_key="voice_install_failed",
                                translation_placeholders={"code": str(state.state)},
                            )
            await self._sleep(5)
        raise action_error("voice_install_unconfirmed", "Voice installation was not confirmed")

    async def _read_voice_installation(self, robot_id, sender):
        reader = self._robot_settings_reader(sender, robot_id)
        replies = await self._executor(reader.read, ("rw-settings", "rw-software"))
        documents = {reply.shadow: reply.document for reply in replies if reply.accepted}
        if robot := (self.data or {}).get(robot_id):
            self._details.setdefault(robot_id, {}).update(documents)
            telemetry = {**robot.telemetry, **project_telemetry(documents)}
            self.data[robot_id] = replace(robot, telemetry=telemetry)
            self.async_update_listeners()
        return voice_installation(
            documents.get("rw-settings", {}), documents.get("rw-software", {})
        )

    async def async_list_cleaning_estimates(self, robot_id, segments):
        async with self._io_lock:
            state = self._estimate_state(robot_id)
            try:
                target = resolve_segments(self.maps_for_robot(robot_id), segments)
            except ValueError:
                raise action_error("unsupported_areas", "Select areas on one current map") from None
            if any(region.kind is not RegionKind.ROOM for region in target.regions):
                raise action_error("estimate_requires_rooms", "Select rooms for time estimates")
            return await self._read_time_estimates(robot_id, target, state.capabilities.cleaning)

    def _estimate_state(self, robot_id):
        if self._closed or robot_id not in self.selected:
            raise action_error("not_configured", "Robot is not configured")
        if self._clock() < max(self._read_retry_until, self._estimates_retry_until):
            raise action_error("estimate_rate_limited", "Waiting to retry time estimates")
        state = (self.data or {}).get(robot_id)
        if state is None or self._maps_available.get(robot_id) is not True:
            raise action_error("map_unavailable", "Could not read the current map")
        return state

    async def _read_time_estimates(self, robot_id, target, capabilities):
        try:
            return await self.client.cleaning_time_estimates(robot_id, target, capabilities)
        except AuthenticationError as error:
            raise ConfigEntryAuthFailed("Authentication required") from error
        except RateLimited as error:
            self._estimates_retry_until = self._clock() + error.retry_after
            raise action_error("estimate_rate_limited", "Waiting to retry time estimates") from None
        except Exception as error:
            _LOGGER.debug("Time estimate request failed: %s", type(error).__name__)
            raise action_error("estimate_unavailable", "Could not read time estimates") from None

    @staticmethod
    def _estimate_defaults(state):
        return {
            field: setting.observed_on(state.telemetry, state.capabilities)
            for field, setting in (
                ("suction_level", RobotSetting.SUCTION),
                ("smart_scrub", RobotSetting.SMART_SCRUB),
                ("two_pass", RobotSetting.TWO_PASS),
            )
        }

    async def async_estimate_cleaning_routine(self, robot_id, selections, reviewed_map=None):
        async with self._io_lock:
            state = self._estimate_state(robot_id)
            try:
                target = await self._profiled_map_target(robot_id, state, selections, reviewed_map)
                matrix = await self._read_time_estimates(
                    robot_id, target, state.capabilities.cleaning
                )
                current = await self._read_map_action(self._read_maps, robot_id)
            except AuthenticationError as error:
                raise ConfigEntryAuthFailed("Authentication required") from error
            if (target.map_id, target.version_id) not in {
                (floor.map_id, floor.version_id) for floor in current
            }:
                raise action_error("map_changed", "The map changed. Review your selection.")
            return routine_time_estimate(target, matrix, self._estimate_defaults(state))

    async def async_schedule_action(
        self,
        robot_id,
        schedule_id=None,
        *,
        weekdays=None,
        time=None,
        enabled=None,
        frequency=None,
        name=None,
        selections=None,
        reviewed_map=None,
    ):
        async with self._schedule_transaction(robot_id, write=schedule_id is not None) as state:
            if schedule_id is None:
                return {"schedules": await self.client.list_cleaning_schedules(robot_id)}
            if enabled is None:
                changes = {}
                if name is not None:
                    changes["name"] = name
                if selections is not None:
                    changes["target"] = await self._profiled_map_target(
                        robot_id, state, selections, reviewed_map
                    )
                if time is None:
                    if frequency is not None or weekdays is not None or not changes:
                        raise ValueError(
                            "Provide a time for timing changes or new cleaning settings."
                        )
                    return await self.client.update_cleaning_schedule(
                        robot_id, schedule_id, **changes
                    )
                frequency = frequency or "weekly"
                days = await self._schedule_days(state, weekdays, time, frequency)
                return await self.client.update_cleaning_schedule(
                    robot_id, schedule_id, days, time, frequency=frequency, **changes
                )
            return await self.client.set_cleaning_schedule_enabled(robot_id, schedule_id, enabled)

    async def async_create_cleaning_schedule(
        self,
        robot_id,
        name,
        weekdays,
        time,
        segments,
        overrides,
        *,
        frequency="weekly",
        reviewed_map=None,
    ):
        async with self._schedule_transaction(robot_id, write=True) as state:
            days = await self._schedule_days(state, weekdays, time, frequency)
            target = await self._profiled_map_target(
                robot_id, state, (segments, overrides), reviewed_map
            )
            return await self.client.create_cleaning_schedule(
                robot_id, name, days, time, target, frequency=frequency
            )

    @staticmethod
    async def _schedule_days(state, weekdays, time, frequency):
        if frequency == "weekly":
            if weekdays is None:
                raise ValueError("Select the weekdays for the recurring schedule.")
            return weekdays
        if weekdays is not None:
            raise ValueError("Provide only a local time for a one-time schedule.")
        name = state.telemetry.get("robot_timezone")
        zone = await dt_util.async_get_time_zone(name) if name else None
        if zone is None:
            raise action_error("schedule_timezone_unavailable", "Robot time zone is unavailable")
        return [once_weekday(time, zone, dt_util.utcnow())]

    async def async_remove_cleaning_schedule(self, robot_id, schedule_id):
        async with self._schedule_transaction(robot_id, write=True):
            return await self.client.remove_cleaning_schedule(robot_id, schedule_id)

    async def async_list_cleaning_routines(self, robot_id):
        async with self._routine_transaction(robot_id):
            return {"routines": await self.client.list_cleaning_routines(robot_id)}

    async def async_create_cleaning_routine(
        self, robot_id, name, selections, *, ordered=True, reviewed_map=None, **appearance
    ):
        async with self._routine_transaction(robot_id) as state:
            target = await self._profiled_map_target(robot_id, state, selections, reviewed_map)
            return await self.client.create_cleaning_routine(
                robot_id, name, replace(target, ordered=ordered), **appearance
            )

    async def async_update_cleaning_routine(
        self, robot_id, routine_id, name, selections, *, ordered=None, **appearance
    ):
        async with self._routine_transaction(robot_id) as state:
            target = None
            if selections is not None:
                target = await self._profiled_map_target(robot_id, state, selections)
                target = replace(target, ordered=ordered is not False)
            elif ordered is not None:
                raise ValueError("Provide regions to change the cleaning order.")
            if target is None and name is None and not appearance:
                raise ValueError("Provide a new routine name, region selection, icon, or color.")
            return await self.client.update_cleaning_routine(
                robot_id, routine_id, name, target, **appearance
            )

    async def async_remove_cleaning_routine(self, robot_id, routine_id):
        async with self._routine_transaction(robot_id):
            return await self.client.remove_cleaning_routine(robot_id, routine_id)

    async def async_reorder_cleaning_routine(
        self, robot_id, routine_id, anchor_id, position, expected_order
    ):
        async with self._routine_transaction(robot_id):
            try:
                routines = await self.client.reorder_cleaning_routine(
                    robot_id, routine_id, anchor_id, position, expected_order=expected_order
                )
            except ProgramSelectionChanged:
                raise action_error(
                    "routine_order_changed",
                    "The routine order changed. Reopen the list and try again.",
                ) from None
            return {"routines": routines}

    async def _profiled_map_target(self, robot_id, state, selections, reviewed_map=None):
        segments, overrides = selections
        target = await self._resolve_current_areas(
            robot_id, segments, reviewed_map, include_furniture=True
        )
        profiles = self._area_profiles(self.profile(robot_id), target, overrides)
        try:
            for profile in profiles:
                profile.validate(state.capabilities.cleaning)
        except ValueError:
            raise action_error("unsupported_profile", "Invalid area cleaning settings") from None
        return replace(target, profiles=profiles)

    @asynccontextmanager
    async def _routine_transaction(self, robot_id):
        async with self._io_lock:
            state = (self.data or {}).get(robot_id)
            if self._closed or robot_id not in self.selected or state is None:
                raise action_error("not_configured", "Robot is not configured")
            if self._clock() < max(self._read_retry_until, self._routines_retry_until):
                raise action_error("routine_rate_limited", "Waiting to retry routines")
            try:
                yield state
            except AuthenticationError as error:
                raise ConfigEntryAuthFailed("Authentication required") from error
            except RateLimited as error:
                self._routines_retry_until = self._clock() + error.retry_after
                raise action_error("routine_rate_limited", "Waiting to retry routines") from None
            except RoutineNotEditable, ValueError:
                raise action_error("routine_not_editable", "Routine is not editable") from None
            except RoutineUpdateUnconfirmed:
                raise action_error(
                    "routine_unconfirmed", "Routine change was not confirmed"
                ) from None
            except HomeAssistantError:
                raise
            except Exception as error:
                _LOGGER.debug("Routine action failed: %s", type(error).__name__)
                raise action_error("routine_unavailable", "Could not access routines") from None

    @asynccontextmanager
    async def _schedule_transaction(self, robot_id, *, write):
        async with self._io_lock:
            state = (self.data or {}).get(robot_id)
            if self._closed or robot_id not in self.selected or state is None:
                raise action_error("not_configured", "Robot is not configured")
            if state.capabilities.schedules is not True:
                raise action_error("schedule_not_editable", "Schedules are not supported")
            if self._clock() < max(self._read_retry_until, self._schedules_retry_until):
                raise action_error("schedule_rate_limited", "Waiting to retry schedules")
            try:
                yield state
            except AuthenticationError as error:
                raise ConfigEntryAuthFailed("Authentication required") from error
            except RateLimited as error:
                self._schedules_retry_until = self._clock() + error.retry_after
                self._schedules_due = max(self._schedules_due, self._schedules_retry_until)
                raise action_error("schedule_rate_limited", "Waiting to retry schedules") from None
            except ScheduleNotEditable, ValueError:
                raise action_error("schedule_not_editable", "Schedule is not editable") from None
            except ScheduleUpdateUnconfirmed:
                self._schedules_due = self._clock()
                raise action_error(
                    "schedule_unconfirmed", "Schedule update was not confirmed"
                ) from None
            except HomeAssistantError:
                raise
            except Exception as error:
                _LOGGER.debug("Schedule action failed: %s", type(error).__name__)
                raise action_error("schedule_unavailable", "Could not access schedules") from None
            if write:
                self._schedules_due = self._clock()
        if write:
            await self.async_request_refresh()

    @staticmethod
    def _area_profiles(profile, target, overrides):
        if target is None or len(overrides) != len(target.regions):
            raise action_error("unsupported_areas", "Each area needs one selection")
        try:
            return tuple(replace(profile, **change) for change in overrides)
        except TypeError, ValueError:
            raise action_error("unsupported_profile", "Invalid area settings") from None

    @asynccontextmanager
    async def _robot_operation(self, robot_id):
        if robot_id not in self.selected:
            raise action_error("not_configured", "Robot is not configured")
        task = asyncio.current_task()
        self._command_tasks.add(task)
        try:
            async with self._command_locks[robot_id]:
                if self._closed:
                    raise action_error("not_configured", "Robot is not configured")
                yield
        finally:
            self._command_tasks.discard(task)

    async def async_command(
        self,
        robot_id,
        command: Command,
        *,
        segments=None,
        overrides=(),
        reviewed_map=None,
        reviewed_skip=None,
        mission_review_id=None,
        ordered=True,
        new_mission=False,
    ):
        async with self._robot_operation(robot_id):
            try:
                skip_target = None
                if reviewed_skip is not None:
                    skip_target = self._skip_review(robot_id)
                    if _skip_review_id(skip_target) != reviewed_skip:
                        raise ControlError("skip_destination_changed")
                mission_identity = None
                if mission_review_id is not None:
                    state = (self.data or {}).get(robot_id)
                    if state is None:
                        raise ControlError("mission_changed")
                    mission = control_snapshot(state)
                    current = mission_review(robot_id, mission)
                    if current is None or current["review_id"] != mission_review_id:
                        raise ControlError("mission_changed")
                    mission_identity = mission.mission_identity
                target = None
                if segments is not None:
                    target = await self._resolve_areas(
                        robot_id, segments, reviewed_map, include_furniture=bool(overrides)
                    )
                profile = self.profile(robot_id)
                area_profiles = ()
                if overrides:
                    area_profiles = self._area_profiles(profile, target, overrides)
                    if not ordered and any(
                        region.kind is RegionKind.FURNITURE for region in target.regions
                    ):
                        raise action_error(
                            "unsupported_areas", "Furniture requires an explicit order"
                        )
                    target = replace(target, profiles=area_profiles, ordered=ordered)
                await execute_control(
                    RobotControlAdapter(
                        self, robot_id, target, refresh_timeline=command is Command.SKIP
                    ),
                    command,
                    area_profiles[0] if area_profiles else profile,
                    new_mission=new_mission or target is not None,
                    area_profiles=area_profiles,
                    reviewed_skip=skip_target,
                    reviewed_mission=mission_identity,
                )
            except AuthenticationError as error:
                self._notify_status(robot_id, "unconfirmed")
                raise ConfigEntryAuthFailed("Authentication required") from error
            except ControlError as error:
                raise action_error(error.key, error.key) from None

    async def async_set_robot_setting(
        self, robot_id, setting: RobotSetting, value: int | bool | str
    ):
        """Update one reported setting and confirm it on the same robot."""
        async with self._robot_operation(robot_id):
            await self._refresh_for_command()
            try:
                await self._write_robot_setting(robot_id, setting, value)
            except AuthenticationError as error:
                raise ConfigEntryAuthFailed("Authentication required") from error
            except RateLimited as error:
                self._read_retry_until = max(
                    self._read_retry_until, self._clock() + error.retry_after
                )
                raise action_error(
                    "robot_setting_unavailable", "Roomba Home is rate limited"
                ) from None
            except (OSError, RoombaError) as error:
                _LOGGER.debug("Robot setting access failed: %s", type(error).__name__)
                raise action_error(
                    "robot_setting_unavailable", "Robot settings are unavailable"
                ) from None

    async def _write_robot_setting(self, robot_id, setting, value):
        async with self._io_lock:
            state = (self.data or {}).get(robot_id)
            if state is None or not self.last_update_success or state.connected is not True:
                raise action_error("robot_setting_unavailable", "Robot settings are unavailable")
            if not robot_settings_idle(state):
                raise action_error("robot_setting_active", "End the active mission first")
            capabilities = state.capabilities.cleaning
            if not isinstance(setting, RobotSetting) or not setting.accepts(value, capabilities):
                if isinstance(setting, RobotSetting) and setting in DEVICE_CONFIGURATION_SETTINGS:
                    raise action_error("unsupported_robot_setting", "This value is not supported")
                raise action_error("unsupported_profile", "This cleaning setting is not supported")
            if not setting.supported_on(state.capabilities):
                raise action_error("unsupported_dock_action", "A compatible dock is required")
            session = await self.client.ensure_session()
            sender = MqttCommandSender(session, robot_id)
            if not setting.accepts(value, sender.capabilities):
                raise action_error("unsupported_profile", "This cleaning setting is not supported")
            reader = self._robot_settings_reader(sender, robot_id)
            document, telemetry = await self._read_robot_settings(reader)
            observed = setting.observed(telemetry, capabilities)
            if observed is None:
                raise action_error("robot_setting_unavailable", "Robot settings are unavailable")
            if setting is RobotSetting.VOICE_LANGUAGE and value not in telemetry.get(
                "installed_voice_languages", ()
            ):
                raise action_error(
                    "voice_language_not_installed", "Voice language is not installed"
                )
            if observed == value:
                self._cache_robot_setting(robot_id, setting, document, telemetry)
                return
            self._details_due = 0
            try:
                await self._executor(sender.write_robot_setting, setting, value)
            except (OSError, ProtocolError) as error:
                # The publication can have succeeded before the acknowledgement was lost.
                _LOGGER.debug("Robot settings write not acknowledged: %s", type(error).__name__)

        for delay in (0, 2, 4, 8):
            if delay:
                await self._sleep(delay)
            async with self._io_lock:
                try:
                    document, telemetry = await self._read_robot_settings(reader)
                except OSError, ProtocolError:
                    continue
                if setting.observed(telemetry, capabilities) == value:
                    self._cache_robot_setting(robot_id, setting, document, telemetry)
                    return
        raise action_error("robot_setting_unconfirmed", "The robot did not confirm the setting")

    @staticmethod
    def _robot_settings_reader(sender, robot_id):
        mqtt = replace(sender.profile, devices={robot_id: sender.profile.devices[robot_id]})
        return MqttShadowReader(mqtt, timeout=5)

    async def _read_robot_settings(self, reader):
        replies = await self._executor(reader.read, ("rw-settings",))
        document = next((reply.document for reply in replies if reply.accepted), {})
        settings = project_telemetry({"rw-settings": document})
        if (name := convert("robot_name", reported(document).get("name"))) is not None:
            settings[RobotSetting.NAME.value] = name
        return document, settings

    def _cache_robot_setting(self, robot_id, setting, document, settings):
        self._details.setdefault(robot_id, {})["rw-settings"] = document
        if state := (self.data or {}).get(robot_id):
            value = settings[setting.value]
            if setting is RobotSetting.NAME:
                state = replace(state, name=value, reported_name=value)
                self._sync_robot_device(robot_id, name=value)
            else:
                state = replace(state, telemetry={**state.telemetry, setting.value: value})
            self.data[robot_id] = state
            self.async_update_listeners()

    def _sync_robot_device(self, robot_id, **updates):
        registry = device_registry.async_get(self.hass)
        identifier = (DOMAIN, f"{self.config_entry.unique_id}_{robot_id}")
        device = registry.async_get_device_by_identifier(identifier, self.config_entry.entry_id)
        if device is not None and any(
            getattr(device, key) != value for key, value in updates.items()
        ):
            registry.async_update_device(device.id, **updates)

    async def async_close(self):
        self._closed = True
        await self._live_stream.async_close()
        await self.async_shutdown()
        tasks = self._command_tasks.copy()
        if (refresh := self._command_refresh_task) is not None and not refresh.done():
            tasks.add(refresh)
        tasks.discard(asyncio.current_task())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Executor operations finish and close their own MQTT clients in finally.
        async with self._io_lock:
            self._deferred_commands.clear()
            if self._cancel_live_expiration is not None:
                self._cancel_live_expiration()
                self._cancel_live_expiration = None
            self._live_announcements.clear()
            self._live_timelines.clear()
            self._live_estimates.clear()
            self._timeline_due.clear()
            self._live_paths.clear()
            self._live_floor_pins.clear()
            self._live_coverage.clear()
            self._live_obstacles.clear()
            self._stream_route_references.clear()
            self._live_route_attempts.clear()
            self._floor_plans.clear()


class RobotControlAdapter:
    """Bind one robot to the application port, owning HA/provider translation."""

    def __init__(
        self,
        coordinator,
        robot_id,
        target: AreaTarget | PointTarget | None = None,
        *,
        refresh_timeline=False,
    ):
        self.coordinator = coordinator
        self.robot_id = robot_id
        self.target = target
        self.refresh_timeline = refresh_timeline

    @property
    def active(self):
        return not self.coordinator._closed

    async def refresh(self):
        coordinator = self.coordinator
        previous = coordinator._live_timelines.get(self.robot_id)
        if self.refresh_timeline:
            coordinator._timeline_due.pop(self.robot_id, None)
        await coordinator._refresh_for_command()
        state = (coordinator.data or {}).get(self.robot_id)
        if state is None or not coordinator.last_update_success:
            return ControlState(
                None,
                None,
                None,
                None,
                CleaningCapabilities(),
                refresh_failed=not coordinator.last_update_success,
            )
        report = None
        if self.refresh_timeline and previous is not coordinator._live_timelines.get(self.robot_id):
            report = coordinator._current_timeline(state, datetime.now(UTC))
        return control_snapshot(state, report)

    async def send(self, command, profile):
        coordinator = self.coordinator
        async with coordinator._io_lock:
            session = await coordinator.client.ensure_session()
            sender = MqttCommandSender(session, self.robot_id)
            if profile is None:
                await coordinator._executor(sender.send, command)
            else:
                arguments = (
                    (command, profile) if self.target is None else (command, profile, self.target)
                )
                await coordinator._executor(sender.send, *arguments)
                # A mission can change reported settings; bypass the slow cache once.
                coordinator._details_due = 0

    def report(self, status):
        self.coordinator._notify_status(self.robot_id, status)

    def defer_preparation(self, plan, state):
        if isinstance(self.coordinator._deferred_commands.get(self.robot_id), ReturnConfirmation):
            return
        self.coordinator._deferred_commands.setdefault(
            self.robot_id,
            PreparationConfirmation(
                plan, state.mission_identity, self.clock() + PREPARATION_CONFIRMATION_SECONDS
            ),
        )
        self.report("submitted")

    def defer_return(self, confirmation: ReturnConfirmation) -> None:
        self.coordinator._deferred_commands[self.robot_id] = confirmation

    async def wait(self, seconds):
        await self.coordinator._sleep(seconds)

    def clock(self):
        return self.coordinator._clock()


def _skip_review_id(key):
    return sha256(repr(key).encode()).hexdigest() if key is not None else None


def mission_review(robot_id, state: ControlState) -> dict | None:
    if not (commands := mission_commands(state)):
        return None
    review_id = sha256(repr((robot_id, state.mission_identity)).encode()).hexdigest()
    return {"review_id": review_id, "commands": commands}


def robot_settings_idle(state):
    return state.cycle == "none" and state.activity in {"idle", "docked"}


def control_snapshot(state, timeline=None):
    number = state.telemetry.get("mission_number")
    started = state.telemetry.get("mission_started")
    return ControlState(
        state.connected,
        state.activity,
        state.cycle != "none" if state.cycle else None,
        reported_cleaning_mode(state.mode),
        state.capabilities.cleaning,
        state.ready,
        dock_snapshot(state),
        state.capabilities.locate is True,
        state.capabilities.docking,
        bin_present=state.telemetry.get("bin_present"),
        preparing_mop=state.preparing_mop is True,
        mission_identity=(number, started) if number and started else None,
        digital_spot=state.capabilities.digital_spot,
        mission_initiator=state.telemetry.get("mission_initiator"),
        skip_capability=state.capabilities.skip,
        skip_observation=timeline.skip_observation() if timeline is not None else None,
        mapping_supported=state.capabilities.persistent_maps is True,
        mapping=state.mapping is True,
        pause_before_return=state.sku == SUPPORTED_SKU,
        ending_return=state.phase in {"hmUsrDock", "hmPostMsn"},
    )


def dock_snapshot(state):
    telemetry = state.telemetry
    return DockSnapshot(
        state.capabilities.dock,
        telemetry.get("evacuation_state"),
        telemetry.get("refill_state"),
        telemetry.get("pad_wash_state"),
        telemetry.get("pad_dry_state"),
        telemetry.get("dock_error"),
        state.mop_attached,
        telemetry.get("tank_present"),
    )
