import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.roomba_home.binary_sensor import RoombaMetricBinary
from custom_components.roomba_home.const import (
    DOMAIN,
    PARTS_SECONDS,
    POLL_SECONDS,
    SERIAL_REFRESH_SECONDS,
)
from custom_components.roomba_home.coordinator import RoombaCoordinator
from custom_components.roomba_home.core.actions import Command
from custom_components.roomba_home.core.capabilities import DockCapabilities
from custom_components.roomba_home.core.cleaning import CleaningMode
from custom_components.roomba_home.core.client import RoombaClient
from custom_components.roomba_home.core.errors import (
    AuthenticationError,
    ProtocolError,
    RateLimited,
)
from custom_components.roomba_home.core.telemetry import DETAIL_SHADOWS
from custom_components.roomba_home.core.transport import HttpResponse
from custom_components.roomba_home.diagnostics import async_get_config_entry_diagnostics
from custom_components.roomba_home.sensor import RoombaMetricSensor
from custom_components.roomba_home.vacuum import RoombaVacuum


def entity_id(hass, entry, suffix, domain="sensor", robot="fixture-0"):
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.unique_id}_{robot}_{suffix}"
    )


@pytest.fixture
async def loaded(hass, entry, robot_states):
    telemetry = {
        "mission_phase": "charge",
        "mission_cycle": "none",
        "mission_area": 9.29,
        "mission_started": datetime.now(UTC) - timedelta(minutes=2),
        "bin_present": True,
        "bin_full": False,
        "child_lock": False,
        "software_version": "26.9.0",
        "not_ready_code": 0,
        "not_ready_conditions": (),
        "dock_known": True,
        "dock_error": 0,
        "evacuation_state": 301,
        "refill_state": 401,
        "pad_wash_state": 601,
        "pad_dry_state": 701,
        "details_available": True,
        "history_available": True,
        "parts_available": True,
        "schedules_available": True,
        "part_71_usage": 25,
        "part_71_remaining": 200,
        "part_71_used": 100,
        "part_71_count_type": "minutes",
        "part_71_category": "replacement",
    }
    states = {
        **robot_states,
        "fixture-0": replace(
            robot_states["fixture-0"], telemetry=telemetry, observed_at=datetime.now(UTC)
        ),
    }
    with patch.object(RoombaCoordinator, "_async_update_data", AsyncMock(return_value=states)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry.runtime_data


async def test_units_metadata_and_original_identities_are_present(hass, entry, loaded):
    assert (
        hass.states.get(entity_id(hass, entry, "mission_area")).attributes["unit_of_measurement"]
        == "m²"
    )
    assert (
        hass.states.get(entity_id(hass, entry, "part_71_remaining")).attributes[
            "unit_of_measurement"
        ]
        == "min"
    )
    assert (
        hass.states.get(entity_id(hass, entry, "part_71_usage")).attributes["unit_of_measurement"]
        == "%"
    )
    assert hass.states.get("vacuum.robot_0").state == "docked"
    assert hass.states.get("sensor.robot_0_battery").state == "100"
    assert hass.states.get("sensor.robot_0_mission_error").state == "0"
    assert hass.states.get("binary_sensor.robot_0_connection").state == "on"
    devices = list(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id))
    assert len(devices) == 3
    assert any(device.sw_version == "26.9.0" for device in devices)


async def test_new_telemetry_is_discovered_once_and_missing_values_become_unknown(
    hass, entry, loaded
):
    state = loaded.data["fixture-0"]
    loaded.async_set_updated_data(
        {
            **loaded.data,
            "fixture-0": replace(state, telemetry={**state.telemetry, "audio_volume": 0}),
        }
    )
    await hass.async_block_till_done()
    identifier = entity_id(hass, entry, "audio_volume")
    assert hass.states.get(identifier).state == "0"
    source_ids = [
        entity_id(hass, entry, f"{source}_available", "binary_sensor")
        for source in ("history", "schedules")
    ]
    assert all(hass.states.get(identifier).state == "on" for identifier in source_ids)
    count = len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id))
    loaded.async_set_updated_data(
        {
            **loaded.data,
            "fixture-0": replace(
                state,
                telemetry={
                    "details_available": False,
                    "history_available": False,
                    "parts_available": False,
                    "schedules_available": False,
                },
            ),
        }
    )
    await hass.async_block_till_done()
    assert hass.states.get(identifier).state == "unknown"
    assert all(hass.states.get(identifier).state == "off" for identifier in source_ids)
    assert hass.states.get("vacuum.robot_0").state == "docked"
    assert (
        hass.states.get(entity_id(hass, entry, "parts_available", "binary_sensor")).state == "off"
    )
    assert len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)) == count


async def test_problem_events_deduplicate_change_and_clear_in_real_ha(hass, entry, loaded):
    identifier = entity_id(hass, entry, "problems", "event")
    state = loaded.data["fixture-0"]
    loaded.async_set_updated_data({**loaded.data, "fixture-0": replace(state, error=17)})
    await hass.async_block_till_done()
    first = hass.states.get(identifier)
    assert first.attributes["event_type"] == "problem_detected"
    assert first.attributes["source"] == "mission"
    assert first.attributes["code"] == 17
    assert hass.states.get(entity_id(hass, entry, "problem", "binary_sensor")).state == "on"
    for _ in range(10):
        loaded.async_set_updated_data(loaded.data)
    await hass.async_block_till_done()
    assert hass.states.get(identifier).state == first.state
    loaded.async_set_updated_data({**loaded.data, "fixture-0": replace(state, error=18)})
    await hass.async_block_till_done()
    assert hass.states.get(identifier).attributes["event_type"] == "problem_changed"
    assert hass.states.get(identifier).attributes["previous_code"] == 17
    loaded.async_set_updated_data({**loaded.data, "fixture-0": state})
    await hass.async_block_till_done()
    assert hass.states.get(identifier).attributes["event_type"] == "problem_cleared"
    assert hass.states.get(entity_id(hass, entry, "problem", "binary_sensor")).state == "off"


