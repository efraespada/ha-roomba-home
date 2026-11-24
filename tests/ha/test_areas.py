"""HA vacuum areas use associated and current map metadata."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import probatio as vol
import pytest
from homeassistant.components.vacuum import VacuumEntityFeature
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import area_registry, entity_registry
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.roomba_home.const import DOMAIN
from custom_components.roomba_home.coordinator import RoombaCoordinator
from custom_components.roomba_home.core.actions import Command
from custom_components.roomba_home.core.capabilities import (
    DeviceCapabilities,
    DigitalSpotCapability,
)
from custom_components.roomba_home.core.cleaning import CleaningMode, CleaningProfile
from custom_components.roomba_home.core.errors import (
    AuthenticationError,
    ProtocolError,
    RateLimited,
)
from custom_components.roomba_home.core.maps import (
    CleaningRegion,
    PersistentMap,
    RegionKind,
)
from custom_components.roomba_home.sensor import RoombaMetricSensor, sensor_candidates
from custom_components.roomba_home.vacuum import RoombaVacuum

ROOM = CleaningRegion("room-a", RegionKind.ROOM, "Example room")
ZONE = CleaningRegion("zone-b", RegionKind.ZONE, None)
MAP = PersistentMap("map-a", "version.42", "Example map", (ROOM, ZONE))


@pytest.fixture
async def account(hass, entry, robot_states):
    state = robot_states["fixture-0"]
    robot_states["fixture-0"] = replace(
        state, capabilities=replace(state.capabilities, persistent_maps=True)
    )
    coordinator = RoombaCoordinator(hass, entry)
    coordinator.async_set_updated_data(robot_states)
    coordinator.client.maps = AsyncMock(return_value=(MAP,))
    yield coordinator
    await coordinator.async_close()


async def test_maps_are_polled_once_per_window_and_only_for_supporting_robot(account):
    await account._refresh_maps(account.data, 0)
    await account._refresh_maps(account.data, 899)
    account.client.maps.assert_awaited_once_with("fixture-0")
    state = account._add_map_capabilities(account.data["fixture-0"])
    assert state.capabilities.room_regions is True and state.capabilities.zone_regions is True
    assert state.capabilities.map_selection is False
    assert state.telemetry["map_count"] == state.telemetry["room_count"] == 1
    assert state.telemetry["maps_available"] is True
    assert state.telemetry["zone_count"] == 1
    assert ("room_count", RoombaMetricSensor) in list(sensor_candidates(state))
    assert account._add_map_capabilities(account.data["fixture-1"]) is account.data["fixture-1"]
    await account._refresh_maps(account.data, 900)
    assert account.client.maps.await_count == 2


async def test_unavailable_or_invalid_room_queries_never_request_estimates(account):
    endpoint = account.client.cleaning_time_estimates = AsyncMock()
    room = ROOM.segment_id(MAP.map_id)
    with pytest.raises(HomeAssistantError) as error:
        await account.async_list_cleaning_estimates("other-robot", [room])
    assert error.value.translation_key == "not_configured"
    with pytest.raises(HomeAssistantError) as error:
        await account.async_list_cleaning_estimates("fixture-0", [room])
    assert error.value.translation_key == "map_unavailable"
    await account._refresh_maps(account.data, 0)
    for regions, expected in (
        ([room, room], "unsupported_areas"),
        (["wrong-map:rid:room-a"], "unsupported_areas"),
        ([ZONE.segment_id(MAP.map_id)], "estimate_requires_rooms"),
    ):
        with pytest.raises(HomeAssistantError) as error:
            await account.async_list_cleaning_estimates("fixture-0", regions)
        assert error.value.translation_key == expected
    account.data.pop("fixture-0")
    with pytest.raises(HomeAssistantError) as error:
        await account.async_list_cleaning_estimates("fixture-0", [room])
    assert error.value.translation_key == "map_unavailable"
    await account.async_close()
    with pytest.raises(HomeAssistantError) as error:
        await account.async_list_cleaning_estimates("fixture-0", [room])
    assert error.value.translation_key == "not_configured"
    endpoint.assert_not_awaited()


async def test_estimate_read_failures_are_translated_and_rate_limit_is_respected(account):
    await account._refresh_maps(account.data, 0)
    room = ROOM.segment_id(MAP.map_id)
    account._clock = lambda: 100
    endpoint = account.client.cleaning_time_estimates = AsyncMock(side_effect=RateLimited(60))
    for _ in range(2):
        with pytest.raises(HomeAssistantError) as error:
            await account.async_list_cleaning_estimates("fixture-0", [room])
        assert error.value.translation_key == "estimate_rate_limited"
    endpoint.assert_awaited_once()
    account._clock = lambda: 160
    endpoint.side_effect = OSError()
    with pytest.raises(HomeAssistantError) as error:
        await account.async_list_cleaning_estimates("fixture-0", [room])
    assert error.value.translation_key == "estimate_unavailable"
    endpoint.side_effect = AuthenticationError()
    with pytest.raises(ConfigEntryAuthFailed):
        await account.async_list_cleaning_estimates("fixture-0", [room])
    endpoint.side_effect = None
    endpoint.return_value = {"regions": []}
    assert await account.async_list_cleaning_estimates("fixture-0", [room]) == {"regions": []}
    account.client.maps.assert_awaited_once()


async def test_two_maps_enable_map_selection_and_zero_regions_remain_explicit(account):
    account.client.maps.return_value = (MAP, replace(MAP, map_id="map-b", regions=()))
    await account._refresh_maps(account.data, 0)
    assert account._add_map_capabilities(account.data["fixture-0"]).capabilities.map_selection
    account.client.maps.return_value = ()
    await account._refresh_maps(account.data, 900)
    state = account._add_map_capabilities(account.data["fixture-0"])
    assert state.telemetry["room_count"] == state.telemetry["zone_count"] == 0
    assert state.telemetry["maps_available"] is True
    assert state.capabilities.room_regions is False


@pytest.mark.parametrize("failure", [RateLimited(900), ProtocolError("fixture"), OSError()])
async def test_map_read_failures_leave_regular_robot_state_available(account, failure):
    account._clock = lambda: 5
    account.client.maps.side_effect = failure
    await account._refresh_maps(account.data, 5)
    assert account._maps_due == 905 and account.maps_for_robot("fixture-0") == ()
    assert account.data["fixture-0"].activity == "docked"
    state = account._add_map_capabilities(account.data["fixture-0"])
    assert state.telemetry["maps_available"] is False and "map_count" not in state.telemetry


async def test_partial_rate_limit_keeps_each_cached_map_but_marks_only_fresh_reads_available(
    account,
):
    other = account.data["fixture-1"]
    account.data["fixture-1"] = replace(
        other, capabilities=replace(other.capabilities, persistent_maps=True)
    )
    await account._refresh_maps(account.data, 0)
    account.client.maps.side_effect = [(MAP,), RateLimited(120)]
    account._clock = lambda: 900
    await account._refresh_maps(account.data, 900)
    first = account._add_map_capabilities(account.data["fixture-0"])
    second = account._add_map_capabilities(account.data["fixture-1"])
    assert first.telemetry["maps_available"] is True and first.telemetry["room_count"] == 1
    assert second.telemetry["maps_available"] is False and "room_count" not in second.telemetry
    assert account.maps_for_robot("fixture-1") == (MAP,)
    unsupported = replace(other, capabilities=replace(other.capabilities, persistent_maps=False))
    account.data["fixture-1"] = unsupported
    assert account._add_map_capabilities(unsupported) is unsupported
    assert account.maps_for_robot("fixture-1") == ()


@pytest.mark.parametrize("scheduled_first", [True, False])
async def test_map_throttle_is_shared_by_scheduled_and_command_reads(account, scheduled_first):
    now = 50
    account._clock = lambda: now
    account.client.maps.side_effect = RateLimited(180)
    segments = ["map-a:rid:room-a"]
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        if scheduled_first:
            await account._refresh_maps(account.data, now)
        with pytest.raises(HomeAssistantError, match="rate limited map requests"):
            await account.async_command("fixture-0", Command.VACUUM, segments=segments)
        now = 229
        with pytest.raises(HomeAssistantError, match="rate limited map requests"):
            await account.async_command("fixture-0", Command.VACUUM, segments=segments)
        await account._refresh_maps(account.data, now)
        sender.assert_not_called()
    assert account.client.maps.await_count == 1
    now = 230
    account.client.maps.side_effect = None
    target = await account._resolve_areas("fixture-0", segments)
    assert target.map_id == "map-a"
    assert account.client.maps.await_count == 2


async def test_account_read_cooldown_blocks_map_lookup_before_area_commands(account):
    account._clock = lambda: 50
    account._read_retry_until = 60
    with pytest.raises(HomeAssistantError, match="Waiting to retry"):
        await account.async_command("fixture-0", Command.VACUUM, segments=["map-a:rid:room-a"])
    account.client.maps.assert_not_awaited()


async def test_map_authentication_failure_requests_reauth(account):
    account.client.maps.side_effect = AuthenticationError()
    with pytest.raises(AuthenticationError):
        await account._refresh_maps(account.data, 0)


async def test_exponential_read_recovery_is_bounded(account, cloud_session):
    now = 0
    account._clock = lambda: now
    account.client.ensure_session = AsyncMock(side_effect=OSError())
    for seconds in (60, 120, 240, 480, 900, 900):
        with pytest.raises(UpdateFailed) as exc:
            await account._async_update_data()
        assert exc.value.retry_after == seconds
        now += 1
        with pytest.raises(UpdateFailed) as waiting:
            await account._async_update_data()
        assert waiting.value.retry_after == seconds - 1
        now += seconds - 1
    assert account.client.ensure_session.await_count == 6
    account.client.ensure_session = AsyncMock(return_value=cloud_session)
    account._read = Mock(return_value={})
    account._details_due = account._parts_due = account._maps_due = float("inf")
    await account._async_update_data()
    assert account._read_failures == account._read_retry_until == 0


async def test_clean_area_resolves_fresh_map_and_one_publication(account):
    await account._refresh_maps(account.data, 0)
    changed = replace(MAP, version_id="version.43")
    account.client.maps.return_value = (changed,)
    account.client.ensure_session = AsyncMock(return_value=object())
    account.async_refresh = AsyncMock()

    async def wait(delay):
        state = account.data["fixture-0"]
        account.data["fixture-0"] = replace(state, phase="run", cycle="clean")

    account._sleep = wait
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        await account.async_command("fixture-0", Command.VACUUM, segments=["map-a:rid:room-a"])
    args = sender.return_value.send.call_args.args
    assert args[0] == Command.VACUUM
    assert args[2].version_id == changed.version_id and args[2].regions == (ROOM,)
    assert account.maps_for_robot("fixture-0") == (changed,)
    assert account.command_status["fixture-0"] == "confirmed"


@pytest.mark.parametrize(
    "robot,segments",
    [
        ("fixture-0", ["old:rid:removed"]),
        ("fixture-1", ["map-a:rid:room-a"]),
    ],
)
async def test_missing_or_unsupported_area_never_publishes(account, robot, segments):
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        with pytest.raises(HomeAssistantError, match="map"):
            await account.async_command(robot, Command.VACUUM, segments=segments)
        sender.assert_not_called()


async def test_area_auth_failure_is_distinct_from_stale_map(account):
    from homeassistant.exceptions import ConfigEntryAuthFailed

    account.client.maps.side_effect = AuthenticationError()
    with pytest.raises(ConfigEntryAuthFailed):
        await account.async_command("fixture-0", Command.VACUUM, segments=["map-a:rid:room-a"])


async def test_vacuum_features_track_capabilities_and_robot_presence(account):
    vacuum = RoombaVacuum(account, "fixture-0")
    assert VacuumEntityFeature.FAN_SPEED in vacuum.supported_features
    assert vacuum.fan_speed is None
    await vacuum.async_set_fan_speed("3")
    assert vacuum.fan_speed == "3"
    with pytest.raises(HomeAssistantError):
        await vacuum.async_set_fan_speed("99")
    assert VacuumEntityFeature.CLEAN_AREA not in vacuum.supported_features
    account._maps["fixture-0"] = (MAP,)
    assert VacuumEntityFeature.CLEAN_AREA in vacuum.supported_features
    assert [(s.id, s.name) for s in await vacuum.async_get_segments()] == [
        ("map-a:rid:room-a", ROOM.name),
        ("map-a:zid:zone-b", "zone-b"),
    ]
    account.data["fixture-0"] = replace(
        account.data["fixture-0"], capabilities=DeviceCapabilities()
    )
    account._maps.clear()
    assert vacuum.supported_features == VacuumEntityFeature.STATE
    account.data.pop("fixture-0")
    assert vacuum.fan_speed is None and vacuum.supported_features == VacuumEntityFeature.STATE


async def test_actual_home_assistant_clean_area_service_maps_ids(hass, entry, robot_states):
    with patch.object(
        RoombaCoordinator, "_async_update_data", AsyncMock(return_value=robot_states)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data
    coordinator._maps["fixture-0"] = (MAP,)
    coordinator.async_command = AsyncMock()
    registry = entity_registry.async_get(hass)
    area = area_registry.async_get(hass).async_create("Test area")
    registry.async_update_entity_options(
        "vacuum.robot_0", "vacuum", {"area_mapping": {area.id: ["map-a:rid:room-a"]}}
    )
    await hass.services.async_call(
        "vacuum",
        "clean_area",
        {"entity_id": "vacuum.robot_0", "cleaning_area_id": [area.id]},
        blocking=True,
    )
    coordinator.async_command.assert_awaited_once_with(
        "fixture-0", Command.VACUUM, segments=["map-a:rid:room-a"]
    )
    await hass.config_entries.async_unload(entry.entry_id)


async def test_map_outage_preserves_ha_area_mapping_and_blocks_a_stale_command(
    hass, entry, robot_states
):
    robot = robot_states["fixture-0"]
    robot_states["fixture-0"] = replace(
        robot, capabilities=replace(robot.capabilities, persistent_maps=True)
    )
    with patch.object(
        RoombaCoordinator, "_async_update_data", AsyncMock(return_value=robot_states)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    account = entry.runtime_data
    account.client.maps = AsyncMock(return_value=(MAP,))

    async def refresh(now):
        await account._refresh_maps(robot_states, now)
        account.async_set_updated_data(
            {key: account._add_map_capabilities(state) for key, state in robot_states.items()}
        )
        await hass.async_block_till_done()

    await refresh(0)
    registry = entity_registry.async_get(hass)
    vacuum = "vacuum.robot_0"
    area = area_registry.async_get(hass).async_create("Test area")
    mapping = {"area_mapping": {area.id: ["map-a:rid:room-a"]}}
    registry.async_update_entity_options(vacuum, "vacuum", mapping)
    account.client.maps.side_effect = ProtocolError("Fixture response unavailable")
    await refresh(900)
    assert registry.async_get(vacuum).options["vacuum"] == mapping
    assert VacuumEntityFeature.CLEAN_AREA in VacuumEntityFeature(
        hass.states.get(vacuum).attributes["supported_features"]
    )
    availability = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.unique_id}_fixture-0_maps_available"
    )
    assert hass.states.get(availability).state == "off"
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        with pytest.raises(HomeAssistantError, match="current map") as error:
            await hass.services.async_call(
                "vacuum",
                "clean_area",
                {"entity_id": vacuum, "cleaning_area_id": [area.id]},
                blocking=True,
            )
        assert error.value.translation_key == "map_unavailable"
        sender.assert_not_called()
    account.client.maps.side_effect = None
    account.client.maps.return_value = ()
    await refresh(1800)
    assert account.maps_for_robot("fixture-0") == ()
    assert hass.states.get(availability).state == "on"
    assert VacuumEntityFeature.CLEAN_AREA not in VacuumEntityFeature(
        hass.states.get(vacuum).attributes["supported_features"]
    )
    assert registry.async_get(vacuum).options["vacuum"] == mapping
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_per_device_updates_are_isolated_and_reuse_account_refresh(account):
    first, second = (account.robot_updates(f"fixture-{i}") for i in (0, 1))
    left, right, another = Mock(), Mock(), Mock()
    remove_left = first.async_add_listener(left)
    remove_second = second.async_add_listener(right)
    remove_another = first.async_add_listener(another)
    account._notify_status("fixture-0", "pending")
    left.assert_called_once()
    another.assert_called_once()
    right.assert_not_called()
    vacuum = RoombaVacuum(account, "fixture-0")
    account.async_request_refresh = AsyncMock()
    await vacuum.async_update()
    account.async_request_refresh.assert_awaited_once()
    account.async_request_refresh.reset_mock()
    with patch.object(RoombaVacuum, "enabled", False):
        await vacuum.async_update()
    account.async_request_refresh.assert_not_awaited()
    remove_left()
    remove_another()
    remove_second()
    assert not first._callbacks and first._remove_account_listener is None


async def test_local_services_list_regions_and_accept_typed_distinct_preferences(
    hass, entry, robot_states
):
    with patch.object(
        RoombaCoordinator, "_async_update_data", AsyncMock(return_value=robot_states)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    account = entry.runtime_data
    account._maps["fixture-0"] = (MAP,)
    account._maps_available["fixture-0"] = True
    listed = await hass.services.async_call(
        DOMAIN,
        "list_cleaning_regions",
        {"entity_id": "vacuum.robot_0"},
        blocking=True,
        return_response=True,
    )
    assert listed["vacuum.robot_0"]["regions"][0] == {
        "id": "map-a:rid:room-a",
        "name": ROOM.name,
        "map": MAP.name,
    }
    account.async_command = AsyncMock()
    room_id = ROOM.segment_id(MAP.map_id)
    estimates = {"regions": [{"id": room_id, "estimates": [{"duration_seconds": 240}]}]}
    account.client.cleaning_time_estimates = AsyncMock(return_value=estimates)
    results = await hass.services.async_call(
        DOMAIN,
        "list_cleaning_estimates",
        {"entity_id": "vacuum.robot_0", "regions": [room_id]},
        blocking=True,
        return_response=True,
    )
    assert results == {"vacuum.robot_0": estimates}
    robot_id, target, capabilities = account.client.cleaning_time_estimates.await_args.args
    assert robot_id == "fixture-0" and target.regions == (ROOM,)
    assert (target.map_id, target.version_id) == (MAP.map_id, MAP.version_id)
    assert capabilities == robot_states[robot_id].capabilities.cleaning
    account.async_command.assert_not_awaited()
    await hass.services.async_call(
        DOMAIN,
        "clean_regions",
        {
            "entity_id": "vacuum.robot_0",
            "regions": [
                {"id": "map-a:rid:room-a", "mode": "mop", "wetness_level": 2},
                {"id": "map-a:zid:zone-b", "suction_level": 3},
            ],
        },
        blocking=True,
    )
    account.async_command.assert_awaited_once_with(
        "fixture-0",
        Command.VACUUM,
        segments=["map-a:rid:room-a", "map-a:zid:zone-b"],
        overrides=[{"mode": CleaningMode.MOP, "wetness_level": 2}, {"suction_level": 3}],
    )
    await hass.config_entries.async_unload(entry.entry_id)


async def test_native_point_action_dispatches_only_the_validated_point(
    hass, entry, robot_states, make_point_bundle
):
    robot = robot_states["fixture-0"]
    robot_states["fixture-0"] = replace(
        robot,
        capabilities=replace(
            robot.capabilities, persistent_maps=True, digital_spot=DigitalSpotCapability.SUPPORTED
        ),
    )
    with patch.object(
        RoombaCoordinator, "_async_update_data", AsyncMock(return_value=robot_states)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    account = entry.runtime_data
    account.client.maps = AsyncMock(return_value=(MAP,))
    account.client.map_geometry = AsyncMock(return_value=make_point_bundle())
    account.client.ensure_session = AsyncMock(return_value=object())
    account._refresh_for_command = AsyncMock()

    async def wait(_delay):
        state = account.data["fixture-0"]
        account.data["fixture-0"] = replace(
            state,
            phase="run",
            cycle="clean",
            mode=2,
            telemetry={
                **state.telemetry,
                "mission_initiator": "rmtApp",
                "mission_number": 90,
                "mission_started": datetime(2026, 1, 1, tzinfo=UTC),
            },
        )

    account._sleep = wait
    data = {"entity_id": "vacuum.robot_0", "region_id": "map-a:rid:room-a", "x": 0.1, "y": 0.1}
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(
                DOMAIN, "clean_point", {**data, "x": True}, blocking=True
            )
        account.client.maps.assert_not_awaited()
        await hass.services.async_call(DOMAIN, "clean_point", data, blocking=True)
        command, profile, target = sender.return_value.send.call_args.args
        assert command is Command.POINT_CLEAN and profile == CleaningProfile()
        assert target.center == (1.0, 1.0) and target.version_id == "version.42"
        sender.return_value.send.assert_called_once()
        account.client.maps.assert_awaited_once_with("fixture-0")
        account.client.map_geometry.assert_awaited_once_with(MAP.map_id, MAP.version_id)
        assert account.command_status["fixture-0"] == "submitted"
        assert not (
            RoombaVacuum(account, "fixture-0").supported_features & VacuumEntityFeature.CLEAN_SPOT
        )
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("region", "x", "geometry_error", "expected", "read_geometry"),
    [
        ("map:rid:room-a", 0.1, None, "unsupported_areas", False),
        ("map-a:zid:zone-b", 0.1, None, "point_requires_room", False),
        ("map-a:rid:room-a", 0.9, None, "invalid_map_point", True),
        ("map-a:rid:room-a", 0.1, RateLimited(60), "map_rate_limited", True),
        ("map-a:rid:room-a", 0.1, ProtocolError("fixture"), "map_unavailable", True),
        ("map-a:rid:room-a", 0.1, None, "map_unavailable", True),
    ],
)
async def test_point_errors_never_publish_mqtt(
    account, make_point_bundle, region, x, geometry_error, expected, read_geometry
):
    state = account.data["fixture-0"]
    account.data["fixture-0"] = replace(
        state,
        capabilities=replace(state.capabilities, digital_spot=DigitalSpotCapability.SUPPORTED),
    )
    payload = b"malformed" if expected == "map_unavailable" else make_point_bundle()
    account.client.map_geometry = AsyncMock(return_value=payload, side_effect=geometry_error)
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        with pytest.raises(HomeAssistantError) as error:
            await account.async_clean_point("fixture-0", region, x, 0.1)
        assert error.value.translation_key == expected
        assert account.client.map_geometry.await_count == int(read_geometry)
        sender.assert_not_called()


async def test_point_read_honors_capability_and_reauth(account):
    account.client.map_geometry = AsyncMock(side_effect=AuthenticationError())
    region = ROOM.segment_id(MAP.map_id)
    with pytest.raises(HomeAssistantError) as error:
        await account.async_clean_point("fixture-0", region, 0.1, 0.1)
    assert error.value.translation_key == "unsupported_point"
    account.client.maps.assert_not_awaited()
    state = account.data["fixture-0"]
    account.data["fixture-0"] = replace(
        state,
        capabilities=replace(state.capabilities, digital_spot=DigitalSpotCapability.SUPPORTED),
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await account.async_clean_point("fixture-0", region, 0.1, 0.1)
    assert account.command_status["fixture-0"] == "unconfirmed"


async def test_point_action_preserves_a_robot_mission_in_progress(account, make_point_bundle):
    state = account.data["fixture-0"]
    account.data["fixture-0"] = replace(
        state,
        phase="stop",
        cycle="clean",
        mode=2,
        capabilities=replace(state.capabilities, digital_spot=DigitalSpotCapability.SUPPORTED),
    )
    account.client.map_geometry = AsyncMock(return_value=make_point_bundle())
    account._refresh_for_command = AsyncMock()
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        with pytest.raises(HomeAssistantError) as error:
            await account.async_clean_point("fixture-0", ROOM.segment_id(MAP.map_id), 0.1, 0.1)
        assert error.value.translation_key == "unsupported_start"
        sender.assert_not_called()


async def test_profiled_areas_use_each_preference_without_mutating_saved_robot_options(account):
    account.client.ensure_session = AsyncMock(return_value=object())
    account.async_refresh = AsyncMock()

    async def wait(delay):
        state = account.data["fixture-0"]
        account.data["fixture-0"] = replace(state, phase="run", cycle="clean", mode=4)

    account._sleep = wait
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        await account.async_command(
            "fixture-0",
            Command.VACUUM,
            segments=["map-a:rid:room-a", "map-a:zid:zone-b"],
            overrides=[{"mode": CleaningMode.MOP, "wetness_level": 3}, {"suction_level": 2}],
        )
    target = sender.return_value.send.call_args.args[2]
    assert target.profiles == (
        CleaningProfile(CleaningMode.MOP, wetness_level=3),
        CleaningProfile(suction_level=2),
    )
    assert account.profile("fixture-0") == CleaningProfile()


@pytest.mark.parametrize(
    "segments,overrides",
    [
        (None, [{"mode": CleaningMode.MOP}]),
        (["map-a:rid:room-a"], [{}, {}]),
        (["map-a:rid:room-a"], [{"suction_level": "5"}]),
    ],
)
async def test_bad_overrides_do_not_reach_transport(account, segments, overrides):
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        with pytest.raises(HomeAssistantError):
            await account.async_command(
                "fixture-0", Command.VACUUM, segments=segments, overrides=overrides
            )
        sender.assert_not_called()
