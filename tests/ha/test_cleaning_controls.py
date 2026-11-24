"""Native HA control services, preferences and lifecycle, with a mocked cloud."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.roomba_home.button import RoombaResetProfile
from custom_components.roomba_home.const import DOMAIN
from custom_components.roomba_home.coordinator import RoombaCoordinator
from custom_components.roomba_home.core.capabilities import DeviceCapabilities, DockCapabilities
from custom_components.roomba_home.core.cleaning import (
    CleaningCapabilities,
    CleaningMode,
    CleaningProfile,
)
from custom_components.roomba_home.core.cleaning_protocol import CleaningSetting
from custom_components.roomba_home.number import RoombaCleaningLevel
from custom_components.roomba_home.select import RoombaCleaningMode
from custom_components.roomba_home.switch import RoombaCleaningOption


def entity_id(hass, entry, domain, suffix, robot="fixture-0"):
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.unique_id}_{robot}_{suffix}"
    )


@pytest.fixture
async def loaded(hass, entry, robot_states):
    robot_states["fixture-0"] = replace(
        robot_states["fixture-0"],
        telemetry={
            "suction_level": 3,
            "pad_wetness": 2,
            "scrub_setting": 0,
            "two_pass": False,
            "carpet_boost": True,
        },
    )
    with patch.object(
        RoombaCoordinator, "_async_update_data", AsyncMock(return_value=robot_states)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry.runtime_data


async def test_capability_driven_controls_belong_to_existing_device(hass, entry, loaded):
    robot = "fixture-0"
    expected = {
        ("select", "next_cleaning_mode"),
        ("number", "next_suction_level"),
        ("number", "default_suction_level"),
        ("number", "next_wetness_level"),
        ("number", "default_wetness_level"),
        ("switch", "next_smart_scrub"),
        ("switch", "default_smart_scrub"),
        ("switch", "next_two_pass"),
        ("switch", "default_two_pass"),
        ("switch", "next_carpet_boost"),
        ("switch", "default_carpet_boost"),
        ("button", "reset_cleaning_profile"),
    }
    registry = er.async_get(hass)
    vacuum = registry.async_get("vacuum.robot_0")
    for domain, suffix in expected:
        identifier = entity_id(hass, entry, domain, suffix, robot)
        assert identifier and registry.async_get(identifier).device_id == vacuum.device_id
    mode = hass.states.get(entity_id(hass, entry, "select", "next_cleaning_mode"))
    assert mode.state == "vacuum"
    assert mode.attributes["options"] == [mode.value for mode in CleaningMode]
    level = hass.states.get(entity_id(hass, entry, "number", "next_suction_level"))
    assert float(level.state) == 3 and level.attributes["max"] == 4
    assert hass.states.get(entity_id(hass, entry, "switch", "next_smart_scrub")).state == "off"
    assert hass.states.get(entity_id(hass, entry, "switch", "next_carpet_boost")).state == "on"


async def test_default_mop_controls_use_reported_values_and_native_ha_services(hass, entry, loaded):
    loaded.async_set_cleaning_setting = AsyncMock()
    await loaded.async_set_profile("fixture-0", wetness_level=3, smart_scrub=True)
    registry = er.async_get(hass)
    number = entity_id(hass, entry, "number", "default_wetness_level")
    switch = entity_id(hass, entry, "switch", "default_smart_scrub")
    assert float(hass.states.get(number).state) == 2
    assert hass.states.get(switch).state == "off"
    assert registry.async_get(number).entity_category == EntityCategory.CONFIG
    assert registry.async_get(switch).entity_category == EntityCategory.CONFIG
    assert not entity_id(hass, entry, "number", "default_wetness_level", "fixture-1")
    assert not entity_id(hass, entry, "switch", "default_smart_scrub", "fixture-1")

    await hass.services.async_call(
        "number", "set_value", {"entity_id": number, "value": 1}, blocking=True
    )
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    assert [call.args for call in loaded.async_set_cleaning_setting.await_args_list] == [
        ("fixture-0", CleaningSetting.WETNESS, 1),
        ("fixture-0", CleaningSetting.SMART_SCRUB, True),
        ("fixture-0", CleaningSetting.SMART_SCRUB, False),
    ]
    assert loaded.profile("fixture-0").wetness_level == 3
    assert loaded.profile("fixture-0").smart_scrub is True

    state = loaded.data["fixture-0"]
    loaded.async_set_updated_data({**loaded.data, "fixture-0": replace(state, telemetry={})})
    await hass.async_block_till_done()
    assert hass.states.get(number).state == "unavailable"
    assert hass.states.get(switch).state == "unavailable"
    loaded.async_set_updated_data({**loaded.data, "fixture-0": state})
    await hass.async_block_till_done()
    assert float(hass.states.get(number).state) == 2
    assert hass.states.get(switch).state == "off"


async def test_default_suction_is_a_native_control_separate_from_the_next_mission(
    hass, entry, loaded
):
    loaded.async_set_cleaning_setting = AsyncMock()
    loaded.async_command = AsyncMock()
    await loaded.async_set_profile("fixture-0", suction_level=4)
    uid = entity_id(hass, entry, "number", "default_suction_level")
    assert er.async_get(hass).async_get(uid).entity_category == EntityCategory.CONFIG
    assert not entity_id(hass, entry, "number", "default_suction_level", "fixture-1")
    assert float(hass.states.get(uid).state) == 3
    await hass.services.async_call(
        "number", "set_value", {"entity_id": uid, "value": 2}, blocking=True
    )
    loaded.async_set_cleaning_setting.assert_awaited_once_with(
        "fixture-0", CleaningSetting.SUCTION, 2
    )
    loaded.async_command.assert_not_awaited()
    assert loaded.profile("fixture-0").suction_level == 4

    state = loaded.data["fixture-0"]
    loaded.async_set_updated_data(
        {**loaded.data, "fixture-0": replace(state, telemetry={"suction_level": 99})}
    )
    await hass.async_block_till_done()
    assert hass.states.get(uid).state == "unavailable"
    loaded.async_set_updated_data({**loaded.data, "fixture-0": state})
    await hass.async_block_till_done()
    assert float(hass.states.get(uid).state) == 3
    assert entity_id(hass, entry, "number", "default_suction_level") == uid


@pytest.mark.parametrize("mode", [CleaningMode.VACUUM, CleaningMode.MOP])
async def test_default_suction_requires_vacuum_capability_and_observed_value(
    hass, entry, robot_states, mode
):
    state = robot_states["fixture-0"]
    capabilities = replace(state.capabilities.cleaning, modes=frozenset({mode}), suction_levels=3)
    robot_states["fixture-0"] = replace(
        state,
        telemetry={"suction_level": 2},
        capabilities=replace(state.capabilities, cleaning=capabilities),
    )
    with patch.object(
        RoombaCoordinator, "_async_update_data", AsyncMock(return_value=robot_states)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert bool(entity_id(hass, entry, "number", "default_suction_level")) == (
        mode is CleaningMode.VACUUM
    )


@pytest.mark.parametrize(
    ("field", "setting", "reported"),
    [
        ("two_pass", CleaningSetting.TWO_PASS, False),
        ("carpet_boost", CleaningSetting.CARPET_BOOST, True),
    ],
)
async def test_default_switch_preserves_the_next_mission_preference(
    hass, entry, loaded, field, setting, reported
):
    loaded.async_set_cleaning_setting = AsyncMock()
    await loaded.async_set_profile("fixture-0", **{field: not reported})
    default_switch = entity_id(hass, entry, "switch", f"default_{field}")
    assert hass.states.get(default_switch).state == ("on" if reported else "off")
    assert er.async_get(hass).async_get(default_switch).entity_category == EntityCategory.CONFIG
    await hass.services.async_call(
        "switch",
        "turn_off" if reported else "turn_on",
        {"entity_id": default_switch},
        blocking=True,
    )
    loaded.async_set_cleaning_setting.assert_awaited_once_with("fixture-0", setting, not reported)
    assert getattr(loaded.profile("fixture-0"), field) is not reported


async def test_auto_evacuation_area_belongs_to_its_dock_and_preserves_existing_sensor(
    hass, entry, robot_states
):
    robot = "fixture-0"
    state = robot_states[robot]
    telemetry = {**state.telemetry, "auto_evacuation_frequency": 25}
    device = replace(
        state.capabilities,
        cleaning=replace(state.capabilities.cleaning, auto_evacuation_area=True),
        dock=DockCapabilities(recognized=True, evacuation=True),
    )
    robot_states[robot] = replace(state, telemetry=telemetry, capabilities=device)
    with patch.object(
        RoombaCoordinator, "_async_update_data", AsyncMock(return_value=robot_states)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data
    coordinator.async_set_cleaning_setting = AsyncMock()
    registry = er.async_get(hass)
    from homeassistant.helpers import device_registry as dr

    area = entity_id(hass, entry, "number", "auto_evacuation_area")
    code = entity_id(hass, entry, "sensor", "auto_evacuation_frequency")
    dock_id = registry.async_get(area).device_id
    robot_id = registry.async_get("vacuum.robot_0").device_id
    assert registry.async_get(code).device_id == robot_id
    assert dr.async_get(hass).async_get(dock_id).parent_device_id == robot_id
    assert registry.async_get(area).entity_category == EntityCategory.CONFIG
    number = hass.states.get(area)
    assert float(number.state) == 25 and number.attributes["unit_of_measurement"] == "m²"
    assert number.attributes["min"] == 10 and number.attributes["max"] == 1000
    assert entity_id(hass, entry, "number", "auto_evacuation_area", "fixture-1") is None
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": area, "value": 50},
        blocking=True,
    )
    coordinator.async_set_cleaning_setting.assert_awaited_once_with(
        robot, CleaningSetting.AUTO_EVACUATION_AREA, 50
    )
    registry.async_update_entity_options(area, "number", {"unit_of_measurement": "ft²"})
    await hass.async_block_till_done()
    assert hass.states.get(area).attributes["unit_of_measurement"] == "ft²"
    await hass.services.async_call(
        "number", "set_value", {"entity_id": area, "value": 538}, blocking=True
    )
    assert coordinator.async_set_cleaning_setting.await_count == 2
    assert coordinator.async_set_cleaning_setting.await_args.args == (
        robot,
        CleaningSetting.AUTO_EVACUATION_AREA,
        50,
    )
    registry.async_update_entity_options(area, "number", {"unit_of_measurement": "m²"})
    await hass.async_block_till_done()
    for unavailable in (
        replace(robot_states[robot], capabilities=replace(device, dock=DockCapabilities())),
        replace(robot_states[robot], telemetry={**telemetry, "auto_evacuation_frequency": 4}),
    ):
        coordinator.async_set_updated_data({**robot_states, robot: unavailable})
        await hass.async_block_till_done()
        assert hass.states.get(area).state == "unavailable"
    coordinator.async_set_updated_data(robot_states)
    await hass.async_block_till_done()
    assert entity_id(hass, entry, "number", "auto_evacuation_area") == area
    assert float(hass.states.get(area).state) == 25


@pytest.mark.parametrize(
    "mode,enabled,disabled",
    [
        (CleaningMode.VACUUM, "carpet_boost", "smart_scrub"),
        (CleaningMode.MOP, "smart_scrub", "carpet_boost"),
    ],
)
async def test_preference_controls_match_each_robots_reported_modes(
    hass, entry, robot_states, mode, enabled, disabled
):
    state = robot_states["fixture-0"]
    capabilities = replace(state.capabilities.cleaning, modes=frozenset({mode}))
    robot_states["fixture-0"] = replace(
        state, capabilities=replace(state.capabilities, cleaning=capabilities)
    )
    with patch.object(
        RoombaCoordinator, "_async_update_data", AsyncMock(return_value=robot_states)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entity_id(hass, entry, "switch", f"next_{enabled}")
    assert entity_id(hass, entry, "switch", f"next_{disabled}") is None


async def test_real_ha_services_persist_next_mission_preferences_without_a_robot_command(
    hass, entry, loaded
):
    loaded.async_command = AsyncMock()
    operations = [
        ("select", "select_option", "next_cleaning_mode", {"option": "mop"}),
        ("number", "set_value", "next_wetness_level", {"value": 3}),
        ("number", "set_value", "next_suction_level", {"value": 4}),
        ("switch", "turn_on", "next_smart_scrub", {}),
        ("switch", "turn_on", "next_two_pass", {}),
        ("switch", "turn_off", "next_carpet_boost", {}),
    ]
    for domain, service, suffix, data in operations:
        await hass.services.async_call(
            domain,
            service,
            {"entity_id": entity_id(hass, entry, domain, suffix), **data},
            blocking=True,
        )
    assert loaded.profile("fixture-0") == CleaningProfile(CleaningMode.MOP, 4, 3, True, True, False)
    assert loaded.profile("fixture-1") == CleaningProfile()
    assert entry.options["cleaning_profiles"]["fixture-0"]["mode"] == "mop"
    loaded.async_command.assert_not_awaited()


async def test_profiles_survive_reload_and_ids_stay_stable(hass, entry, loaded):
    await loaded.async_set_profile("fixture-0", mode=CleaningMode.VACUUM_MOP, wetness_level=3)
    registry = er.async_get(hass)
    before = {
        r.unique_id: r.entity_id
        for r in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    restored = entry.runtime_data
    assert restored.profile("fixture-0").mode is CleaningMode.VACUUM_MOP
    assert restored.profile("fixture-0").wetness_level == 3
    after = {
        r.unique_id: r.entity_id
        for r in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert before == after


async def test_reset_button_clears_only_local_overrides(hass, entry, loaded):
    await loaded.async_set_profile("fixture-0", mode=CleaningMode.MOP, wetness_level=3)
    loaded.async_command = AsyncMock()
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": entity_id(hass, entry, "button", "reset_cleaning_profile")},
        blocking=True,
    )
    assert loaded.profile("fixture-0") == CleaningProfile()
    assert hass.states.get(entity_id(hass, entry, "number", "next_wetness_level")).state == "2"
    loaded.async_command.assert_not_awaited()


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "mop"},
        {"suction_level": 5},
        {"wetness_level": 0},
        {"two_pass": "true"},
        {"unknown": True},
    ],
)
async def test_invalid_preferences_do_not_change_storage_or_publish(loaded, entry, changes):
    with pytest.raises(HomeAssistantError):
        await loaded.async_set_profile("fixture-0", **changes)
    assert not loaded.profiles and "cleaning_profiles" not in entry.options


@pytest.mark.parametrize("value", [1.5, True, "2", None, float("inf"), float("nan")])
async def test_level_rejects_nonintegral_and_untyped_service_values(loaded, value):
    entity = RoombaCleaningLevel(loaded, "fixture-0", "suction_level")
    with pytest.raises(HomeAssistantError):
        await entity.async_set_native_value(value)
    assert not loaded.profiles


async def test_removed_or_unknown_capabilities_disable_retained_controls(loaded):
    entities = [
        RoombaCleaningMode(loaded, "fixture-0"),
        RoombaCleaningLevel(loaded, "fixture-0", "wetness_level"),
        RoombaCleaningOption(loaded, "fixture-0", "smart_scrub"),
        RoombaResetProfile(loaded, "fixture-0"),
    ]
    loaded.async_set_updated_data(
        {
            **loaded.data,
            "fixture-0": replace(loaded.data["fixture-0"], capabilities=DeviceCapabilities()),
        }
    )
    assert all(not entity.available for entity in entities)
    assert entities[0].options == [] and entities[0].current_option is None
    with pytest.raises(HomeAssistantError):
        await entities[0].async_select_option("mop")


async def test_missing_robot_leaves_controls_unknown(loaded):
    entities = [
        RoombaCleaningMode(loaded, "fixture-0"),
        RoombaCleaningLevel(loaded, "fixture-0", "wetness_level"),
        RoombaCleaningOption(loaded, "fixture-0", "two_pass"),
    ]
    loaded.data.pop("fixture-0")
    assert entities[0].options == [] and entities[0].current_option is None
    assert entities[1].native_value is None and entities[1].native_max_value == 1
    assert entities[2].is_on is None
    assert all(not e.available for e in entities)


async def test_unknown_reported_option_does_not_become_false(loaded):
    state = loaded.data["fixture-0"]
    for value in [None, 2, True, "1"]:
        loaded.data["fixture-0"] = replace(state, telemetry={"scrub_setting": value})
        assert RoombaCleaningOption(loaded, "fixture-0", "smart_scrub").is_on is None
    loaded.data["fixture-0"] = replace(state, telemetry={"two_pass": 1})
    assert RoombaCleaningOption(loaded, "fixture-0", "two_pass").is_on is None


async def test_unknown_or_invalid_saved_preferences_are_discarded(hass, entry):
    hass.config_entries.async_update_entry(
        entry,
        options={
            "cleaning_profiles": {
                "fixture-0": {"wetness_level": True},
                "unassociated": {"mode": "mop"},
            }
        },
    )
    coordinator = RoombaCoordinator(hass, entry)
    assert coordinator.profiles == {} and coordinator.profile("fixture-0") == CleaningProfile()
    hass.config_entries.async_update_entry(entry, options={"cleaning_profiles": []})
    assert RoombaCoordinator(hass, entry).profiles == {}


async def test_mop_only_device_defaults_to_its_supported_mode(loaded):
    loaded.data["fixture-0"] = replace(
        loaded.data["fixture-0"],
        capabilities=DeviceCapabilities(
            CleaningCapabilities(modes=frozenset({CleaningMode.MOP}), wetness_levels=3)
        ),
    )
    assert loaded.profile("fixture-0").mode is CleaningMode.MOP
    assert RoombaCleaningMode(loaded, "fixture-0").options == ["mop"]


@pytest.mark.parametrize("method", ["async_set_profile", "async_reset_profile"])
async def test_unconfigured_or_unloaded_robot_cannot_change_preferences(loaded, method):
    with pytest.raises(HomeAssistantError):
        await getattr(loaded, method)("unassociated")
    loaded._closed = True
    with pytest.raises(HomeAssistantError):
        await getattr(loaded, method)("fixture-0")