async def test_offline_and_missing_read_dont_emit_false_resolution(hass, entry, loaded):
    identifier = entity_id(hass, entry, "problems", "event")
    state = replace(loaded.data["fixture-0"], error=17)
    loaded.async_set_updated_data({**loaded.data, "fixture-0": state})
    await hass.async_block_till_done()
    loaded.async_set_updated_data({**loaded.data, "fixture-0": replace(state, connected=False)})
    await hass.async_block_till_done()
    value = hass.states.get(identifier)
    assert value.attributes["source"] == "connection"
    assert value.attributes["problem_codes"]["mission"] == 17
    loaded.async_set_update_error(UpdateFailed("fixture transport failure"))
    await hass.async_block_till_done()
    assert hass.states.get(identifier).state == "unavailable"
    loaded.async_set_updated_data({**loaded.data, "fixture-0": replace(state, error=None)})
    await hass.async_block_till_done()
    assert hass.states.get(identifier).attributes["problem_codes"]["mission"] == 17


async def test_reload_preserves_entity_set_and_active_problem_timestamp(hass, entry, loaded):
    identifier = entity_id(hass, entry, "problems", "event")
    state = replace(loaded.data["fixture-0"], error=17)
    states = {**loaded.data, "fixture-0": state}
    loaded.async_set_updated_data(states)
    await hass.async_block_till_done()
    before = hass.states.get(identifier).state
    registry_before = {
        e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    with patch.object(RoombaCoordinator, "_async_update_data", AsyncMock(return_value=states)):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get(identifier).state == before
    assert registry_before == {
        e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


async def test_simultaneous_component_events_are_individually_observable(hass, entry, loaded):
    identifier = entity_id(hass, entry, "problems", "event")
    observed = []

    def listen(event):
        if event.data["entity_id"] == identifier:
            observed.append(event.data["new_state"])

    unsubscribe = hass.bus.async_listen(EVENT_STATE_CHANGED, listen)
    state = loaded.data["fixture-0"]
    loaded.async_set_updated_data(
        {
            **loaded.data,
            "fixture-0": replace(
                state, error=17, telemetry={**state.telemetry, "pad_wash_state": 650}
            ),
        }
    )
    await hass.async_block_till_done()
    unsubscribe()
    changes = [s for s in observed if s and s.attributes.get("event_type") == "problem_detected"]
    assert {s.attributes["source"] for s in changes} == {"mission", "pad_wash"}
    assert len({s.state for s in changes}) == 2


async def test_dock_event_belongs_to_dock_and_excludes_robot_faults(hass, entry, loaded):
    state = loaded.data["fixture-0"]
    assert entity_id(hass, entry, "dock_problems", "event") is None
    recognized = replace(
        state,
        capabilities=replace(state.capabilities, dock=DockCapabilities(True, wash=True)),
    )
    loaded.async_set_updated_data({**loaded.data, "fixture-0": recognized})
    await hass.async_block_till_done()
    robot_event = entity_id(hass, entry, "problems", "event")
    dock_event = entity_id(hass, entry, "dock_problems", "event")
    registry = er.async_get(hass)
    parent = registry.async_get(robot_event).device_id
    dock = dr.async_get(hass).async_get(registry.async_get(dock_event).device_id)
    assert dock.id != parent and dock.parent_device_id == parent

    loaded.async_set_updated_data(
        {
            **loaded.data,
            "fixture-0": replace(
                recognized, error=1026, telemetry={**recognized.telemetry, "pad_wash_state": 654}
            ),
        }
    )
    await hass.async_block_till_done()
    latest = hass.states.get(dock_event)
    assert latest.attributes["source"] == "pad_wash"
    assert latest.attributes["reason"] == "grey_water_dock_tank_level_too_full"
    assert "mission" not in latest.attributes["problem_codes"]
    assert hass.states.get(robot_event).attributes["problem_codes"]["mission"] == 1026

    loaded.async_set_updated_data({**loaded.data, "fixture-0": state})
    await hass.async_block_till_done()
    assert hass.states.get(dock_event).state == "unavailable"
    loaded.async_set_updated_data({**loaded.data, "fixture-0": recognized})
    await hass.async_block_till_done()
    assert entity_id(hass, entry, "dock_problems", "event") == dock_event
    assert hass.states.get(dock_event).attributes["event_type"] == "problem_cleared"


async def test_readiness_event_reaches_ha_with_each_raw_condition(hass, entry, loaded):
    state = loaded.data["fixture-0"]
    loaded.async_set_updated_data(
        {
            **loaded.data,
            "fixture-0": replace(
                state, telemetry={**state.telemetry, "not_ready_conditions": (6, 4)}
            ),
        }
    )
    await hass.async_block_till_done()
    event = hass.states.get(entity_id(hass, entry, "problems", "event"))
    assert event.attributes["source"] == "readiness_conditions"
    assert event.attributes["condition_codes"] == [4, 6]
    assert hass.states.get(entity_id(hass, entry, "ready", "binary_sensor")).state == "off"
    assert hass.states.get(entity_id(hass, entry, "problem", "binary_sensor")).state == "on"


async def test_last_mission_command_is_an_enum_discovered_from_history(hass, entry, loaded):
    state = loaded.data["fixture-0"]
    assert entity_id(hass, entry, "last_mission_command") is None
    loaded.async_set_updated_data(
        {
            **loaded.data,
            state.robot_id: replace(
                state, telemetry={**state.telemetry, "last_mission_command": "point_clean"}
            ),
        }
    )
    await hass.async_block_till_done()
    identifier = entity_id(hass, entry, "last_mission_command")
    entity = hass.states.get(identifier)
    assert entity.state == "point_clean"
    assert entity.attributes["options"] == ["start", "spot", "point_clean"]
    loaded.async_set_updated_data({**loaded.data, state.robot_id: state})
    await hass.async_block_till_done()
    assert hass.states.get(identifier).state == "unknown"


async def test_room_history_and_live_timeline_keep_stable_entities(hass, entry, loaded):
    robot = loaded.data["fixture-0"]
    rooms = [{"room": "Office", "pass_count": 2}]
    zones = [{"kind": "furniture", "name": "Sofa", "pass_count": 0}]
    destinations = [{"kind": "room", "name": "Office", "status": "finished"}]
    stage_started = datetime.now(UTC).isoformat()
    active = replace(
        robot,
        telemetry=robot.telemetry
        | {
            "last_mission_rooms": rooms,
            "last_mission_zones": zones,
            "live_timeline_updated": datetime.now(UTC),
            "live_timeline_stage": "start",
            "live_timeline_stage_started": stage_started,
            "live_timeline_rooms": rooms,
            "live_timeline_active_rooms": rooms,
            "live_timeline_zones": zones,
            "live_timeline_active_zones": zones,
            "live_destinations_completed": 1,
            "live_estimated_remaining": 85,
            "live_timeline_plan": {
                "completed": 1,
                "total": 1,
                "ordered": True,
                "destinations": destinations,
                "estimated_duration_seconds": 502,
            },
        },
    )
    loaded.async_set_updated_data(loaded.data | {robot.robot_id: active})
    await hass.async_block_till_done()
    history_id = entity_id(hass, entry, "last_mission_rooms")
    timeline_id = entity_id(hass, entry, "live_timeline_updated")
    zones_id = entity_id(hass, entry, "last_mission_zones")
    completion_id = entity_id(hass, entry, "live_destinations_completed")
    estimate_id = entity_id(hass, entry, "live_estimated_remaining")
    assert hass.states.get(history_id).state == "1"
    assert hass.states.get(history_id).attributes["rooms"] == rooms
    assert hass.states.get(timeline_id).attributes["stage"] == "start"
    assert hass.states.get(timeline_id).attributes["stage_started_at"] == stage_started
    assert hass.states.get(timeline_id).attributes["rooms"] == rooms
    assert hass.states.get(timeline_id).attributes["active_rooms"] == rooms
    assert hass.states.get(timeline_id).attributes["zones"] == zones
    assert hass.states.get(timeline_id).attributes["active_zones"] == zones
    assert hass.states.get(zones_id).state == "1"
    assert hass.states.get(zones_id).attributes["zones"] == zones
    assert hass.states.get(completion_id).state == "1"
    assert hass.states.get(completion_id).attributes["total"] == 1
    assert hass.states.get(completion_id).attributes["ordered"] is True
    assert hass.states.get(completion_id).attributes["destinations"] == destinations
    assert hass.states.get(estimate_id).state == "85"
    assert hass.states.get(estimate_id).attributes["estimated_duration_seconds"] == 502

    loaded.async_set_updated_data(loaded.data | {robot.robot_id: robot})
    await hass.async_block_till_done()
    assert hass.states.get(history_id).state == "unknown"
    assert hass.states.get(timeline_id).state == "unknown"
    assert hass.states.get(zones_id).state == "unknown"
    assert hass.states.get(completion_id).state == "unknown"
    assert "destinations" not in hass.states.get(completion_id).attributes
    assert hass.states.get(estimate_id).state == "unknown"
    assert hass.states.get(estimate_id).attributes["estimated_duration_seconds"] is None


async def test_phase_problems_and_documented_mission_error_are_visible_in_ha(hass, entry, loaded):
    state = loaded.data["fixture-0"]
    stuck = entity_id(hass, entry, "stuck", "binary_sensor")
    charging = entity_id(hass, entry, "charging_problem", "binary_sensor")
    assert hass.states.get(stuck).state == "off"
    loaded.async_set_updated_data({**loaded.data, "fixture-0": replace(state, phase="stuck")})
    await hass.async_block_till_done()
    assert hass.states.get(stuck).state == "on"
    assert hass.states.get("vacuum.robot_0").state == "error"
    assert hass.states.get(entity_id(hass, entry, "ready", "binary_sensor")).state == "off"
    loaded.async_set_updated_data(
        {**loaded.data, "fixture-0": replace(state, phase="chgerr", error=106)}
    )
    await hass.async_block_till_done()
    assert hass.states.get(charging).state == "on"
    assert hass.states.get(stuck).state == "off"
    error = hass.states.get("sensor.robot_0_mission_error")
    assert error.state == "106" and error.attributes["meaning"] == "battery_too_hot"
    unknown = RoombaMetricBinary(loaded, "fixture-0", "charging_problem")
    loaded.data["fixture-0"] = replace(state, phase="unknown")
    assert unknown.is_on is None


@pytest.mark.parametrize("code,expected", [(0, 0), (650, 650), (9999, None)])
async def test_component_error_sensor_distinguishes_normal_error_and_unknown(
    loaded, code, expected
):
    raw = 601 if code == 0 else code
    loaded.data["fixture-0"].telemetry["pad_wash_state"] = raw
    error = RoombaMetricSensor(loaded, "fixture-0", "pad_wash_error")
    assert error.native_value == expected
    assert (
        error.extra_state_attributes["meaning"]
        == {
            0: "ok",
            650: "clear_fluid_dock_tank_missing",
            9999: "unknown_code",
        }[code]
    )


async def test_sensor_attributes_identify_firmware_and_dock_codes_by_source(loaded):
    state = loaded.data["fixture-0"]
    dock_error = RoombaMetricSensor(loaded, "fixture-0", "dock_error")
    wash_status = RoombaMetricSensor(loaded, "fixture-0", "pad_wash_state")
    firmware = RoombaMetricSensor(loaded, "fixture-0", "software_deployment_state")
    assert dock_error.extra_state_attributes == {"meaning": "ok"}
    for code, meaning in [
        (601, "okay"),
        (401, "unknown_code"),
        (654, "grey_water_dock_tank_level_too_full"),
    ]:
        state.telemetry["pad_wash_state"] = code
        assert wash_status.extra_state_attributes == {"meaning": meaning}
    for code, meaning in [(4, "installing"), (103, "wifi_timeout"), (170, "unknown_code")]:
        state.telemetry["software_deployment_state"] = code
        assert firmware.extra_state_attributes == {"meaning": meaning}


@pytest.mark.parametrize(
    "code,conditions,expected",
    [
        (0, (), True),
        (0, (4,), False),
        (4, (), False),
        (None, (), None),
        (0, None, None),
        (4, None, False),
    ],
)
async def test_readiness_is_not_inferred_from_connection_alone(loaded, code, conditions, expected):
    loaded.data["fixture-0"].telemetry.update(not_ready_code=code, not_ready_conditions=conditions)
    assert RoombaMetricBinary(loaded, "fixture-0", "ready").is_on is expected


async def test_elapsed_includes_pause_and_stops_after_mission(loaded):
    state = loaded.data["fixture-0"]
    loaded.data["fixture-0"] = replace(state, cycle="clean", phase="stop")
    sensor = RoombaMetricSensor(loaded, "fixture-0", "mission_elapsed")
    assert sensor.native_value >= 120
    loaded.data["fixture-0"] = replace(state, cycle="none")
    assert sensor.native_value is None


async def test_docked_during_mission_has_its_own_status_and_elapsed_time(hass, entry, loaded):
    state = loaded.data["fixture-0"]
    identifier = entity_id(hass, entry, "mission_at_dock", "binary_sensor")
    assert hass.states.get(identifier).state == "off"
    loaded.async_set_updated_data({**loaded.data, "fixture-0": replace(state, cycle="clean")})
    await hass.async_block_till_done()
    assert hass.states.get(identifier).state == "on"
    assert hass.states.get("vacuum.robot_0").state == "docked"
    assert float(hass.states.get(entity_id(hass, entry, "mission_elapsed")).state) >= 120
    loaded.async_set_updated_data({**loaded.data, "fixture-0": replace(state, cycle=None)})
    await hass.async_block_till_done()
    assert hass.states.get(identifier).state == "unknown"


async def test_mop_preparation_sensor_distinguishes_mission_from_standalone_wash(
    hass, entry, loaded
):
    state = loaded.data["fixture-0"]
    identifier = entity_id(hass, entry, "preparing_mop", "binary_sensor")
    for cycle, expected in [("clean", "on"), ("none", "off"), (None, "unknown")]:
        loaded.async_set_updated_data(
            {**loaded.data, "fixture-0": replace(state, phase="padWash", cycle=cycle)}
        )
        await hass.async_block_till_done()
        assert hass.states.get(identifier).state == expected


async def test_diagnostics_contain_counts_and_codes_but_no_raw_fields(hass, entry, loaded):
    loaded.data["fixture-0"].telemetry["fixture-private-key"] = "fixture-private-value"
    report = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(report)
    for private in ("fixture-private", "fixture-0", "Robot 0", "fixture-password"):
        assert private not in text
    assert report["robots"][0]["telemetry_fields"] > 0


@pytest.fixture
async def reader(hass, entry, cloud_session):
    coordinator = RoombaCoordinator(hass, entry)
    coordinator.client.ensure_session = AsyncMock(return_value=cloud_session)
    coordinator.client.request = AsyncMock(return_value={"parts": []})
    coordinator.client.http.request = AsyncMock(return_value=HttpResponse(200, {"parts": []}))
    coordinator.client.robot_serial_number = AsyncMock(return_value="EXAMPLE-SERIAL")

    def read(session, shadows=None):
        if shadows == DETAIL_SHADOWS:
            return {
                f"fixture-{i}": {"rw-settings": {"state": {"reported": {"childLock": False}}}}
                for i in range(3)
            }
        return {
            f"fixture-{i}": {
                "ro-currentstate": {
                    "state": {
                        "reported": {
                            "batPct": 100,
                            "cleanMissionStatus": {"phase": "charge", "cycle": "none", "error": 0},
                        }
                    }
                },
                "rw-constatus": {"state": {"reported": {"connected": True}}},
            }
            for i in range(3)
        }

    coordinator._read = read
    coordinator._clock = lambda: 100
    yield coordinator
    await coordinator.async_close()


async def test_optional_sources_use_their_own_cadence_and_exclude_unsupported_robots(reader):
    first = await reader._async_update_data()
    assert len(first) == 3
    assert first["fixture-0"].telemetry["child_lock"] is False
    assert reader.client.request.await_count == 3
    paths = [call.args[1] for call in reader.client.request.await_args_list]
    assert all("fixture-3" not in path for path in paths)
    await reader._async_update_data()
    assert reader.client.request.await_count == 3
    assert reader.client.http.request.await_count == 1
    reader._clock = lambda: 2000
    await reader._async_update_data()
    assert reader.client.request.await_count == 6


async def test_robot_serials_update_device_registry_and_survive_optional_failures(
    hass, entry, reader
):
    serials = reader.client.robot_serial_number
    serials.side_effect = ["EXAMPLE-123", ProtocolError("Unavailable"), "EXAMPLE-321"]
    with patch("custom_components.roomba_home.coordinator.RoombaCoordinator", return_value=reader):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = dr.async_get(hass)

    def device(identifier):
        return registry.async_get_device_by_identifier(
            (DOMAIN, f"{entry.unique_id}_{identifier}"), entry.entry_id
        )

    robot = device("fixture-0")
    assert robot.serial_number == "EXAMPLE-123"
    assert device("fixture-1").serial_number is None
    assert reader._serials_due == 100 + PARTS_SECONDS
    assert {call.args for call in serials.await_args_list} == {
        ("fixture-0",),
        ("fixture-1",),
        ("fixture-2",),
    }
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert "EXAMPLE-123" not in json.dumps(report)
    assert "EXAMPLE-123" not in str(hass.states.get("vacuum.robot_0").attributes)
    await reader.async_refresh()
    assert serials.await_count == 3

    serials.side_effect = RateLimited(120)
    reader._clock = lambda: 100 + PARTS_SECONDS
    await reader.async_refresh()
    assert serials.await_count == 4
    assert reader._serials_due == 220 + PARTS_SECONDS
    assert device("fixture-0").serial_number == "EXAMPLE-123"
    assert device("fixture-1").serial_number is None

    serials.side_effect = ["EXAMPLE-456", "EXAMPLE-789", "EXAMPLE-321"]
    reader._clock = lambda: 220 + PARTS_SECONDS
    await reader.async_refresh()
    assert reader.last_update_success
    assert device("fixture-0").id == robot.id
    assert device("fixture-0").serial_number == "EXAMPLE-456"
    assert device("fixture-1").serial_number == "EXAMPLE-789"
    assert reader._serials_due == 220 + PARTS_SECONDS + SERIAL_REFRESH_SECONDS
    reader._serials.clear()
    registry.async_get_or_create_from_info(
        config_entry_id=entry.entry_id,
        device_info=RoombaVacuum(reader, "fixture-0").device_info,
    )
    assert device("fixture-0").serial_number == "EXAMPLE-456"


async def test_partial_mqtt_poll_preserves_availability_and_last_read_of_each_robot(
    hass, entry, reader
):
    original_read = reader._read
    responding = {"fixture-0", "fixture-1"}

    def read(session, shadows=None):
        documents = original_read(session, shadows)
        if shadows == DETAIL_SHADOWS:
            return documents
        return {robot: report for robot, report in documents.items() if robot in responding}

    reader._read = read
    at = datetime(2026, 11, 23, 10, 0, tzinfo=UTC)
    with patch("custom_components.roomba_home.coordinator.datetime") as time_source:
        time_source.now.return_value = at
        with patch(
            "custom_components.roomba_home.coordinator.RoombaCoordinator", return_value=reader
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        assert hass.states.get("vacuum.robot_0").state == "docked"
        assert hass.states.get("vacuum.robot_1").state == "docked"
        assert reader.data["fixture-2"].observed_at is None

        responding.remove("fixture-0")
        time_source.now.return_value = at + timedelta(minutes=1)
        await reader.async_refresh()
        await hass.async_block_till_done()
        assert reader.last_update_success
        assert reader.data["fixture-0"].observed_at == at
        assert reader.data["fixture-1"].observed_at == at + timedelta(minutes=1)
        assert hass.states.get("vacuum.robot_0").state == "unavailable"
        assert hass.states.get("binary_sensor.robot_0_connection").state == "unknown"
        assert hass.states.get("vacuum.robot_1").state == "docked"
        with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
            with pytest.raises(HomeAssistantError, match="unavailable"):
                await reader.async_command("fixture-0", Command.VACUUM)
            sender.assert_not_called()

        responding.add("fixture-0")
        time_source.now.return_value = at + timedelta(minutes=2)
        await reader.async_refresh()
        await hass.async_block_till_done()
        assert reader.data["fixture-0"].observed_at == at + timedelta(minutes=2)
        assert hass.states.get("vacuum.robot_0").state == "docked"


async def test_expiring_session_with_forbidden_exchange_recovers_without_reauth(
    hass, entry, reader, cloud_session
):
    robot = "fixture-0"
    cloud_session.raw["robots"][robot]["digiCap"] = {"timeline": 1}
    reader.client.mission_history = AsyncMock(
        return_value={
            "last_mission_target": "temporary_zones",
            "last_mission_target_count": 1,
            "last_mission_error": 48,
        }
    )
    reader.client.ensure_session = RoombaClient.ensure_session.__get__(reader.client)
    reader.client._session = cloud_session
    now = cloud_session.expires_at - timedelta(minutes=6)
    elapsed = 100
    reader.client.clock = lambda: now
    reader._clock = lambda: elapsed

    deployment = cloud_session.discovery["current_deployment"]
    discovery = {
        **cloud_session.discovery,
        "deployments": {
            deployment: {
                **cloud_session.deployment,
                "httpBase": "https://fixture.irobotapi.com",
                "httpBaseAuth": "https://signed.fixture.irobotapi.com",
            }
        },
        "gigya": {"api_key": "fixture-key", "datacenter_domain": "us1.gigya.com"},
    }
    identity = {
        "errorCode": 0,
        "UID": "fixture-id",
        "UIDSignature": "fixture-signature",
        "signatureTimestamp": "fixture-timestamp",
    }
    renewed = {
        **cloud_session.raw,
        "credentials": {
            **cloud_session.raw["credentials"],
            "Expiration": (cloud_session.expires_at + timedelta(hours=1)).isoformat(),
        },
    }
    reader.client.http.request.side_effect = [
        HttpResponse(200, {"parts": []}),
        HttpResponse(200, discovery),
        HttpResponse(200, identity),
        HttpResponse(403, {"message": "fixture-private-provider-response"}),
        HttpResponse(200, discovery),
        HttpResponse(200, identity),
        HttpResponse(200, renewed),
    ]
    with patch("custom_components.roomba_home.coordinator.RoombaCoordinator", return_value=reader):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    vacuum = entity_id(hass, entry, "vacuum", "vacuum")
    target = entity_id(hass, entry, "last_mission_target")
    failure = entity_id(hass, entry, "last_mission_error")
    assert hass.states.get(vacuum).state == "docked"
    assert hass.states.get(target).state == "temporary_zones"
    assert hass.states.get(failure).state == "48"
    registry = er.async_get(hass)
    before = {key: registry.async_get(key).id for key in (vacuum, target, failure)}

    now += timedelta(minutes=2)
    await reader.async_refresh()
    await hass.async_block_till_done()
    assert not reader.last_update_success
    assert reader.last_exception.retry_after == POLL_SECONDS
    assert all(hass.states.get(key).state == "unavailable" for key in before)
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)

    elapsed += 1
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        with pytest.raises(HomeAssistantError, match="unavailable"):
            await reader.async_command(robot, Command.VACUUM)
        sender.assert_not_called()
    assert reader.client.http.request.await_count == 4

    elapsed += POLL_SECONDS - 1
    await reader.async_refresh()
    await hass.async_block_till_done()
    assert reader.last_update_success and reader._read_retry_until == 0
    assert hass.states.get(vacuum).state == "docked"
    assert hass.states.get(target).state == "temporary_zones"
    assert hass.states.get(target).attributes["region_count"] == 1
    assert hass.states.get(failure).state == "48"
    assert {key: registry.async_get(key).id for key in before} == before
    assert reader.client.http.request.await_count == 7
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    exchanges = [
        json.loads(call.kwargs["body"])
        for call in reader.client.http.request.await_args_list
        if call.args[1].endswith("/v2/login")
    ]
    assert [payload["app_id"] for payload in exchanges] == [reader.client.profile.app_id] * 2


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"phase": "run"}, "confirmed"),
        ({"phase": "charge", "cycle": "none"}, "unconfirmed"),
        ({"phase": "run", "nMssn": 2}, "unconfirmed"),
    ],
)
async def test_mop_preparation_is_reconciled_in_the_shared_poll_without_another_send(
    reader, cloud_session, change, expected
):
    cloud_session.raw["robots"]["fixture-0"]["cap"] = {"oMode": 4}
    mission = {
        "phase": "charge",
        "cycle": "none",
        "operatingMode": 4,
        "nMssn": 1,
        "mssnStrtTm": 100,
        "error": 0,
    }
    poll = reader._read

    def read(session, shadows=None):
        documents = poll(session, shadows)
        if shadows != DETAIL_SHADOWS:
            documents["fixture-0"]["ro-currentstate"]["state"]["reported"]["cleanMissionStatus"] = (
                dict(mission)
            )
        return documents

    async def enter_preparation(delay):
        mission.update(phase="padWash", cycle="clean")

    reader._read = read
    reader._sleep = enter_preparation
    await reader.async_refresh()
    await reader.async_set_profile("fixture-0", mode=CleaningMode.MOP)
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        await reader.async_command("fixture-0", Command.VACUUM)
        assert reader.command_status["fixture-0"] == "submitted"
        reader._reconcile_preparations({})
        assert reader.command_status["fixture-0"] == "submitted"
        watched = reader._preparations["fixture-0"]
        await reader.async_command("fixture-0", Command.VACUUM)
        assert reader._preparations["fixture-0"] is watched
        mission.update(change)
        await reader.async_refresh()
        assert reader.command_status["fixture-0"] == expected
        assert not reader._preparations
        sender.return_value.send.assert_called_once()


