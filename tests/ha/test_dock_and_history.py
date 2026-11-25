"""Actual HA entities and service routing with a synthetic dock and history."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.vacuum import VacuumEntityFeature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry, entity_registry

from custom_components.roomba_home.binary_sensor import RoombaMetricBinary, binary_candidates
from custom_components.roomba_home.button import DOCK_BUTTONS, RoombaDockButton
from custom_components.roomba_home.const import DOMAIN
from custom_components.roomba_home.coordinator import RoombaCoordinator, dock_snapshot
from custom_components.roomba_home.core.actions import Command
from custom_components.roomba_home.core.capabilities import DockCapabilities
from custom_components.roomba_home.core.cleaning import CleaningMode
from custom_components.roomba_home.core.errors import AuthenticationError, RateLimited
from custom_components.roomba_home.core.history import ended_mission_start
from custom_components.roomba_home.sensor import RoombaMetricSensor
from custom_components.roomba_home.vacuum import RoombaVacuum

ADVANCED = DockCapabilities(True, True, True, True, True, False)
HEALTHY = {
    "dock_known": True,
    "dock_error": 0,
    "evacuation_state": 301,
    "refill_state": 401,
    "pad_wash_state": 601,
    "pad_dry_state": 701,
    "detected_pad": "padPlate",
    "tank_present": True,
    "part_67_usage": 20,
    "part_202_usage": 15,
}


@pytest.fixture
async def account(hass, entry, robot_states):
    first = robot_states["fixture-0"]
    robot_states["fixture-0"] = replace(
        first,
        telemetry=dict(HEALTHY),
        capabilities=replace(
            first.capabilities, dock=ADVANCED, history=True, locate=True, maintenance=True
        ),
    )
    with patch.object(
        RoombaCoordinator, "_async_update_data", AsyncMock(return_value=robot_states)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    yield entry.runtime_data
    await hass.config_entries.async_unload(entry.entry_id)


def entity_id(hass, entry, slug, domain="button"):
    return entity_registry.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.unique_id}_fixture-0_{slug}"
    )


async def test_dock_buttons_and_telemetry_belong_to_the_docks_child_device(hass, entry, account):
    registry = entity_registry.async_get(hass)
    devices = device_registry.async_get(hass)
    parent_id = registry.async_get("vacuum.robot_0").device_id
    dock_id = registry.async_get(entity_id(hass, entry, "wash_mop")).device_id
    dock = devices.async_get(dock_id)
    assert dock.parent_device_id == parent_id
    assert dock.name == "Dock"
    for slug in ("empty_bin", "wash_mop", "dry_mop", "stop_drying"):
        identifier = entity_id(hass, entry, slug)
        assert identifier and registry.async_get(identifier).device_id == dock_id
    for slug in ("pad_wash_state", "pad_wash_error", "dock_error", "part_202_usage"):
        assert registry.async_get(entity_id(hass, entry, slug, "sensor")).device_id == dock_id
    for slug in ("dock_problem", "dock_clean_water", "dock_maintenance_required"):
        assert (
            registry.async_get(entity_id(hass, entry, slug, "binary_sensor")).device_id == dock_id
        )
    for slug in ("battery", "part_67_usage"):
        assert registry.async_get(entity_id(hass, entry, slug, "sensor")).device_id == parent_id
    assert (
        registry.async_get(entity_id(hass, entry, "dock_known", "binary_sensor")).device_id
        == parent_id
    )
    assert (
        devices.async_get_child_device_by_identifier(
            (DOMAIN, f"{entry.unique_id}_fixture-1_dock"), entry.entry_id
        )
        is None
    )
    assert entity_id(hass, entry, "refill_tank") is None
    assert not registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.unique_id}_fixture-1_wash_mop"
    )
    assert hass.states.get(entity_id(hass, entry, "stop_drying")).state == "unavailable"
    account.async_command = AsyncMock()
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id(hass, entry, "wash_mop")}, blocking=True
    )
    account.async_command.assert_awaited_once_with("fixture-0", Command.WASH_MOP)


async def test_dock_telemetry_can_discover_its_parent_before_vacuum_setup(
    hass, entry, robot_states
):
    coordinator = RoombaCoordinator(hass, entry)
    coordinator.data = robot_states
    devices = device_registry.async_get(hass)
    identity = (DOMAIN, f"{entry.unique_id}_fixture-0")
    assert devices.async_get_device_by_identifier(identity, entry.entry_id) is None
    sensor = RoombaMetricSensor(coordinator, "fixture-0", "pad_wash_state")
    parent = devices.async_get_device_by_identifier(identity, entry.entry_id)
    assert sensor.device_info.parent_device_id == parent.id


async def test_wash_button_is_available_during_drying(hass, entry, account):
    robot = account.data["fixture-0"]
    account.async_set_updated_data(
        {**account.data, "fixture-0": replace(robot, telemetry={**HEALTHY, "pad_dry_state": 702})}
    )
    wash_button = entity_id(hass, entry, "wash_mop")
    assert hass.states.get(wash_button).state != "unavailable"
    account.async_command = AsyncMock()
    await hass.services.async_call("button", "press", {"entity_id": wash_button}, blocking=True)
    account.async_command.assert_awaited_once_with("fixture-0", Command.WASH_MOP)


async def test_reloading_moves_existing_dock_entities_to_child_without_renaming(
    hass, entry, account
):
    registry = entity_registry.async_get(hass)
    parent = registry.async_get("vacuum.robot_0").device_id
    identifier = entity_id(hass, entry, "pad_wash_state", "sensor")
    current = registry.async_get(identifier)
    dock = current.device_id
    current = registry.async_update_entity(
        identifier,
        new_entity_id="sensor.robot_0_mop_washing_state_code",
        device_id=parent,
        name="Fixture wash state",
    )
    with patch.object(
        RoombaCoordinator, "_async_update_data", AsyncMock(return_value=account.data)
    ):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    reloaded = registry.async_get(current.entity_id)
    assert (reloaded.id, reloaded.unique_id, reloaded.entity_id) == (
        current.id,
        current.unique_id,
        current.entity_id,
    )
    assert reloaded.name == "Fixture wash state"
    assert reloaded.device_id == dock


async def test_dock_data_loss_keeps_existing_child_and_blocks_unsupported_discovery(
    hass, entry, account
):
    registry = entity_registry.async_get(hass)
    state = account.data["fixture-0"]
    child_entity = entity_id(hass, entry, "pad_wash_state", "sensor")
    drying_entity = entity_id(hass, entry, "pad_dry_state", "sensor")
    dock_id = registry.async_get(child_entity).device_id
    new_telemetry = {**state.telemetry, "dock_tank_level": 1, "part_147_usage": 7}
    unavailable = replace(
        state,
        telemetry=new_telemetry,
        capabilities=replace(state.capabilities, dock=DockCapabilities(recognized=False)),
    )
    account.async_set_updated_data({**account.data, "fixture-0": unavailable})
    await hass.async_block_till_done()
    assert hass.states.get(child_entity).state == "unavailable"
    assert entity_id(hass, entry, "dock_tank_level", "sensor") is None
    assert entity_id(hass, entry, "part_147_usage", "sensor") is None
    new_telemetry.pop("pad_dry_state")
    account.async_set_updated_data(
        {**account.data, "fixture-0": replace(state, telemetry=new_telemetry)}
    )
    await hass.async_block_till_done()
    assert hass.states.get(child_entity).state == "601"
    assert hass.states.get(drying_entity).state == "unknown"
    assert (
        registry.async_get(entity_id(hass, entry, "dock_tank_level", "sensor")).device_id == dock_id
    )


async def test_locate_is_a_standard_vacuum_service_and_not_duplicated(hass, account):
    vacuum = RoombaVacuum(account, "fixture-0")
    assert VacuumEntityFeature.LOCATE in vacuum.supported_features
    assert "locate" not in DOCK_BUTTONS
    account.async_command = AsyncMock()
    await hass.services.async_call(
        "vacuum", "locate", {"entity_id": "vacuum.robot_0"}, blocking=True
    )
    account.async_command.assert_awaited_once_with("fixture-0", Command.LOCATE)


async def test_fault_or_dock_deregistration_makes_actions_unavailable(account):
    state = account.data["fixture-0"]
    button = RoombaDockButton(account, state.robot_id, "wash_mop")
    assert button.available
    account.data[state.robot_id] = replace(state, telemetry={**state.telemetry, "dock_error": 517})
    assert not button.available
    account.data[state.robot_id] = replace(state, connected=False)
    assert not button.available
    account.data[state.robot_id] = replace(
        state, capabilities=replace(state.capabilities, dock=DockCapabilities(recognized=False))
    )
    assert not button.available


async def test_stop_drying_remains_available_during_the_drying_cycle(account):
    state = account.data["fixture-0"]
    account.data[state.robot_id] = replace(
        state, cycle="dry", telemetry={**state.telemetry, "pad_dry_state": 702}
    )
    assert RoombaDockButton(account, state.robot_id, "stop_drying").available
    assert not RoombaDockButton(account, state.robot_id, "empty_bin").available


@pytest.mark.parametrize("mode", [CleaningMode.VACUUM, CleaningMode.MOP])
async def test_manual_wash_keeps_robot_docked_and_blocks_mission_start(hass, entry, account, mode):
    state = account.data["fixture-0"]
    account.async_set_updated_data(
        {
            **account.data,
            state.robot_id: replace(
                state,
                phase="padWash",
                cycle="none",
                telemetry={**state.telemetry, "pad_wash_state": 602, "not_ready_code": 0},
            ),
        }
    )
    await account.async_set_profile(state.robot_id, mode=mode)
    await hass.async_block_till_done()
    assert hass.states.get("vacuum.robot_0").state == "docked"
    assert hass.states.get(entity_id(hass, entry, "ready", "binary_sensor")).state == "off"
    assert hass.states.get(entity_id(hass, entry, "pad_wash_state", "sensor")).state == "602"
    assert hass.states.get(entity_id(hass, entry, "dry_mop")).state == "unavailable"

    with (
        patch.object(account, "_refresh_for_command", AsyncMock()),
        patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender,
    ):
        with pytest.raises(HomeAssistantError) as error:
            await hass.services.async_call(
                "vacuum", "start", {"entity_id": "vacuum.robot_0"}, blocking=True
            )
        assert error.value.translation_key == "robot_not_ready"
        sender.assert_not_called()


@pytest.mark.parametrize("code,expected", [("padPlate", True), ("none", False), (None, None)])
async def test_pad_presence_only_uses_reported_detection(account, code, expected):
    state = account.data["fixture-0"]
    account.data[state.robot_id] = replace(
        state, telemetry={**state.telemetry, "detected_pad": code}
    )
    binary = RoombaMetricBinary(account, state.robot_id, "mop_attached")
    assert binary.is_on is expected
    assert dock_snapshot(account.data[state.robot_id]).pad_attached is expected


@pytest.mark.parametrize(
    "key,extra,expected",
    [
        ("dock_problem", {"dock_error": 517}, True),
        ("dock_problem", {"dock_error": 0}, False),
        ("dock_problem", {"dock_error": None}, None),
        ("dock_clean_water", {"refill_state": 451}, True),
        ("dock_clean_water", {"refill_state": 401}, False),
        ("dock_clean_water", {"refill_state": None}, None),
        ("maintenance_required", {"part_67_usage": 100}, True),
        ("maintenance_required", {"part_67_usage": 20}, False),
        ("maintenance_required", {"part_67_usage": None, "part_202_usage": None}, None),
        ("dock_maintenance_required", {"part_202_usage": 100}, True),
        ("dock_maintenance_required", {"part_67_usage": 100}, False),
    ],
)
async def test_diagnostics_distinguish_faults_healthy_and_missing_readings(
    account, key, extra, expected
):
    state = account.data["fixture-0"]
    state = replace(state, telemetry={**state.telemetry, **extra})
    account.data[state.robot_id] = state
    assert (key, RoombaMetricBinary) in list(binary_candidates(state))
    assert RoombaMetricBinary(account, state.robot_id, key).is_on is expected


async def test_unsupported_dock_parts_are_not_additional_requirements(account):
    state = account.data["fixture-0"]
    caps = DockCapabilities(recognized=True, evacuation=False, wash=False, dry=False, refill=False)
    account.data[state.robot_id] = replace(
        state,
        capabilities=replace(state.capabilities, dock=caps),
        telemetry={"dock_known": True, "dock_error": 0},
    )
    assert RoombaMetricBinary(account, state.robot_id, "dock_problem").is_on is False
    assert RoombaMetricBinary(account, state.robot_id, "dock_clean_water").is_on is None
    assert ("dock_clean_water", RoombaMetricBinary) not in list(
        binary_candidates(account.data[state.robot_id])
    )
    assert ("dock_maintenance_required", RoombaMetricBinary) not in list(
        binary_candidates(account.data[state.robot_id])
    )
    assert RoombaMetricBinary(account, state.robot_id, "dock_maintenance_required").is_on is None
    account.data[state.robot_id] = replace(
        state, capabilities=replace(state.capabilities, dock=replace(caps, recognized=False))
    )
    assert RoombaMetricBinary(account, state.robot_id, "dock_problem").is_on is None


async def test_history_has_separate_cadence_and_summaries(account):
    account.client.mission_history = AsyncMock(return_value={"history_count": 1})
    await account._refresh_history(account.data, 0)
    await account._refresh_history(account.data, 1799)
    account.client.mission_history.assert_awaited_once_with("fixture-0")
    assert account._history == {"fixture-0": {"history_count": 1}}
    state = account.data["fixture-0"]
    account.data[state.robot_id] = replace(
        state,
        telemetry={
            **state.telemetry,
            "last_mission_outcome": "completed",
            "last_mission_modes": ("vacuum", "mop"),
            "last_mission_mode_statistics": {"vacuum": {"duration_minutes": 10, "area_m2": 8}},
            "last_mission_started_at_dock": True,
        },
    )
    summary = RoombaMetricSensor(account, state.robot_id, "last_mission_outcome")
    assert summary.native_value == "completed"
    assert summary.extra_state_attributes == {
        "cleaning_modes": ("vacuum", "mop"),
        "mode_statistics": {"vacuum": {"duration_minutes": 10, "area_m2": 8}},
        "started_at_dock": True,
    }
    assert summary.options == ["completed", "cancelled", "incomplete", "stuck"]


async def test_last_mission_component_times_are_reported_with_units(hass, entry, account):
    state = account.data["fixture-0"]
    durations = {
        "last_mission_active_duration": 14,
        "last_mission_pause_duration": 2,
        "last_mission_charge_duration": 0,
    }
    account.async_set_updated_data(
        {
            **account.data,
            "fixture-0": replace(state, telemetry={**state.telemetry, **durations}),
        }
    )
    await hass.async_block_till_done()
    for key, value in durations.items():
        sensor = hass.states.get(entity_id(hass, entry, key, "sensor"))
        assert sensor.state == str(value)
        assert sensor.attributes["unit_of_measurement"] == "min"
        assert sensor.attributes["device_class"] == "duration"


async def test_mission_origins_are_distinct_sensors(hass, entry, account):
    state = account.data["fixture-0"]
    origins = {"mission_initiator": "cloud", "last_mission_initiator": "rmtApp"}
    account.async_set_updated_data(
        {**account.data, state.robot_id: replace(state, telemetry={**state.telemetry, **origins})}
    )
    await hass.async_block_till_done()
    for key, value in origins.items():
        sensor = hass.states.get(entity_id(hass, entry, key, "sensor"))
        assert sensor.state == value
        assert RoombaMetricSensor(account, state.robot_id, key).entity_category == "diagnostic"


MARK = datetime(2026, 11, 23, 22, tzinfo=UTC)


@pytest.mark.parametrize(
    ("old_cycle", "new_cycle", "old_start", "new_start", "old_link", "new_link", "expected"),
    [
        ("clean", "dock", MARK, MARK + timedelta(seconds=1), True, True, MARK),
        ("spot", "none", MARK, None, True, True, MARK),
        ("none", "dock", None, MARK, True, True, MARK),
        ("none", "none", MARK, MARK, True, True, None),
        ("none", "none", MARK, MARK - timedelta(seconds=1), True, True, None),
        ("clean", "none", MARK, MARK, False, True, None),
        ("clean", "none", MARK, MARK, True, None, None),
        ("clean", "clean", MARK, MARK, True, True, None),
        ("clean", None, MARK, None, True, True, None),
    ],
)
def test_history_detects_finished_missions_without_assuming_missing_state(
    account, old_cycle, new_cycle, old_start, new_start, old_link, new_link, expected
):
    state = account.data["fixture-0"]
    before = replace(
        state, cycle=old_cycle, connected=old_link, telemetry={"mission_started": old_start}
    )
    after = replace(
        state, cycle=new_cycle, connected=new_link, telemetry={"mission_started": new_start}
    )
    assert ended_mission_start(before, after) == expected
    assert ended_mission_start(None, after) is None


async def test_finished_mission_refreshes_only_that_robot_and_retries_once(account):
    key = "fixture-0"
    state = account.data[key]
    other = account.data["fixture-1"]
    before = replace(state, cycle="clean", phase="run", telemetry={"mission_started": MARK})
    after = replace(before, cycle="none", phase="charge")
    account.async_set_updated_data(
        {
            **account.data,
            key: before,
            other.robot_id: replace(other, capabilities=replace(other.capabilities, history=True)),
        }
    )
    account._history_due = 1800
    old_summary = {"history_count": 1, "last_mission_started": MARK - timedelta(minutes=9)}
    new_summary = {
        "history_count": 2,
        "last_mission_started": MARK - timedelta(seconds=1),
        "last_mission_error": 48,
        "last_mission_target": "temporary_zones",
    }
    target = {**account.data, key: after}
    account._history = {key: old_summary, "fixture-1": {"history_count": 2}}
    account.client.mission_history = AsyncMock(side_effect=[old_summary, new_summary])
    await account._refresh_history(target, 20)
    await account._refresh_history(target, 21)
    account.async_set_updated_data(target)
    await account._refresh_history(target, 79)
    account.client.mission_history.assert_awaited_once_with(key)
    await account._refresh_history(target, 80)
    await account._refresh_history(target, 81)
    assert [call.args for call in account.client.mission_history.await_args_list] == [
        (key,),
        (key,),
    ]
    assert account._history[key] == new_summary
    assert account._history["fixture-1"]["history_count"] == 2
    assert not account._history_pending


async def test_short_mission_refresh_respects_provider_backoff_and_bounds_retries(account):
    key = "fixture-0"
    state = account.data[key]
    previous = replace(state, telemetry={"mission_started": MARK - timedelta(minutes=4)})
    account.async_set_updated_data({**account.data, key: previous})
    after = replace(previous, cycle="dock", phase="hmUsrDock", telemetry={"mission_started": MARK})
    robots = {**account.data, key: after}
    account._history_due = 1800
    account.client.mission_history = AsyncMock(
        side_effect=[RateLimited(90), OSError(), {"history_count": 0}]
    )
    await account._refresh_history(robots, 0)
    account.async_set_updated_data(robots)
    await account._refresh_history(robots, 89)
    account.client.mission_history.assert_awaited_once_with(key)
    for now in (90, 149, 150, 210):
        await account._refresh_history(robots, now)
    assert account.client.mission_history.await_count == 3
    assert not account._history_pending
    assert account._history_due == 1800


async def test_history_full_poll_preserves_pending_settle_delay(account):
    key = "fixture-0"
    state = account.data[key]
    previous = replace(state, cycle="clean", telemetry={"mission_started": MARK})
    account.async_set_updated_data({**account.data, key: previous})
    robots = {**account.data, key: replace(previous, cycle="none")}
    account._history_due = 25
    account.client.mission_history = AsyncMock(return_value={"history_count": 0})
    await account._refresh_history(robots, 20)
    await account._refresh_history(robots, 25)
    assert account._history_pending[key].due == 80


async def test_known_finished_mission_does_not_trigger_an_extra_history_read(account):
    key = "fixture-0"
    state = account.data[key]
    previous = replace(state, cycle="clean", telemetry={"mission_started": MARK})
    account.async_set_updated_data({**account.data, key: previous})
    current = {**account.data, key: replace(previous, cycle="none")}
    account._history[key] = {"last_mission_started": MARK}
    account._history_due = 1800
    account.client.mission_history = AsyncMock()
    await account._refresh_history(current, 20)
    account.client.mission_history.assert_not_awaited()


async def test_last_target_sensor_publishes_classification_beside_existing_error_sensor(
    hass, entry, account
):
    key = "fixture-0"
    state = account.data[key]
    account.async_set_updated_data(
        {
            **account.data,
            key: replace(
                state,
                telemetry={
                    **state.telemetry,
                    "last_mission_target": "temporary_zones",
                    "last_mission_target_count": 1,
                    "last_mission_error": 48,
                },
            ),
        }
    )
    await hass.async_block_till_done()
    target = entity_id(hass, entry, "last_mission_target", "sensor")
    assert hass.states.get(target).state == "temporary_zones"
    assert hass.states.get(target).attributes["region_count"] == 1
    assert "rooms" in hass.states.get(target).attributes["options"]
    assert hass.states.get(entity_id(hass, entry, "last_mission_error", "sensor")).state == "48"
    account.async_set_updated_data(
        {
            **account.data,
            key: replace(state, telemetry={**state.telemetry, "last_mission_target": "map_point"}),
        }
    )
    await hass.async_block_till_done()
    assert hass.states.get(target).state == "map_point"
    assert "region_count" not in hass.states.get(target).attributes


async def test_last_recorded_error_does_not_turn_into_a_live_fault(hass, entry, account):
    state = account.data["fixture-0"]
    key = "last_mission_error"
    account.async_set_updated_data(
        {**account.data, state.robot_id: replace(state, telemetry={**state.telemetry, key: 48})}
    )
    await hass.async_block_till_done()
    sensor_id = entity_id(hass, entry, key, "sensor")
    assert hass.states.get(sensor_id).state == "48"
    assert hass.states.get(sensor_id).attributes["meaning"] == "path_blocked"
    assert hass.states.get(entity_id(hass, entry, "mission_error", "sensor")).state == "0"
    account.async_set_updated_data({**account.data, state.robot_id: state})
    await hass.async_block_till_done()
    assert hass.states.get(sensor_id).state == "unknown"
    assert "meaning" not in hass.states.get(sensor_id).attributes


@pytest.mark.parametrize("error", [RateLimited(900), OSError(), AuthenticationError()])
async def test_history_failure_is_isolated_unless_authentication_is_required(account, error):
    account.client.mission_history = AsyncMock(side_effect=error)
    if isinstance(error, AuthenticationError):
        with pytest.raises(AuthenticationError):
            await account._refresh_history(account.data, 0)
    else:
        await account._refresh_history(account.data, 0)
    assert not account._history
    assert account._history_due == 1800
