from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.roomba_home.binary_sensor import RoombaConnected
from custom_components.roomba_home.coordinator import RoombaCoordinator
from custom_components.roomba_home.core.commands import Command
from custom_components.roomba_home.diagnostics import async_get_config_entry_diagnostics
from custom_components.roomba_home.sensor import RoombaBattery, RoombaMissionError
from custom_components.roomba_home.vacuum import RoombaVacuum


@pytest.fixture
async def coordinator(hass, entry, robot_states):
    value = RoombaCoordinator(hass, entry)
    value.async_set_updated_data(robot_states)
    entry.runtime_data = value
    return value


async def test_three_robots_have_distinct_vacuum_sensor_and_device_identities(coordinator):
    entities = [
        kind(coordinator, key)
        for key in coordinator.data
        for kind in (RoombaVacuum, RoombaBattery, RoombaMissionError, RoombaConnected)
    ]
    assert len({e.unique_id for e in entities}) == 12
    assert len({next(iter(e.device_info["identifiers"])) for e in entities}) == 3


@pytest.mark.parametrize(
    "phase,cycle,expected",
    [
        ("run", "clean", "cleaning"),
        ("stop", "clean", "paused"),
        ("stop", "none", "idle"),
        ("hmUsrDock", "dock", "returning"),
        ("charge", "none", "docked"),
        ("future_phase", "clean", None),
    ],
)
async def test_vacuum_projects_activity_without_guessing(coordinator, phase, cycle, expected):
    coordinator.data["fixture-0"] = replace(coordinator.data["fixture-0"], phase=phase, cycle=cycle)
    assert RoombaVacuum(coordinator, "fixture-0").state == expected


@pytest.mark.parametrize("battery", [0, None, 100])
async def test_battery_preserves_zero_and_unknown(coordinator, battery):
    coordinator.data["fixture-0"] = replace(coordinator.data["fixture-0"], battery=battery)
    assert RoombaBattery(coordinator, "fixture-0").native_value is battery


async def test_offline_robot_is_unavailable_while_connectivity_reports_false(coordinator):
    coordinator.data["fixture-0"] = replace(coordinator.data["fixture-0"], connected=False)
    assert not RoombaVacuum(coordinator, "fixture-0").available
    connected = RoombaConnected(coordinator, "fixture-0")
    assert connected.available and connected.is_on is False
    coordinator.last_update_success = False
    assert not connected.available


@pytest.mark.parametrize(
    "method,command",
    [
        ("async_start", Command.VACUUM),
        ("async_pause", Command.PAUSE),
        ("async_stop", Command.CANCEL),
        ("async_return_to_base", Command.DOCK),
    ],
)
async def test_vacuum_actions_use_the_shared_coordinator(coordinator, method, command):
    coordinator.async_command = AsyncMock()
    await getattr(RoombaVacuum(coordinator, "fixture-0"), method)()
    coordinator.async_command.assert_awaited_once_with("fixture-0", command)


async def test_diagnostics_omit_credentials_names_ids_and_profiles(hass, entry, coordinator):
    result = await async_get_config_entry_diagnostics(hass, entry)
    import json

    text = json.dumps(result)
    assert result["robot_count"] == 3
    for value in ("fixture-password", "fixture-login", "fixture-0", "Robot 0", "ANDROID-PRIME-"):
        assert value not in text


async def test_setup_reload_and_unload_preserve_identities_without_duplicate_entities(
    hass, entry, robot_states
):
    with patch.object(
        RoombaCoordinator, "_async_update_data", AsyncMock(return_value=robot_states)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        before = {
            s.entity_id
            for s in hass.states.async_all()
            if s.domain in {"vacuum", "sensor", "binary_sensor"}
        }
        assert before == {
            f"{domain}.robot_{index}{suffix}"
            for index in range(3)
            for domain, suffix in (
                ("vacuum", ""),
                ("sensor", "_battery"),
                ("sensor", "_mission_error"),
                ("sensor", "_last_command"),
                ("binary_sensor", "_connection"),
                ("binary_sensor", "_problem"),
                ("binary_sensor", "_robot_stuck"),
                ("binary_sensor", "_charging_problem"),
                ("binary_sensor", "_docked_during_cleaning"),
                ("binary_sensor", "_preparing_the_mop"),
            )
        }
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        after = {
            s.entity_id
            for s in hass.states.async_all()
            if s.domain in {"vacuum", "sensor", "binary_sensor"}
        }
        assert before == after
        coordinator = entry.runtime_data
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert coordinator._closed and coordinator._shutdown_requested


async def test_failed_platform_unload_keeps_the_coordinator_available(hass, entry, coordinator):
    from custom_components.roomba_home import async_unload_entry

    with patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=False)):
        assert not await async_unload_entry(hass, entry)
    assert not coordinator._closed


async def test_live_entity_updates_preserve_unknown_and_offline_states(hass, entry, robot_states):
    with patch.object(
        RoombaCoordinator, "_async_update_data", AsyncMock(return_value=robot_states)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        updated = {
            **robot_states,
            "fixture-0": replace(robot_states["fixture-0"], phase="run", cycle="clean", battery=0),
            "fixture-1": replace(robot_states["fixture-1"], connected=False),
            "fixture-2": replace(robot_states["fixture-2"], phase="future_phase", battery=None),
        }
        entry.runtime_data.async_set_updated_data(updated)
        await hass.async_block_till_done()
        assert hass.states.get("vacuum.robot_0").state == "cleaning"
        assert hass.states.get("sensor.robot_0_battery").state == "0"
        assert hass.states.get("vacuum.robot_1").state == "unavailable"
        assert hass.states.get("binary_sensor.robot_1_connection").state == "off"
        assert hass.states.get("vacuum.robot_2").state == "unknown"
        assert hass.states.get("sensor.robot_2_battery").state == "unknown"
        assert await hass.config_entries.async_unload(entry.entry_id)