@pytest.mark.parametrize(
    "phase,cycle,expected",
    [
        ("run", "clean", 15),
        ("stop", "clean", 15),
        ("hmUsrDock", "dock", 15),
        ("charge", "clean", 15),
        ("charge", "none", 60),
    ],
)
async def test_polling_accelerates_during_active_mission(reader, phase, cycle, expected):
    original = reader._read

    def read(session, shadows=None):
        documents = original(session, shadows)
        if shadows != DETAIL_SHADOWS:
            documents["fixture-0"]["ro-currentstate"]["state"]["reported"][
                "cleanMissionStatus"
            ].update(phase=phase, cycle=cycle)
        return documents

    reader._read = read
    await reader._async_update_data()
    assert reader.update_interval.total_seconds() == expected


async def test_a_known_dock_remains_supported_when_robot_leaves_it(reader):
    reader.async_set_updated_data(await reader._async_update_data())
    original = reader._read

    def read(session, shadows=None):
        documents = original(session, shadows)
        documents["fixture-0"]["ro-currentstate"]["state"]["reported"]["cleanMissionStatus"].update(
            phase="run", cycle="clean"
        )
        return documents

    reader._read = read
    result = await reader._async_update_data()
    assert result["fixture-0"].capabilities.docking is True


@pytest.mark.parametrize(
    "field,code", [("state", 302), ("frState", 403), ("pwState", 602), ("pdState", 702)]
)
async def test_polling_also_tracks_active_dock_processes(reader, field, code):
    original = reader._read

    def read(session, shadows=None):
        documents = original(session, shadows)
        if shadows != DETAIL_SHADOWS:
            documents["fixture-0"]["ro-currentstate"]["state"]["reported"]["dock"] = {field: code}
        return documents

    reader._read = read
    await reader._async_update_data()
    assert reader.update_interval.total_seconds() == 15


