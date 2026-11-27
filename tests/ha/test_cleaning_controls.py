"""Native HA control services, preferences and lifecycle, with a mocked cloud."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import probatio as vol
import pytest
from homeassistant.components.button import ButtonDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_platform
from homeassistant.helpers import entity_registry as er

from custom_components.roomba_home.button import RoombaResetProfile
from custom_components.roomba_home.const import DOMAIN
from custom_components.roomba_home.coordinator import (
    RobotControlAdapter,
    RoombaCoordinator,
    control_snapshot,
)
from custom_components.roomba_home.core.capabilities import DeviceCapabilities, DockCapabilities
from custom_components.roomba_home.core.cleaning import (
    CleaningCapabilities,
    CleaningMode,
    CleaningProfile,
)
from custom_components.roomba_home.core.commands import Command
from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.settings_protocol import RobotSetting
from custom_components.roomba_home.number import RoombaCleaningLevel
from custom_components.roomba_home.select import (
    RoombaCleaningMode,
    RoombaDockSelect,
    RoombaVoiceLanguage,
)
from custom_components.roomba_home.switch import RoombaCleaningOption
from custom_components.roomba_home.text import RoombaRobotName


def entity_id(hass, entry, domain, suffix, robot="fixture-0"):
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.unique_id}_{robot}_{suffix}"
    )


async def test_native_reboot_button_dispatches_only_for_the_selected_robot(hass, entry, loaded):
    loaded.async_command = AsyncMock()
    button = entity_id(hass, entry, "button", "reboot_robot")
    assert button
    device = er.async_get(hass).async_get(button)
    assert hass.states.get(button).attributes["device_class"] == ButtonDeviceClass.RESTART
    assert device.entity_category == EntityCategory.CONFIG
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    loaded.async_command.assert_awaited_once_with("fixture-0", Command.REBOOT)


async def test_install_voice_action_accepts_a_locale_but_no_package_path(hass, loaded):
    loaded.async_install_voice_language = AsyncMock()
    payload = {"entity_id": "vacuum.robot_0"}
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "install_voice_language",
            {**payload, "language": "picea_lang_pack/da_DK_v10.zip"},
            blocking=True,
        )
    loaded.async_install_voice_language.assert_not_awaited()
    await hass.services.async_call(
        DOMAIN, "install_voice_language", {**payload, "language": "da-dk"}, blocking=True
    )
    loaded.async_install_voice_language.assert_awaited_once_with("fixture-0", "da-dk")


async def test_mapping_action_requires_confirmation_and_paused_mapping_is_visible(
    hass, entry, loaded
):
    loaded.async_command = AsyncMock()
    robot = loaded.data["fixture-0"]
    can_map = replace(robot.capabilities, persistent_maps=True)
    loaded.async_set_updated_data(
        {**loaded.data, "fixture-0": replace(robot, capabilities=can_map)}
    )
    await hass.async_block_till_done()
    sensor = entity_id(hass, entry, "binary_sensor", "mapping")
    assert hass.states.get(sensor).state == "off"
    payload = {"entity_id": "vacuum.robot_0"}
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "start_mapping", payload, blocking=True)
    loaded.async_command.assert_not_awaited()
    await hass.services.async_call(
        DOMAIN, "start_mapping", {**payload, "confirmed": True}, blocking=True
    )
    loaded.async_command.assert_awaited_once_with("fixture-0", Command.START_MAPPING)
    loaded.async_set_updated_data(
        {
            **loaded.data,
            "fixture-0": replace(robot, capabilities=can_map, phase="stop", cycle="train"),
        }
    )
    assert hass.states.get(sensor).state == "on"
    assert hass.states.get("vacuum.robot_0").state == "paused"


async def test_clean_everywhere_requires_confirmation_and_does_not_resume(hass, loaded):
    robot = loaded.data["fixture-0"]
    target = {"entity_id": "vacuum.robot_0"}
    paused = control_snapshot(replace(robot, phase="stop", cycle="clean", connected=True))
    service = "clean_everywhere"
    with (
        patch.object(RobotControlAdapter, "refresh", return_value=paused) as refresh,
        patch.object(RobotControlAdapter, "send") as send,
    ):
        for value in ({}, {"confirmed": False}):
            with pytest.raises(vol.Invalid):
                await hass.services.async_call(DOMAIN, service, target | value, blocking=True)
        refresh.assert_not_awaited()
        with pytest.raises(HomeAssistantError) as error:
            await hass.services.async_call(
                DOMAIN, service, target | {"confirmed": True}, blocking=True
            )
        assert error.value.translation_key == "unsupported_start"
    send.assert_not_awaited()


async def test_clean_everywhere_uses_an_untargeted_command_and_confirms_start(hass, loaded):
    robot = loaded.data["fixture-0"]
    idle = replace(robot, phase="charge", cycle="none", connected=True)
    cleaning = replace(idle, phase="run", cycle="clean", mode=2)
    profile = CleaningProfile(CleaningMode.VACUUM, suction_level=1, two_pass=False)
    loaded.profiles["fixture-0"] = profile
    with (
        patch.object(
            RobotControlAdapter,
            "refresh",
            side_effect=[control_snapshot(idle), control_snapshot(cleaning)],
        ),
        patch.object(RobotControlAdapter, "wait"),
        patch.object(RobotControlAdapter, "send", autospec=True) as send,
    ):
        await hass.services.async_call(
            DOMAIN,
            "clean_everywhere",
            {"entity_id": "vacuum.robot_0", "confirmed": True},
            blocking=True,
        )
    send.assert_awaited_once()
    adapter, command, sent_profile = send.await_args.args
    assert adapter.target is None
    assert command is Command.VACUUM and sent_profile == profile
    assert loaded.command_status["fixture-0"] == "confirmed"


@pytest.mark.parametrize("wash_reads", [0, 54], ids=["direct", "post-return-wash"])
async def test_return_to_base_pauses_the_supported_robot_before_docking(hass, loaded, wash_reads):
    robot = loaded.data["fixture-0"]
    cleaning = replace(
        robot,
        phase="run",
        cycle="clean",
        mode=4 if wash_reads else 2,
        connected=True,
        capabilities=replace(robot.capabilities, docking=True),
        telemetry={
            **robot.telemetry,
            "mission_number": 10,
            "mission_started": datetime.fromtimestamp(100, UTC),
        },
    )
    paused = replace(cleaning, phase="stop")
    washing = replace(
        cleaning, phase="padWash", telemetry={**cleaning.telemetry, "pad_wash_state": 602}
    )
    docked = replace(cleaning, phase="charge", cycle="none")
    robot_states = [cleaning, paused, *([washing] * wash_reads), docked]
    states = [control_snapshot(state) for state in robot_states]
    elapsed = 0

    async def wait(seconds):
        nonlocal elapsed
        elapsed += seconds

    with (
        patch.object(RobotControlAdapter, "refresh", side_effect=states),
        patch.object(RobotControlAdapter, "wait", side_effect=wait),
        patch.object(RobotControlAdapter, "clock", side_effect=lambda: elapsed),
        patch.object(RobotControlAdapter, "send", autospec=True) as send,
    ):
        await hass.services.async_call(
            "vacuum", "return_to_base", {"entity_id": "vacuum.robot_0"}, blocking=True
        )
    assert [(call.args[0].robot_id, call.args[1]) for call in send.await_args_list] == [
        ("fixture-0", Command.PAUSE),
        ("fixture-0", Command.DOCK),
    ]
    assert loaded.command_status["fixture-0"] == "confirmed"
    assert elapsed == (wash_reads + 2) * 5


@pytest.mark.parametrize(
    ("phase", "next_action"),
    [
        ("hmUsrDock", "arrival"),
        ("hmPostMsn", "cancel"),
        ("hmMidMsn", "timeout"),
        ("hmUsrChrg", "timeout"),
    ],
)
async def test_long_return_uses_shared_state_and_releases_the_same_robot_for_cancellation(
    hass, loaded, phase, next_action
):
    robot_id = "fixture-0"
    robot = loaded.data[robot_id]
    cleaning = replace(
        robot,
        phase="run",
        cycle="clean",
        mode=4,
        connected=True,
        capabilities=replace(robot.capabilities, docking=True),
        telemetry={
            **robot.telemetry,
            "mission_number": 10,
            "mission_started": datetime.fromtimestamp(100, UTC),
        },
    )
    paused = replace(cleaning, phase="stop")
    travel = replace(cleaning, phase=phase, cycle="dock")
    wash = replace(
        cleaning, phase="padWash", telemetry={**cleaning.telemetry, "pad_wash_state": 602}
    )
    docked = replace(cleaning, phase="charge", cycle="none")
    states = [cleaning, paused, *([travel] * 24), travel, docked]
    elapsed = 0

    async def wait(seconds):
        nonlocal elapsed
        elapsed += seconds

    with (
        patch.object(RobotControlAdapter, "refresh", side_effect=map(control_snapshot, states)),
        patch.object(RobotControlAdapter, "wait", side_effect=wait),
        patch.object(loaded, "_clock", side_effect=lambda: elapsed),
        patch.object(RobotControlAdapter, "send", autospec=True) as send,
    ):
        service_data = {"entity_id": "vacuum.robot_0"}
        if next_action == "timeout":
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "vacuum", "return_to_base", service_data, blocking=True
                )
            assert loaded.command_status[robot_id] == "unconfirmed"
        else:
            await hass.services.async_call("vacuum", "return_to_base", service_data, blocking=True)
            assert loaded.command_status[robot_id] == "pending"
            assert elapsed == 125
            if next_action == "arrival":
                elapsed = 336
                loaded._reconcile_deferred_commands({robot_id: wash})
                assert loaded.command_status[robot_id] == "pending"
                # An idempotent start while the robot is washing does not replace its return.
                with patch.object(
                    RobotControlAdapter, "refresh", return_value=control_snapshot(wash)
                ):
                    await hass.services.async_call("vacuum", "start", service_data, blocking=True)
                assert loaded.command_status[robot_id] == "pending"
                elapsed = 571
                loaded._reconcile_deferred_commands({robot_id: docked})
            else:
                await hass.services.async_call("vacuum", "stop", service_data, blocking=True)
                assert loaded.command_status[robot_id] == "confirmed"
                loaded._reconcile_deferred_commands({robot_id: replace(travel, phase="stuck")})
            assert loaded.command_status[robot_id] == "confirmed"
        assert not loaded._deferred_commands

    expected = [Command.PAUSE, Command.DOCK]
    if next_action == "cancel":
        expected.append(Command.CANCEL)
    assert [(call.args[0].robot_id, call.args[1]) for call in send.await_args_list] == [
        (robot_id, command) for command in expected
    ]


async def test_maintenance_reset_action_requires_a_supported_part_and_confirmation(hass, loaded):
    loaded.async_reset_maintenance_counter = AsyncMock()
    target = {"entity_id": "vacuum.robot_0"}
    for fields in (
        {"part": "filter"},
        {"part": "filter", "confirmed": False},
        {"part": "filter", "confirmed": 1},
        {"part": "dust_bag", "confirmed": True},
    ):
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(
                DOMAIN, "reset_maintenance_counter", target | fields, blocking=True
            )
    loaded.async_reset_maintenance_counter.assert_not_awaited()
    await hass.services.async_call(
        DOMAIN,
        "reset_maintenance_counter",
        target | {"part": "filter", "confirmed": True},
        blocking=True,
    )
    loaded.async_reset_maintenance_counter.assert_awaited_once_with("fixture-0", "filter")


@pytest.mark.parametrize(
    "candidates,status,has_date",
    [((), "up_to_date", True), (("9.3.7",), "catalog_candidates", False)],
)
async def test_software_status_uses_the_reported_versions_and_preserves_the_installation_time(
    hass, entry, loaded, candidates, status, has_date
):
    robot_id = "fixture-0"
    robot = loaded.data[robot_id]
    updated = datetime(2026, 11, 25, 11, 22, tzinfo=UTC)
    telemetry = {
        **robot.telemetry,
        "software_version": "p25-705+9.3.6+I5.3.149",
        "dock_firmware": "42",
    }
    if has_date:
        telemetry["software_updated_at"] = updated
    loaded.async_set_updated_data({**loaded.data, robot_id: replace(robot, telemetry=telemetry)})
    await hass.async_block_till_done()
    catalog = loaded.client.firmware_candidates = AsyncMock(return_value=candidates)
    response = await hass.services.async_call(
        DOMAIN,
        "get_software_status",
        {"entity_id": "vacuum.robot_0"},
        blocking=True,
        return_response=True,
    )
    assert response["vacuum.robot_0"] == {
        "installed_version": telemetry["software_version"],
        "last_installed_at": updated.isoformat() if has_date else None,
        "dock_version": "42",
        "status": status,
        "catalog_versions": list(candidates),
    }
    catalog.assert_awaited_once_with(robot.sku, telemetry["software_version"], "42")
    if has_date:
        sensor = hass.states.get(entity_id(hass, entry, "sensor", "software_updated_at"))
        assert sensor.state == updated.isoformat()
        assert sensor.attributes["device_class"] == "timestamp"


@pytest.mark.parametrize(
    "cause", ["closed", "unknown_robot", "no_state", "stale", "no_version", "catalog_error"]
)
async def test_software_status_preserves_unknown_and_failed_states(loaded, cause):
    robot_id = "fixture-0"
    robot = loaded.data[robot_id]
    catalog = loaded.client.firmware_candidates = AsyncMock(
        side_effect=ProtocolError("private provider payload")
    )
    expected = "software_status_unavailable"
    match cause:
        case "closed":
            loaded._closed = True
            expected = "not_configured"
        case "unknown_robot":
            robot_id = "unassociated"
            expected = "not_configured"
        case "no_state":
            del loaded.data[robot_id]
        case "stale":
            loaded.last_update_success = False
        case "no_version":
            loaded.data[robot_id] = replace(robot, telemetry={})
        case "catalog_error":
            loaded.data[robot_id] = replace(robot, telemetry={"software_version": "9.3.6"})
    with pytest.raises(HomeAssistantError) as error:
        await loaded.async_get_software_status(robot_id)
    assert error.value.translation_key == expected
    assert "private provider payload" not in str(error.value)
    if cause == "catalog_error":
        catalog.assert_awaited_once_with(robot.sku, "9.3.6", None)
    else:
        catalog.assert_not_awaited()


async def test_robot_help_is_a_response_only_action_that_never_commands_the_robot(hass, loaded):
    robot = loaded.data["fixture-0"]
    catalog = {
        "manual_url": "https://prod-help-content.care.irobotapi.com/files/example.pdf",
        "support_url": "https://answers.irobot.com/appanswers",
        "device_guides": {},
        "articles": [],
    }

    async def read_while_entity_changes(*args):
        del loaded.data["fixture-0"]
        return catalog

    loaded.client.robot_help = AsyncMock(side_effect=read_while_entity_changes)
    loaded.async_command = AsyncMock()
    result = await hass.services.async_call(
        DOMAIN,
        "get_robot_help",
        {"entity_id": "vacuum.robot_0"},
        blocking=True,
        return_response=True,
    )
    report = result["vacuum.robot_0"]
    guide = report.pop("setup_guide")
    assert [step["id"] for step in guide["steps"]] == ["brushes", "water", "charge", "rooms"]
    assert report == {
        "robot": robot.name,
        **catalog,
        "current_articles": [],
    }
    loaded.client.robot_help.assert_awaited_once_with(robot.sku, hass.config.language)
    loaded.async_command.assert_not_awaited()


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("closed", "not_configured"),
        ("unselected", "not_configured"),
        ("no_state", "robot_help_unavailable"),
    ],
)
async def test_robot_help_requires_an_associated_model_before_requesting_catalog(
    loaded, condition, expected
):
    robot_id = "fixture-0"
    loaded.client.robot_help = AsyncMock()
    if condition == "closed":
        loaded._closed = True
    elif condition == "unselected":
        robot_id = "unassociated"
    else:
        del loaded.data[robot_id]
    with pytest.raises(HomeAssistantError) as error:
        await loaded.async_get_robot_help(robot_id)
    assert error.value.translation_key == expected
    loaded.client.robot_help.assert_not_awaited()


async def test_voice_catalog_action_lists_installed_and_downloadable_voice_codes(
    hass, entry, loaded
):
    robot_id = "fixture-0"
    state = loaded.data[robot_id]
    telemetry = {
        **state.telemetry,
        "voice_language": "es-ES",
        "installed_voice_languages": ("es-ES", "en-GB"),
    }
    loaded.async_set_updated_data({**loaded.data, robot_id: replace(state, telemetry=telemetry)})
    catalog = loaded.client.voice_catalog = AsyncMock(return_value=("cs-cz", "en-gb", "es-es"))
    response = await hass.services.async_call(
        DOMAIN,
        "list_voice_languages",
        {"entity_id": "vacuum.robot_0"},
        blocking=True,
        return_response=True,
    )
    assert response["vacuum.robot_0"] == {
        "current": "es-es",
        "installed": ["en-gb", "es-es"],
        "downloadable": ["cs-cz"],
    }
    catalog.assert_awaited_once_with(state.sku)

    telemetry.pop("voice_language")
    assert (await loaded.async_list_voice_languages(robot_id))["current"] is None
    catalog.side_effect = ProtocolError("Private provider information")
    with pytest.raises(HomeAssistantError) as error:
        await loaded.async_list_voice_languages(robot_id)
    assert error.value.translation_key == "voice_catalog_unavailable"
    assert "Private provider information" not in str(error.value)

    with pytest.raises(HomeAssistantError) as error:
        await loaded.async_list_voice_languages("unassociated")
    assert error.value.translation_key == "not_configured"
    loaded.last_update_success = False
    with pytest.raises(HomeAssistantError) as error:
        await loaded.async_list_voice_languages(robot_id)
    assert error.value.translation_key == "voice_catalog_unavailable"
    loaded.last_update_success = True
    telemetry.pop("installed_voice_languages")
    with pytest.raises(HomeAssistantError) as error:
        await loaded.async_list_voice_languages(robot_id)
    assert error.value.translation_key == "voice_catalog_unavailable"


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
            "audio_volume": 100,
            "child_lock": False,
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
    loaded.async_set_robot_setting = AsyncMock()
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
    assert [call.args for call in loaded.async_set_robot_setting.await_args_list] == [
        ("fixture-0", RobotSetting.WETNESS, 1),
        ("fixture-0", RobotSetting.SMART_SCRUB, True),
        ("fixture-0", RobotSetting.SMART_SCRUB, False),
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


async def test_device_configuration_entities_follow_the_fresh_robot_report(hass, entry, loaded):
    loaded.async_set_robot_setting = AsyncMock()
    loaded.async_command = AsyncMock()
    volume = entity_id(hass, entry, "number", "voice_volume")
    lock = entity_id(hass, entry, "switch", "child_pet_lock")
    registry = er.async_get(hass)
    robot = registry.async_get("vacuum.robot_0")
    for entity in (volume, lock):
        device_setting = registry.async_get(entity)
        assert device_setting.device_id == robot.device_id
        assert device_setting.entity_category == EntityCategory.CONFIG
    assert not entity_id(hass, entry, "number", "voice_volume", "fixture-1")
    assert not entity_id(hass, entry, "switch", "child_pet_lock", "fixture-1")
    volume_state = hass.states.get(volume)
    assert (volume_state.attributes["min"], volume_state.attributes["max"]) == (0, 100)
    assert volume_state.attributes["unit_of_measurement"] == "%"
    assert float(volume_state.state) == 100
    assert hass.states.get(lock).state == "off"

    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": volume, "value": 37.5}, blocking=True
        )
    assert error.value.translation_key == "unsupported_robot_setting"
    await hass.services.async_call(
        "number", "set_value", {"entity_id": volume, "value": 0}, blocking=True
    )
    await hass.services.async_call("switch", "turn_on", {"entity_id": lock}, blocking=True)
    await hass.services.async_call("switch", "turn_off", {"entity_id": lock}, blocking=True)
    assert [call.args for call in loaded.async_set_robot_setting.await_args_list] == [
        ("fixture-0", RobotSetting.VOICE_VOLUME, 0),
        ("fixture-0", RobotSetting.CHILD_PET_LOCK, True),
        ("fixture-0", RobotSetting.CHILD_PET_LOCK, False),
    ]
    loaded.async_command.assert_not_awaited()

    saved = loaded.data["fixture-0"]
    loaded.async_set_updated_data({**loaded.data, "fixture-0": replace(saved, telemetry={})})
    await hass.async_block_till_done()
    assert hass.states.get(volume).state == hass.states.get(lock).state == "unavailable"
    other_devices = {key: state for key, state in loaded.data.items() if key != "fixture-0"}
    loaded.async_set_updated_data(other_devices)
    await hass.async_block_till_done()
    assert hass.states.get(volume).state == hass.states.get(lock).state == "unavailable"
    updated = replace(saved, telemetry={**saved.telemetry, "audio_volume": 0, "child_lock": True})
    loaded.async_set_updated_data({**other_devices, "fixture-0": updated})
    await hass.async_block_till_done()
    assert float(hass.states.get(volume).state) == 0
    assert hass.states.get(lock).state == "on"


async def test_name_and_installed_voice_entities_keep_identity_and_use_native_services(
    hass, entry, loaded
):
    robot_id = "fixture-0"
    state = loaded.data[robot_id]
    telemetry = {
        "voice_language": "es-ES",
        "installed_voice_languages": ("es-ES", "en-GB"),
    }
    supported = replace(
        state, reported_name="Fixture robot", telemetry={**state.telemetry, **telemetry}
    )
    loaded.async_set_updated_data({**loaded.data, robot_id: supported})
    await hass.async_block_till_done()
    name = entity_id(hass, entry, "text", "robot_name")
    voice = entity_id(hass, entry, "select", "voice_language")
    assert name and voice
    assert not entity_id(hass, entry, "text", "robot_name", "fixture-1")
    assert not entity_id(hass, entry, "select", "voice_language", "fixture-1")
    registry = er.async_get(hass)
    for entity in (name, voice):
        record = registry.async_get(entity)
        assert record.device_id == registry.async_get("vacuum.robot_0").device_id
        assert record.entity_category == EntityCategory.CONFIG
    assert hass.states.get(name).state == "Fixture robot"
    assert hass.states.get(name).attributes["max"] == 63
    assert hass.states.get(voice).state == "es-es"
    assert hass.states.get(voice).attributes["options"] == ["es-es", "en-gb"]
    loaded.async_set_robot_setting = AsyncMock()
    await hass.services.async_call(
        "text", "set_value", {"entity_id": name, "value": "Ático"}, blocking=True
    )
    await hass.services.async_call(
        "select", "select_option", {"entity_id": voice, "option": "en-gb"}, blocking=True
    )
    assert [call.args for call in loaded.async_set_robot_setting.await_args_list] == [
        (robot_id, RobotSetting.NAME, "Ático"),
        (robot_id, RobotSetting.VOICE_LANGUAGE, "en-GB"),
    ]
    selector = RoombaVoiceLanguage(loaded, robot_id, "voice_language")
    name_input = RoombaRobotName(loaded, robot_id, "robot_name")
    with pytest.raises(HomeAssistantError) as error:
        await selector.async_select_option("cs-CZ")
    assert error.value.translation_key == "voice_language_not_installed"
    loaded.async_set_updated_data({**loaded.data, robot_id: state})
    await hass.async_block_till_done()
    assert hass.states.get(voice).state == hass.states.get(name).state == "unavailable"

    others = {key: robot for key, robot in loaded.data.items() if key != robot_id}
    loaded.async_set_updated_data(others)
    assert selector.options == [] and selector.current_option is None
    assert name_input.native_value is None

    loaded.async_set_updated_data({**others, robot_id: supported})
    await hass.async_block_till_done()
    assert hass.states.get(voice).state == "es-es"
    assert hass.states.get(name).state == "Fixture robot"


async def test_dock_configuration_uses_native_choices_and_the_existing_dock_device(
    hass, entry, loaded
):
    robot_id = "fixture-0"
    robot = loaded.data[robot_id]
    other = loaded.data["fixture-1"]
    observed = {
        "pad_wash_heat": 0,
        "pad_wash_return": 100,
        "detergent_setting": 0,
        "pad_dry_duration": 4,
    }
    dock = DockCapabilities(recognized=True, wash=True, dry=True)
    capable = replace(
        robot,
        telemetry={**robot.telemetry, **observed},
        capabilities=replace(robot.capabilities, dock=dock),
    )
    unsupported = replace(other, telemetry=observed)
    loaded.async_set_updated_data({**loaded.data, robot_id: capable, "fixture-1": unsupported})
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    temperature = registry.async_get(entity_id(hass, entry, "select", "mop_wash_temperature"))
    dock_device = dr.async_get(hass).async_get(temperature.device_id)
    robot_device_id = registry.async_get("vacuum.robot_0").device_id
    assert (DOMAIN, f"{entry.unique_id}_{robot_id}_dock") in dock_device.identifiers
    assert dock_device.parent_device_id == robot_device_id
    settings = (
        (
            "select",
            "mop_wash_temperature",
            "room_temperature",
            ["room_temperature", "hot", "very_hot"],
        ),
        ("select", "mop_wash_frequency", "standard", ["standard", "medium", "high"]),
        (
            "select",
            "mop_drying_duration",
            "four_hours",
            ["three_hours", "four_hours", "five_hours"],
        ),
        ("switch", "automatic_mop_detergent", "off", None),
    )
    entities = {}
    for domain, key, initial, options in settings:
        identifier = entity_id(hass, entry, domain, key)
        assert identifier and not entity_id(hass, entry, domain, key, "fixture-1")
        entity = registry.async_get(identifier)
        assert (
            entity.device_id == dock_device.id and entity.entity_category == EntityCategory.CONFIG
        )
        assert hass.states.get(identifier).state == initial
        assert hass.states.get(identifier).attributes.get("options") == options
        entities[key] = identifier

    loaded.async_set_robot_setting = AsyncMock()
    loaded.async_command = AsyncMock()
    for key, option in (
        ("mop_wash_temperature", "very_hot"),
        ("mop_wash_frequency", "high"),
        ("mop_drying_duration", "five_hours"),
    ):
        await hass.services.async_call(
            "select", "select_option", {"entity_id": entities[key], "option": option}, blocking=True
        )
    switch = entities["automatic_mop_detergent"]
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    choice = RoombaDockSelect(loaded, robot_id, "mop_wash_temperature")
    with pytest.raises(HomeAssistantError) as error:
        await choice.async_select_option("unverified")
    assert error.value.translation_key == "unsupported_robot_setting"
    assert [call.args for call in loaded.async_set_robot_setting.await_args_list] == [
        (robot_id, RobotSetting.PAD_WASH_TEMPERATURE, 2),
        (robot_id, RobotSetting.PAD_WASH_FREQUENCY, 102),
        (robot_id, RobotSetting.PAD_DRY_DURATION, 5),
        (robot_id, RobotSetting.AUTOMATIC_DETERGENT, True),
        (robot_id, RobotSetting.AUTOMATIC_DETERGENT, False),
    ]
    loaded.async_command.assert_not_awaited()

    invalid = {
        "pad_wash_heat": 4,
        "pad_wash_return": 2,
        "pad_dry_duration": 7,
        "detergent_setting": True,
    }
    partial = replace(capable, telemetry=invalid)
    detached = replace(capable, capabilities=replace(capable.capabilities, dock=DockCapabilities()))
    for unavailable in (partial, detached, None):
        data = {k: v for k, v in loaded.data.items() if k != robot_id}
        if unavailable is not None:
            data[robot_id] = unavailable
        loaded.async_set_updated_data(data)
        await hass.async_block_till_done()
        assert all(hass.states.get(entity).state == "unavailable" for entity in entities.values())
        assert choice.current_option is None
    loaded.async_set_updated_data({**loaded.data, robot_id: capable})
    await hass.async_block_till_done()
    for domain, key, initial, _ in settings:
        assert entity_id(hass, entry, domain, key) == entities[key]
        assert hass.states.get(entities[key]).state == initial


async def test_default_suction_is_a_native_control_separate_from_the_next_mission(
    hass, entry, loaded
):
    loaded.async_set_robot_setting = AsyncMock()
    loaded.async_command = AsyncMock()
    await loaded.async_set_profile("fixture-0", suction_level=4)
    uid = entity_id(hass, entry, "number", "default_suction_level")
    assert er.async_get(hass).async_get(uid).entity_category == EntityCategory.CONFIG
    assert not entity_id(hass, entry, "number", "default_suction_level", "fixture-1")
    assert float(hass.states.get(uid).state) == 3
    await hass.services.async_call(
        "number", "set_value", {"entity_id": uid, "value": 2}, blocking=True
    )
    loaded.async_set_robot_setting.assert_awaited_once_with("fixture-0", RobotSetting.SUCTION, 2)
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
        ("two_pass", RobotSetting.TWO_PASS, False),
        ("carpet_boost", RobotSetting.CARPET_BOOST, True),
    ],
)
async def test_default_switch_preserves_the_next_mission_preference(
    hass, entry, loaded, field, setting, reported
):
    loaded.async_set_robot_setting = AsyncMock()
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
    loaded.async_set_robot_setting.assert_awaited_once_with("fixture-0", setting, not reported)
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
    coordinator.async_set_robot_setting = AsyncMock()
    registry = er.async_get(hass)
    from homeassistant.helpers import device_registry as dr

    area = entity_id(hass, entry, "number", "auto_evacuation_area")
    code = entity_id(hass, entry, "sensor", "auto_evacuation_frequency")
    frequency = entity_id(hass, entry, "select", "auto_empty_frequency")
    dock_id = registry.async_get(area).device_id
    robot_id = registry.async_get("vacuum.robot_0").device_id
    assert registry.async_get(code).device_id == robot_id
    assert dr.async_get(hass).async_get(dock_id).parent_device_id == robot_id
    assert registry.async_get(area).entity_category == EntityCategory.CONFIG
    assert registry.async_get(frequency).device_id == dock_id
    assert registry.async_get(frequency).entity_category == EntityCategory.CONFIG
    assert entity_id(hass, entry, "select", "auto_empty_frequency", "fixture-1") is None
    assert hass.states.get(frequency).state == "every_25_m2"
    native_options = ["after_each_routine", "every_25_m2", "every_50_m2"]
    assert hass.states.get(frequency).attributes["options"] == native_options
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
    coordinator.async_set_robot_setting.assert_awaited_once_with(
        robot, RobotSetting.AUTO_EVACUATION_AREA, 50
    )
    registry.async_update_entity_options(area, "number", {"unit_of_measurement": "ft²"})
    await hass.async_block_till_done()
    assert hass.states.get(area).attributes["unit_of_measurement"] == "ft²"
    await hass.services.async_call(
        "number", "set_value", {"entity_id": area, "value": 538}, blocking=True
    )
    assert coordinator.async_set_robot_setting.await_count == 2
    assert coordinator.async_set_robot_setting.await_args.args == (
        robot,
        RobotSetting.AUTO_EVACUATION_AREA,
        50,
    )
    registry.async_update_entity_options(area, "number", {"unit_of_measurement": "m²"})
    await hass.async_block_till_done()
    coordinator.async_set_robot_setting.reset_mock()

    for choice, requested in zip(native_options, (0, 25, 50), strict=True):
        await hass.services.async_call(
            "select", "select_option", {"entity_id": frequency, "option": choice}, blocking=True
        )
        assert coordinator.async_set_robot_setting.await_args.args == (
            robot,
            RobotSetting.AUTO_EVACUATION_AREA,
            requested,
        )
    coordinator.async_set_robot_setting.reset_mock()
    for reported, selected in ((0, "after_each_routine"), (37, "custom_area")):
        updated = replace(
            robot_states[robot], telemetry={**telemetry, "auto_evacuation_frequency": reported}
        )
        coordinator.async_set_updated_data({**robot_states, robot: updated})
        await hass.async_block_till_done()
        assert hass.states.get(frequency).state == selected
        assert hass.states.get(frequency).attributes["options"] == (
            native_options if reported == 0 else [*native_options, "custom_area"]
        )
        if reported == 0:
            assert hass.states.get(area).state == "unknown"
            assert hass.states.get(code).state == "0"
            await hass.services.async_call(
                "number", "set_value", {"entity_id": area, "value": 37}, blocking=True
            )
            coordinator.async_set_robot_setting.assert_awaited_once_with(
                robot, RobotSetting.AUTO_EVACUATION_AREA, 37
            )
        else:
            assert float(hass.states.get(area).state) == 37
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": frequency, "option": "custom_area"},
                blocking=True,
            )
            assert coordinator.async_set_robot_setting.await_count == 1

    (number_platform,) = (
        platform
        for platform in entity_platform.async_get_platforms(hass, DOMAIN)
        if platform.domain == "number"
    )
    with pytest.raises(HomeAssistantError) as error:
        await number_platform.entities[area].async_set_native_value(0)
    assert error.value.translation_key == "unsupported_robot_setting"
    assert coordinator.async_set_robot_setting.await_count == 1

    for unavailable in (
        replace(robot_states[robot], capabilities=replace(device, dock=DockCapabilities())),
        replace(robot_states[robot], telemetry={**telemetry, "auto_evacuation_frequency": 4}),
    ):
        coordinator.async_set_updated_data({**robot_states, robot: unavailable})
        await hass.async_block_till_done()
        assert hass.states.get(area).state == "unavailable"
        assert hass.states.get(frequency).state == "unavailable"
    coordinator.async_set_updated_data(robot_states)
    await hass.async_block_till_done()
    assert entity_id(hass, entry, "number", "auto_evacuation_area") == area
    assert entity_id(hass, entry, "select", "auto_empty_frequency") == frequency
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
