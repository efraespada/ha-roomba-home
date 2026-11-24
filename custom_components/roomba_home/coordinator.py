"""Account coordinator: serialized MQTT work, polling and command confirmation."""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from time import monotonic

from homeassistant.const import CONF_COUNTRY, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ACTIVE_POLL_SECONDS,
    CONF_PROFILE,
    CONF_SHOW_MAPS,
    DETAIL_SECONDS,
    DOMAIN,
    HISTORY_SECONDS,
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
    execute_control,
)
from .core.capabilities import supports_point_clean
from .core.cleaning import CleaningCapabilities, CleaningMode, CleaningProfile
from .core.cleaning_protocol import CleaningSetting, reported_cleaning_mode
from .core.client import RoombaClient, check_status
from .core.commands import Command, MqttCommandSender
from .core.dock import DockSnapshot
from .core.errors import (
    AuthenticationError,
    ProtocolError,
    RateLimited,
    RoombaError,
    ScheduleNotEditable,
    ScheduleUpdateUnconfirmed,
)
from .core.history import ended_mission_start, history_includes_mission, present_rooms
from .core.live_maps import MissionPath
from .core.maps import AreaTarget, RegionKind, resolve_segments
from .core.models import AppProfile, LoginDetails
from .core.mqtt import MqttProfile, MqttShadowReader, live_map_topic
from .core.point_maps import PointTarget, read_floor_plan, resolve_room_point
from .core.preferences import profile_preferences, restore_profile
from .core.schedules import next_weekly_start
from .core.state import RobotState, project_state
from .core.telemetry import (
    CLEANING_CYCLES,
    DETAIL_SHADOWS,
    FAST_SHADOWS,
    project_parts,
    project_telemetry,
)
from .core.transport import AiohttpTransport
from .robot_updates import RobotUpdates