@pytest.mark.parametrize("failure", [ProtocolError("fixture"), OSError(), RateLimited(900)])
async def test_optional_failure_does_not_hide_good_fast_state(reader, failure):
    original = reader._read

    def read(session, shadows=None):
        if shadows == DETAIL_SHADOWS:
            raise failure
        return original(session, shadows)

    reader._read = read
    reader.client.request.side_effect = failure
    reader.client.http.request.side_effect = failure
    result = await reader._async_update_data()
    assert result["fixture-0"].activity == "docked"
    assert result["fixture-0"].connected is True
    assert result["fixture-0"].telemetry["details_available"] is False
    assert result["fixture-0"].telemetry["parts_available"] is False
    if isinstance(failure, RateLimited):
        assert reader._details_due >= 100 + failure.retry_after


@pytest.mark.parametrize("invalid", [ProtocolError("fixture"), [1], {"parts": "invalid"}])
async def test_bad_optional_catalog_and_one_failed_part_do_not_drop_other_robots(reader, invalid):
    reader.client.http.request.return_value = HttpResponse(200, [])
    reader.client.request.side_effect = [invalid, {"parts": []}, {"parts": []}]
    result = await reader._async_update_data()
    assert not result["fixture-0"].telemetry["parts_available"]
    assert result["fixture-0"].capabilities.maintenance is None
    assert result["fixture-1"].telemetry["parts_available"]
    assert reader.source_status["parts"] == 2


@pytest.mark.parametrize("source", ["details", "parts"])
async def test_optional_authentication_error_still_requests_reauth(reader, source):
    if source == "parts":
        reader.client.request.side_effect = AuthenticationError()
    else:
        reader._read = lambda *args: (
            (_ for _ in ()).throw(AuthenticationError()) if len(args) > 1 else {}
        )
    from homeassistant.exceptions import ConfigEntryAuthFailed

    with pytest.raises(ConfigEntryAuthFailed):
        await reader._async_update_data()


async def test_schedule_count_is_discovered_as_a_separate_sensor(loaded):
    from custom_components.roomba_home.sensor import sensor_candidates

    state = replace(loaded.data["fixture-0"], telemetry={"schedule_count": 2})
    assert ("schedule_count", RoombaMetricSensor) in list(sensor_candidates(state))
    loaded.data["fixture-0"] = state
    assert RoombaMetricSensor(loaded, "fixture-0", "schedule_count").native_value == 2


async def test_cloud_schedules_do_not_replace_device_schedule_count(reader):
    session = await reader.client.ensure_session()
    session.raw["robots"]["fixture-0"]["cap"] = {"sched": 2}
    session.raw["robots"]["fixture-1"]["cap"] = {"sched": 0}
    reader.client.cloud_schedules = AsyncMock(
        return_value={
            "fixture-0": {
                "cloud_schedule_count": 1,
                "cloud_enabled_schedule_count": 0,
                "cloud_schedule_times": ({"weekdays": (1, 3), "time": "08:15", "enabled": False},),
            }
        }
    )
    first = await reader._async_update_data()
    reader.async_set_updated_data(first)
    assert first["fixture-1"].capabilities.schedules is False
    assert first["fixture-0"].telemetry["cloud_enabled_schedule_count"] == 0
    assert "schedule_count" not in first["fixture-0"].telemetry
    sensor = RoombaMetricSensor(reader, "fixture-0", "cloud_schedule_count")
    assert sensor.native_value == 1
    assert sensor.extra_state_attributes["weekly_times"][0]["time"] == "08:15"
    await reader._async_update_data()
    reader.client.cloud_schedules.assert_awaited_once_with(frozenset({"fixture-0"}))