_LOGGER = logging.getLogger(__name__)
TIMELINE_INTERVAL = 45
TIMELINE_MAX_AGE = 100


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
        self._live_announcements = {}
        self._live_timelines = {}
        self._timeline_due = {}
        self._cancel_live_expiration = None
        self._io_lock = asyncio.Lock()
        self._command_locks = {robot_id: asyncio.Lock() for robot_id in self.selected}
        self._command_refresh_task = None
        self._closed = False
        self.command_status = {}
        self._preparations = {}
        self._command_tasks = set()
        self._sleep = asyncio.sleep
        self._clock = monotonic
        self._details_due = 0
        self._parts_due = 0
        self._maps_due = 0
        self._maps_retry_until = 0
        self._estimates_retry_until = 0
        self._history_due = 0
        self._history_retry_until = 0
        self._schedules_due = 0
        self._schedules_retry_until = 0
        self._read_failures = 0
        self._read_retry_until = 0
        self._details = {}
        self._parts = {}
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
        self, session, shadows=FAST_SHADOWS, live=None, positions=None, pending=None, timelines=None
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
                    "GET", "https://content-prod.iot.irobotapi.com/v2/es-es/ES/X185240/parts"
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
                    parts = await self.client.request("GET", f"/v1/robots/{robot_id}/parts")
                    if not isinstance(parts, dict) or not isinstance(parts.get("parts"), list):
                        raise ProtocolError("Expected the robot consumables list")
                    self._parts[robot_id] = parts
                except AuthenticationError:
                    raise
                except RateLimited as error:
                    self._parts_due = max(self._parts_due, now + error.retry_after)
                    _LOGGER.debug("Part refresh rate limited")
                    break
                except Exception as error:
                    _LOGGER.debug("Part refresh failed: %s", type(error).__name__)

    async def _executor(self, function, *args):
        future = self.hass.async_add_executor_job(function, *args)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # A thread cannot be cancelled: wait for its bounded finally/close.
            await asyncio.shield(future)
            raise

    async def _refresh_maps(self, robots, now):
        if now < self._maps_due:
            return
        self._maps_due = now + MAPS_SECONDS
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
        valid = {(item.map_id, item.version_id) for item in maps}
        for key in tuple(self._floor_plans):
            if key[0] == robot_id and key[1:] not in valid:
                del self._floor_plans[key]
        return maps

    async def _floor_plan(self, robot_id, floor):
        key = (robot_id, floor.map_id, floor.version_id)
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

    def live_path(self, robot_id):
        return self._live_paths.get(robot_id)

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
            if (
                not started
                or key not in session.raw["robots"]
                or len(self.maps_for_robot(key)) != 1
            ):
                self._live_announcements.pop(key, None)
                continue
            topic = live_map_topic(session, key)
            if not topic:
                continue
            mission, retry_at, authorized = self._live_announcements.get(key, (None, 0, False))
            if mission != started or (not authorized and self._clock() >= retry_at):
                retry_at = self._clock() + POLL_SECONDS
                try:
                    async with asyncio.timeout(3):
                        announced = await self.client.live_map_topic(key)
                except RateLimited as error:
                    retry_at = max(retry_at, self._clock() + error.retry_after)
                    authorized = False
                except RoombaError, OSError, TimeoutError:
                    authorized = False
                else:
                    authorized = announced == topic
                self._live_announcements[key] = (started, retry_at, authorized)
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

    def _timeline_metrics(self, state, report, now):
        key = state.robot_id
        started = self._live_mission(state)
        number = state.telemetry.get("mission_number")
        if not started:
            self._live_timelines.pop(key, None)
            self._timeline_due.pop(key, None)
            return {}
        if report is not None and report.mission_number == number:
            self._live_timelines[key] = (started, report)
        previous, recent = self._live_timelines.get(key, (None, None))
        if (
            previous != started
            or recent.mission_number != number
            or (now - recent.observed_at).total_seconds() > TIMELINE_MAX_AGE
        ):
            self._live_timelines.pop(key, None)
            return {}
        maps = self.maps_for_robot(key)
        return {
            "live_timeline_updated": recent.observed_at,
            "live_timeline_stage": recent.stage,
            "live_timeline_rooms": present_rooms(recent.rooms, maps),
            "live_timeline_active_rooms": present_rooms(recent.active_rooms, maps),
        }

    async def _update_live_paths(self, robots, positions, now):
        for key, state in robots.items():
            started = self._live_mission(state)
            maps = self._maps.get(key, ())
            if not started or not self._maps_available.get(key) or len(maps) != 1:
                self._live_paths.pop(key, None)
                continue
            floor = maps[0]
            version = (floor.map_id, floor.version_id)
            path = self._live_paths.get(key)
            if path and (path.started != started or path.map_version != version):
                del self._live_paths[key]
                path = None
            batches = positions.get(key, ())
            for batch in batches:
                if not started.timestamp() <= batch.timestamp <= now.timestamp() < batch.expires:
                    continue
                path = (path or MissionPath(version, started, batch, ())).append(batch)
            if path is None:
                continue
            try:
                geometry = await self._floor_plan(key, floor)
            except RoombaError, HomeAssistantError:
                self._live_paths.pop(key, None)
                continue
            self._live_paths[key] = path
            if now.timestamp() < path.latest.expires:
                point = path.latest.positions[-1]
                room = geometry.room_at((point.x, point.y))
                telemetry = {
                    **state.telemetry,
                    "current_room": room,
                    "position_updated": datetime.fromtimestamp(path.latest.timestamp, UTC),
                }
                robots[key] = replace(state, telemetry=telemetry)
        self._schedule_live_expiration(now)

    def _schedule_live_expiration(self, now):
        if self._cancel_live_expiration is not None:
            self._cancel_live_expiration()
            self._cancel_live_expiration = None
        active = [
            path.latest.expires
            for path in self._live_paths.values()
            if path.latest.expires > now.timestamp()
        ]
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
            return result

    async def _read_account_state(self):
        session = await self.client.ensure_session()
        positions = {}
        timelines = {}
        if self.show_maps and (topics := await self._live_topics(session)):
            pending = self._timeline_requests(topics, self._clock())
            documents = await self._executor(
                self._read, session, FAST_SHADOWS, topics, positions, pending, timelines
            )
        else:
            documents = await self._executor(self._read, session)
        observed_at = datetime.now(UTC)
        await self._optional_sources(session, self._clock())
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
                "details_available": bool(self._details.get(robot_id)),
                "parts_available": bool(self._parts.get(robot_id)),
            }
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
            if self.show_maps:
                telemetry.update(self._timeline_metrics(state, timelines.get(key), now))
            if zone_name := telemetry.get("robot_timezone"):
                zone = await dt_util.async_get_time_zone(zone_name)
                if zone is None:
                    telemetry["robot_timezone"] = None
                if "cloud_schedule_times" in telemetry:
                    telemetry["next_cloud_schedule"] = (
                        next_weekly_start(telemetry, zone, now) if zone is not None else None
                    )
            result[key] = self._add_map_capabilities(replace(state, telemetry=telemetry))
        if self.show_maps:
            await self._update_live_paths(result, positions, now)
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
        self._reconcile_preparations(result)
        return result

    def _reconcile_preparations(self, robots):
        for robot_id, confirmation in tuple(self._preparations.items()):
            state = robots.get(robot_id)
            outcome = confirmation.result(control_snapshot(state) if state else None, self._clock())
            if outcome is not None:
                self.command_status[robot_id] = outcome
                del self._preparations[robot_id]

    def _notify_status(self, robot_id, value):
        if value != "submitted":
            self._preparations.pop(robot_id, None)
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

    async def _resolve_areas(self, robot_id, segments):
        async with self._io_lock:
            return await self._resolve_current_areas(robot_id, segments)

    async def _resolve_current_areas(self, robot_id, segments):
        state = (self.data or {}).get(robot_id)
        if not state or state.capabilities.persistent_maps is not True:
            raise action_error("unsupported_areas", "This robot has no available cleaning map")
        maps = await self._read_map_action(self._read_maps, robot_id)
        try:
            return resolve_segments(maps, segments)
        except ValueError:
            raise action_error("unsupported_areas", "Select areas on one current map") from None

    async def _read_map_action(self, read, *args):
        now = self._clock()
        if now < self._read_retry_until:
            raise action_error("robot_unavailable", "Waiting to retry Roomba Home")
        if now < self._maps_retry_until:
            raise action_error("map_rate_limited", "Roomba Home rate limited map requests")
        try:
            return await read(*args)
        except AuthenticationError:
            raise
        except RateLimited as error:
            self._defer_maps(self._clock(), error.retry_after)
            raise action_error(
                "map_rate_limited", "Roomba Home rate limited map requests"
            ) from None
        except Exception:
            raise action_error("map_unavailable", "Could not read the current map") from None

    async def _resolve_point(self, robot_id, region_id, x, y):
        async with self._io_lock:
            state = (self.data or {}).get(robot_id)
            if not state or not supports_point_clean(state.capabilities.digital_spot):
                raise action_error("unsupported_point", "This robot cannot clean a mapped point")
            area = await self._resolve_current_areas(robot_id, [region_id])
            if area.regions[0].kind is not RegionKind.ROOM:
                raise action_error("point_requires_room", "Select a mapped room")
            bundle = await self._read_map_action(
                self.client.map_geometry, area.map_id, area.version_id
            )
        try:
            return await self._executor(resolve_room_point, bundle, area, x, y)
        except ProtocolError:
            raise action_error("map_unavailable", "Could not read the current map") from None
        except ValueError:
            raise action_error("invalid_map_point", "Select a point within the room") from None

    async def async_clean_point(self, robot_id, region_id, x, y):
        async with self._robot_operation(robot_id):
            try:
                target = await self._resolve_point(robot_id, region_id, x, y)
                await execute_control(
                    RobotControlAdapter(self, robot_id, target),
                    Command.POINT_CLEAN,
                    CleaningProfile(),
                )
            except AuthenticationError as error:
                self._notify_status(robot_id, "unconfirmed")
                raise ConfigEntryAuthFailed("Authentication required") from error
            except ControlError as error:
                raise action_error(error.key, error.key) from None

    async def async_list_cleaning_estimates(self, robot_id, segments):
        async with self._io_lock:
            if self._closed or robot_id not in self.selected:
                raise action_error("not_configured", "Robot is not configured")
            if self._clock() < max(self._read_retry_until, self._estimates_retry_until):
                raise action_error("estimate_rate_limited", "Waiting to retry time estimates")
            state = (self.data or {}).get(robot_id)
            if state is None or self._maps_available.get(robot_id) is not True:
                raise action_error("map_unavailable", "Could not read the current map")
            try:
                target = resolve_segments(self.maps_for_robot(robot_id), segments)
            except ValueError:
                raise action_error("unsupported_areas", "Select areas on one current map") from None
            if any(region.kind is not RegionKind.ROOM for region in target.regions):
                raise action_error("estimate_requires_rooms", "Select rooms for time estimates")
            try:
                return await self.client.cleaning_time_estimates(
                    robot_id, target, state.capabilities.cleaning
                )
            except AuthenticationError as error:
                raise ConfigEntryAuthFailed("Authentication required") from error
            except RateLimited as error:
                self._estimates_retry_until = self._clock() + error.retry_after
                raise action_error(
                    "estimate_rate_limited", "Waiting to retry time estimates"
                ) from None
            except Exception as error:
                _LOGGER.debug("Time estimate request failed: %s", type(error).__name__)
                raise action_error(
                    "estimate_unavailable", "Could not read time estimates"
                ) from None

    async def async_schedule_action(
        self, robot_id, schedule_id=None, *, weekdays=None, time=None, enabled=None
    ):
        async with self._schedule_transaction(robot_id, write=schedule_id is not None):
            if schedule_id is None:
                return {"schedules": await self.client.list_weekly_schedules(robot_id)}
            if enabled is None:
                return await self.client.update_weekly_schedule(
                    robot_id, schedule_id, weekdays, time
                )
            return await self.client.set_weekly_schedule_enabled(robot_id, schedule_id, enabled)

    async def async_create_cleaning_schedule(
        self, robot_id, name, weekdays, time, segments, overrides
    ):
        async with self._schedule_transaction(robot_id, write=True) as state:
            target = await self._resolve_current_areas(robot_id, segments)
            profiles = self._area_profiles(self.profile(robot_id), target, overrides)
            try:
                for profile in profiles:
                    profile.validate(state.capabilities.cleaning)
            except ValueError:
                raise action_error(
                    "unsupported_profile", "Invalid schedule cleaning settings"
                ) from None
            return await self.client.create_weekly_schedule(
                robot_id, name, weekdays, time, replace(target, profiles=profiles)
            )

    async def async_remove_cleaning_schedule(self, robot_id, schedule_id):
        async with self._schedule_transaction(robot_id, write=True):
            return await self.client.remove_weekly_schedule(robot_id, schedule_id)

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
        self, robot_id, command: Command, *, segments=None, overrides=(), map_revision=None
    ):
        async with self._robot_operation(robot_id):
            try:
                target = None
                if segments is not None:
                    target = await self._resolve_areas(robot_id, segments)
                    if map_revision is not None and map_revision != (
                        target.map_id,
                        target.version_id,
                    ):
                        raise action_error("map_changed", "The map changed. Review your selection.")
                profile = self.profile(robot_id)
                area_profiles = ()
                if overrides:
                    area_profiles = self._area_profiles(profile, target, overrides)
                    target = replace(target, profiles=area_profiles)
                await execute_control(
                    RobotControlAdapter(self, robot_id, target),
                    command,
                    area_profiles[0] if area_profiles else profile,
                    new_mission=target is not None,
                    area_profiles=area_profiles,
                )
            except AuthenticationError as error:
                self._notify_status(robot_id, "unconfirmed")
                raise ConfigEntryAuthFailed("Authentication required") from error
            except ControlError as error:
                raise action_error(error.key, error.key) from None

    async def async_set_cleaning_setting(
        self, robot_id, setting: CleaningSetting, value: int | bool
    ):
        """Update one default and verify it without starting a mission."""
        async with self._robot_operation(robot_id):
            await self._refresh_for_command()
            try:
                await self._write_cleaning_setting(robot_id, setting, value)
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

    async def _write_cleaning_setting(self, robot_id, setting, value):
        async with self._io_lock:
            state = (self.data or {}).get(robot_id)
            if state is None or not self.last_update_success or state.connected is not True:
                raise action_error("robot_setting_unavailable", "Robot settings are unavailable")
            if state.cycle != "none" or state.activity not in {"idle", "docked"}:
                raise action_error("robot_setting_active", "End the active mission first")
            capabilities = state.capabilities.cleaning
            if not isinstance(setting, CleaningSetting) or not setting.accepts(value, capabilities):
                raise action_error("unsupported_profile", "This cleaning setting is not supported")
            if (
                setting is CleaningSetting.AUTO_EVACUATION_AREA
                and not state.capabilities.supports_auto_evacuation_area
            ):
                raise action_error("unsupported_dock_action", "An evacuation dock is required")
            session = await self.client.ensure_session()
            sender = MqttCommandSender(session, robot_id)
            if not setting.accepts(value, sender.capabilities):
                raise action_error("unsupported_profile", "This cleaning setting is not supported")
            mqtt = replace(sender.profile, devices={robot_id: sender.profile.devices[robot_id]})
            reader = MqttShadowReader(mqtt, timeout=5)
            document, telemetry = await self._read_cleaning_settings(reader)
            observed = setting.observed(telemetry, capabilities)
            if observed is None:
                raise action_error("robot_setting_unavailable", "Robot settings are unavailable")
            if observed == value:
                self._cache_cleaning_setting(robot_id, setting, document, telemetry)
                return
            self._details_due = 0
            try:
                await self._executor(sender.write_cleaning_setting, setting, value)
            except (OSError, ProtocolError) as error:
                # The publication can have succeeded before the acknowledgement was lost.
                _LOGGER.debug("Robot settings write not acknowledged: %s", type(error).__name__)

        for delay in (0, 2, 4, 8):
            if delay:
                await self._sleep(delay)
            async with self._io_lock:
                try:
                    document, telemetry = await self._read_cleaning_settings(reader)
                except OSError, ProtocolError:
                    continue
                if setting.observed(telemetry, capabilities) == value:
                    self._cache_cleaning_setting(robot_id, setting, document, telemetry)
                    return
        raise action_error("robot_setting_unconfirmed", "The robot did not confirm the setting")

    async def _read_cleaning_settings(self, reader):
        replies = await self._executor(reader.read, ("rw-settings",))
        document = next((reply.document for reply in replies if reply.accepted), {})
        return document, project_telemetry({"rw-settings": document})

    def _cache_cleaning_setting(self, robot_id, setting, document, telemetry):
        self._details.setdefault(robot_id, {})["rw-settings"] = document
        if state := (self.data or {}).get(robot_id):
            updated = {**state.telemetry, setting.value: telemetry[setting.value]}
            self.data[robot_id] = replace(state, telemetry=updated)
            self.async_update_listeners()

    async def async_close(self):
        self._closed = True
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
            self._preparations.clear()
            if self._cancel_live_expiration is not None:
                self._cancel_live_expiration()
                self._cancel_live_expiration = None
            self._live_announcements.clear()
            self._live_timelines.clear()
            self._timeline_due.clear()
            self._live_paths.clear()
            self._floor_plans.clear()


class RobotControlAdapter:
    """Bind one robot to the application port, owning HA/provider translation."""

    def __init__(self, coordinator, robot_id, target: AreaTarget | PointTarget | None = None):
        self.coordinator = coordinator
        self.robot_id = robot_id
        self.target = target

    @property
    def active(self):
        return not self.coordinator._closed

    async def refresh(self):
        coordinator = self.coordinator
        await coordinator._refresh_for_command()
        state = (coordinator.data or {}).get(self.robot_id)
        if state is None or not coordinator.last_update_success:
            return ControlState(None, None, None, None, CleaningCapabilities())
        return control_snapshot(state)

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
        self.coordinator._preparations.setdefault(
            self.robot_id,
            PreparationConfirmation(
                plan, state.mission_identity, self.clock() + PREPARATION_CONFIRMATION_SECONDS
            ),
        )
        self.report("submitted")

    async def wait(self, seconds):
        await self.coordinator._sleep(seconds)

    def clock(self):
        return self.coordinator._clock()


def control_snapshot(state):
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