@pytest.mark.parametrize(
    "timezone,schedule_present,expected",
    [
        ("Europe/Paris", True, datetime(2026, 11, 23, 7, 15, tzinfo=UTC)),
        ("Fixture/UnknownZone", True, None),
        ("Europe/Paris", False, None),
        (None, True, None),
    ],
)
async def test_next_cloud_schedule_uses_a_valid_robot_zone_and_known_schedules(
    reader, timezone, schedule_present, expected
):
    session = await reader.client.ensure_session()
    session.raw["robots"]["fixture-0"]["cap"] = {"sched": 2}
    reader.client.cloud_schedules = AsyncMock(
        return_value={
            "fixture-0": {
                "cloud_enabled_schedule_count": 1,
                "cloud_schedule_times": ({"weekdays": (1, 3), "time": "08:15", "enabled": True},),
            }
        }
        if schedule_present
        else {}
    )
    read = reader._read

    def documents(session, shadows=None):
        output = read(session, shadows)
        if shadows == DETAIL_SHADOWS:
            output["fixture-0"]["rw-settings"]["state"]["reported"]["timezone"] = timezone
        return output

    reader._read = documents
    with patch(
        "custom_components.roomba_home.coordinator.dt_util.utcnow",
        return_value=datetime(2026, 11, 23, 7, tzinfo=UTC),
    ):
        result = await reader._async_update_data()
    reader.async_set_updated_data(result)
    values = result["fixture-0"].telemetry
    assert values["robot_timezone"] == (timezone if timezone == "Europe/Paris" else None)
    assert ("next_cloud_schedule" in values) is (bool(timezone) and schedule_present)
    sensor = RoombaMetricSensor(reader, "fixture-0", "next_cloud_schedule")
    assert sensor.native_value == expected
    assert sensor.device_class == "timestamp" and sensor.native_unit_of_measurement is None


@pytest.mark.parametrize("error", [AuthenticationError(), RateLimited(900), OSError()])
async def test_cloud_schedule_failure_isolated_to_its_source(reader, error):
    session = await reader.client.ensure_session()
    session.raw["robots"]["fixture-0"]["cap"] = {"sched": 1}
    reader.client.cloud_schedules = AsyncMock(side_effect=error)
    if isinstance(error, AuthenticationError):
        from homeassistant.exceptions import ConfigEntryAuthFailed

        with pytest.raises(ConfigEntryAuthFailed):
            await reader._async_update_data()
    else:
        result = await reader._async_update_data()
        assert result["fixture-0"].connected is True
        assert result["fixture-0"].telemetry["schedules_available"] is False
        assert "cloud_schedule_count" not in result["fixture-0"].telemetry
        assert reader._schedules_due == (1000 if isinstance(error, RateLimited) else 400)


async def test_optional_availability_distinguishes_empty_results_failures_and_support(
    reader, cloud_session
):
    robots = cloud_session.raw["robots"]
    for index in range(3):
        robots[f"fixture-{index}"].update(
            cap={"sched": 1 if index < 2 else 0},
            digiCap={"timeline": 1 if index < 2 else 0},
        )
    schedules = {"cloud_schedule_count": 0, "cloud_schedule_times": ()}
    reader.client.cloud_schedules = AsyncMock(
        side_effect=[{"fixture-1": schedules}, {"fixture-0": schedules, "fixture-1": schedules}]
    )
    reader.client.mission_history = AsyncMock(
        side_effect=[{"history_count": 0}, OSError(), {"history_count": 0}, {"history_count": 0}]
    )
    first = await reader._async_update_data()
    assert first["fixture-0"].telemetry["history_available"] is True
    assert first["fixture-0"].telemetry["history_count"] == 0
    assert first["fixture-0"].telemetry["schedules_available"] is False
    assert first["fixture-1"].telemetry["history_available"] is False
    assert "history_count" not in first["fixture-1"].telemetry
    assert first["fixture-1"].telemetry["schedules_available"] is True
    assert first["fixture-1"].telemetry["cloud_schedule_count"] == 0
    assert "history_available" not in first["fixture-2"].telemetry
    assert "schedules_available" not in first["fixture-2"].telemetry
    assert reader.source_status["history"] == reader.source_status["schedules"] == 1

    reader._clock = lambda: 1900
    recovered = await reader._async_update_data()
    for key in ("fixture-0", "fixture-1"):
        assert recovered[key].activity == "docked"
        assert recovered[key].telemetry["history_available"] is True
        assert recovered[key].telemetry["schedules_available"] is True
    assert reader.source_status["history"] == reader.source_status["schedules"] == 2

    robots["fixture-0"].update(cap={}, digiCap={})
    unknown = await reader._async_update_data()
    assert "history_count" not in unknown["fixture-0"].telemetry
    assert "cloud_schedule_count" not in unknown["fixture-0"].telemetry
    assert reader.source_status["history"] == reader.source_status["schedules"] == 1


async def test_reported_mode_is_a_translated_enum_separate_from_next_mission(loaded):
    from custom_components.roomba_home.sensor import RoombaCleaningModeSensor, sensor_candidates

    state = replace(loaded.data["fixture-0"], telemetry={"operating_mode": 4}, mode=4)
    assert ("reported_cleaning_mode", RoombaCleaningModeSensor) in list(sensor_candidates(state))
    loaded.data["fixture-0"] = state
    entity = RoombaCleaningModeSensor(loaded, "fixture-0", "reported_cleaning_mode")
    assert entity.native_value == "mop"
    assert loaded.profile("fixture-0").mode == "vacuum"
    loaded.data["fixture-0"] = replace(state, mode=100)
    assert entity.native_value is None
    loaded.data.pop("fixture-0")
    assert entity.native_value is None


async def test_diagnostic_metric_and_unknown_readiness_attributes(loaded):
    from homeassistant.const import EntityCategory

    sensor = RoombaMetricSensor(loaded, "fixture-0", "charging_errors")
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.state_class.value == "total_increasing"
    condition = RoombaMetricSensor(loaded, "fixture-0", "not_ready_condition_count")
    assert condition.extra_state_attributes == {"condition_codes": []}
    loaded.data["fixture-0"] = replace(loaded.data["fixture-0"], telemetry={})
    assert condition.extra_state_attributes == {"condition_codes": None}


async def test_missing_robot_clears_optional_sensor_and_binary_readings(loaded):
    from custom_components.roomba_home.sensor import RoombaCloudRead

    cloud = RoombaCloudRead(loaded, "fixture-0")
    binary = RoombaMetricBinary(loaded, "fixture-0", "bin_present")
    metric = RoombaMetricSensor(loaded, "fixture-0", "mission_area")
    assert cloud.available and cloud.native_value is not None
    loaded.data.pop("fixture-0")
    assert cloud.native_value is None and not cloud.available
    assert metric.native_value is None and binary.is_on is None


async def test_connection_time_is_visible_offline_and_stays_registered(hass, entry, loaded):
    robot = loaded.data["fixture-0"]
    updated = datetime(2026, 1, 2, 3, tzinfo=UTC)
    loaded.async_set_updated_data(
        {
            **loaded.data,
            robot.robot_id: replace(
                robot, connected=False, telemetry={"connection_updated_at": updated}
            ),
        }
    )
    await hass.async_block_till_done()
    identifier = entity_id(hass, entry, "connection_updated_at")
    state = hass.states.get(identifier)
    assert state.state == updated.isoformat()
    assert state.attributes["device_class"] == "timestamp"
    loaded.async_set_updated_data({**loaded.data, robot.robot_id: replace(robot, telemetry={})})
    assert hass.states.get(identifier).state == "unknown"


async def test_mission_event_baselines_restores_and_emits_with_available_details(
    hass, entry, loaded
):
    robot = loaded.data["fixture-0"]
    robot = replace(robot, capabilities=replace(robot.capabilities, history=True))
    finished = datetime(2026, 1, 2, 3, tzinfo=UTC)
    initial = {"history_available": True, "last_mission_finished": finished}

    def apply(values):
        loaded.async_set_updated_data(
            {**loaded.data, robot.robot_id: replace(robot, telemetry=values)}
        )

    apply(initial)
    await hass.async_block_till_done()
    identifier = entity_id(hass, entry, "mission_finished", "event")
    assert hass.states.get(identifier).attributes["event_type"] is None

    later = {
        "history_available": True,
        "last_mission_finished": finished + timedelta(minutes=8),
        "last_mission_outcome": "cancelled",
        "last_mission_area": 0,
        "last_mission_duration": 4,
        "last_mission_modes": ("vacuum",),
        "last_mission_error": 48,
    }
    apply({**later, "last_mission_outcome": None})
    apply({**later, "history_available": False})
    assert hass.states.get(identifier).attributes["event_type"] is None
    apply(later)
    event = hass.states.get(identifier)
    assert event.attributes["event_type"] == "mission_finished"
    assert event.attributes["outcome"] == "cancelled"
    assert event.attributes["duration_minutes"] == 4
    assert event.attributes["area_m2"] == 0
    assert event.attributes["cleaning_modes"] == ("vacuum",)
    assert event.attributes["error_code"] == 48
    for telemetry in (initial, {}, later, later):
        apply(telemetry)
        assert hass.states.get(identifier).state == event.state

    with patch.object(RoombaCoordinator, "_async_update_data", AsyncMock(return_value=loaded.data)):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get(identifier).state == event.state
    assert hass.states.get(identifier).attributes["error_code"] == 48
    loaded = entry.runtime_data
    apply(
        {
            "history_available": True,
            "last_mission_finished": finished + timedelta(minutes=15),
            "last_mission_outcome": "completed",
        }
    )
    assert hass.states.get(identifier).attributes["outcome"] == "completed"
    assert "error_code" not in hass.states.get(identifier).attributes
