import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.roomba_home.coordinator import RoombaCoordinator
from custom_components.roomba_home.core.capabilities import DockCapabilities
from custom_components.roomba_home.core.cleaning import CleaningCapabilities, CleaningProfile
from custom_components.roomba_home.core.commands import Command
from custom_components.roomba_home.core.errors import (
    AuthenticationError,
    ProtocolError,
    RateLimited,
)
from custom_components.roomba_home.core.mqtt import MqttProfile, ShadowReply
from custom_components.roomba_home.core.settings_protocol import RobotSetting
from custom_components.roomba_home.core.voice_catalog import VoicePack


@pytest.fixture
async def coordinator(hass, entry, robot_states):
    value = RoombaCoordinator(hass, entry)
    value.async_set_updated_data(robot_states)
    value.client.ensure_session = AsyncMock(return_value=object())
    value.async_refresh = AsyncMock()
    value._sleep = AsyncMock()
    return value


@pytest.fixture
def mop_wire(coordinator):
    with (
        patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender_type,
        patch("custom_components.roomba_home.coordinator.MqttShadowReader") as reader_type,
    ):
        sender = sender_type.return_value
        sender.capabilities = coordinator.data["fixture-0"].capabilities.cleaning
        sender.profile = MqttProfile("fixture", "client", {}, {"fixture-0": "a", "fixture-1": "b"})
        yield sender, reader_type


def settings_reply(reported):
    document = {"state": {"reported": reported}}
    return [ShadowReply("fixture-0", "rw-settings", True, document)]


VOICE_ID = "LANG261125120000"
VOICE_PACK = VoicePack("cs-CZ", "picea_lang_pack/cs_CZ_v10.zip")


def voice_replies(
    *, stage=0, installed=False, selected="es-ES", identifier=None, slots=1, pending=None
):
    langs = {
        "aSlots": slots,
        "sLang": selected,
        "dLangs": {"langs": ["es-ES"]},
        "uLangs": {"langs": ["cs-CZ"] if installed else []},
    }
    firmware = {
        "state": {
            "reported": {"deploymentState": stage, "deploymentId": identifier},
            "desired": {"deploymentId": pending},
        }
    }
    return [
        *settings_reply({"langs2": langs}),
        ShadowReply("fixture-0", "rw-software", True, firmware),
    ]


@pytest.mark.parametrize("already_selected", [True, False])
async def test_voice_install_waits_for_fresh_pack_then_selects_if_needed(
    coordinator, mop_wire, already_selected
):
    sender, reader = mop_wire
    coordinator.client.voice_pack = AsyncMock(return_value=VOICE_PACK)
    coordinator._write_robot_setting = AsyncMock()
    sender.install_voice_pack.side_effect = ProtocolError("lost acknowledgement")
    reader.return_value.read.side_effect = [
        voice_replies(),
        ProtocolError("temporary read failure"),
        voice_replies(stage=4, identifier=VOICE_ID),
        voice_replies(installed=True, identifier="old-deployment"),
        voice_replies(
            installed=True, identifier=VOICE_ID, selected="cs-CZ" if already_selected else "es-ES"
        ),
    ]
    with patch(
        "custom_components.roomba_home.coordinator.voice_deployment_id", return_value=VOICE_ID
    ):
        await coordinator.async_install_voice_language("fixture-0", "cs-cz")
    sender.install_voice_pack.assert_called_once_with(VOICE_ID, VOICE_PACK)
    coordinator.client.voice_pack.assert_awaited_once_with("X185240", "cs-cz")
    if already_selected:
        coordinator._write_robot_setting.assert_not_awaited()
    else:
        coordinator._write_robot_setting.assert_awaited_once_with(
            "fixture-0", RobotSetting.VOICE_LANGUAGE, "cs-CZ"
        )
    assert coordinator.command_status["fixture-0"] == "confirmed"
    assert coordinator.data["fixture-0"].telemetry["installed_voice_languages"] == (
        "es-ES",
        "cs-CZ",
    )


async def test_installing_an_installed_voice_selects_without_another_deployment(
    coordinator, mop_wire
):
    sender, reader = mop_wire
    coordinator._write_robot_setting = AsyncMock()
    reader.return_value.read.return_value = voice_replies(installed=True)
    await coordinator.async_install_voice_language("fixture-0", "cs-cz")
    coordinator._write_robot_setting.assert_awaited_once_with(
        "fixture-0", RobotSetting.VOICE_LANGUAGE, "cs-CZ"
    )
    sender.install_voice_pack.assert_not_called()


async def test_voice_observation_preserves_robot_removal_from_cache(coordinator, mop_wire):
    sender, reader = mop_wire
    del coordinator.data["fixture-0"]
    reader.return_value.read.return_value = voice_replies(installed=True, identifier=VOICE_ID)
    observed = await coordinator._read_voice_installation("fixture-0", sender)
    assert observed.result(VOICE_ID, "cs-CZ") == "installed"
    assert "fixture-0" not in coordinator.data
    assert "fixture-0" not in coordinator._details


def part_read(counter):
    return {
        "parts": [{"part_id": "72", "counter": counter, "count_type": "minutes", "count_used": 0}]
    }


async def test_part_reset_updates_reported_counter_after_one_write(coordinator):
    coordinator.client.robot_parts = AsyncMock(
        side_effect=[part_read(63), part_read(63), part_read(0)]
    )
    coordinator.client.reset_part = AsyncMock()
    await coordinator.async_reset_maintenance_counter("fixture-0", "filter")
    coordinator.client.reset_part.assert_awaited_once_with("fixture-0", "72")
    assert coordinator.client.robot_parts.await_count == 3
    assert coordinator.data["fixture-0"].telemetry["part_72_usage"] == 0
    assert coordinator._parts["fixture-0"] == part_read(0)


@pytest.mark.parametrize("cause", ["missing_robot", "stale_state", "unsupported_part", "disabled"])
async def test_part_reset_rejects_unavailable_counter(coordinator, cause):
    robot_id = "fixture-0"
    part = "filter"
    coordinator.client.robot_parts = AsyncMock(return_value=part_read(40))
    coordinator.client.reset_part = AsyncMock()
    match cause:
        case "missing_robot":
            del coordinator.data[robot_id]
        case "stale_state":
            coordinator.last_update_success = False
        case "unsupported_part":
            part = "dust_bag"
        case "disabled":
            coordinator._part_catalog = {"parts": [{"part_id": "72", "counter_enabled": False}]}
    with pytest.raises(HomeAssistantError) as error:
        await coordinator.async_reset_maintenance_counter(robot_id, part)
    assert error.value.translation_key == "part_reset_unavailable"
    coordinator.client.reset_part.assert_not_awaited()


@pytest.mark.parametrize(
    "failure", [None, ProtocolError("private acknowledgement"), OSError("private connection")]
)
async def test_part_reset_reports_missing_confirmation_without_retrying_the_post(
    coordinator, failure
):
    coordinator.client.robot_parts = AsyncMock(return_value=part_read(40))
    coordinator.client.reset_part = AsyncMock(side_effect=failure)
    with pytest.raises(HomeAssistantError) as error:
        await coordinator.async_reset_maintenance_counter("fixture-0", "filter")
    assert error.value.translation_key == "part_reset_unconfirmed"
    assert "private" not in str(error.value)
    coordinator.client.reset_part.assert_awaited_once_with("fixture-0", "72")


async def test_part_reset_requests_reauthentication_and_skips_the_post(coordinator):
    coordinator.client.robot_parts = AsyncMock(side_effect=AuthenticationError())
    coordinator.client.reset_part = AsyncMock()
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator.async_reset_maintenance_counter("fixture-0", "filter")
    coordinator.client.reset_part.assert_not_awaited()


@pytest.mark.parametrize(
    ("state_changes", "shadow", "pack", "key"),
    [
        ({"connected": False}, {}, VOICE_PACK, "voice_install_unavailable"),
        ({"phase": "stop"}, {}, VOICE_PACK, "voice_install_requires_dock"),
        ({}, {"slots": 0}, VOICE_PACK, "voice_install_unavailable"),
        ({}, {"stage": None}, VOICE_PACK, "voice_install_unavailable"),
        ({}, {"stage": 4}, VOICE_PACK, "voice_install_busy"),
        ({}, {"pending": "other"}, VOICE_PACK, "voice_install_busy"),
        ({}, {}, None, "unsupported_voice_pack"),
    ],
)
async def test_voice_install_preconditions_reject_without_publishing(
    coordinator, mop_wire, state_changes, shadow, pack, key
):
    sender, reader = mop_wire
    robot_id = "fixture-0"
    coordinator.data[robot_id] = replace(coordinator.data[robot_id], **state_changes)
    coordinator.client.voice_pack = AsyncMock(return_value=pack)
    reader.return_value.read.return_value = voice_replies(**shadow)
    with pytest.raises(HomeAssistantError) as error:
        await coordinator.async_install_voice_language(robot_id, "cs-cz")
    assert error.value.translation_key == key
    sender.install_voice_pack.assert_not_called()


@pytest.mark.parametrize(
    ("stage", "key"), [(132, "voice_install_failed"), (2, "voice_install_unconfirmed")]
)
async def test_voice_install_failure_and_timeout_never_republish(coordinator, mop_wire, stage, key):
    sender, reader = mop_wire
    coordinator.client.voice_pack = AsyncMock(return_value=VOICE_PACK)
    coordinator._clock = MagicMock(side_effect=(0, 0, 601))
    reader.return_value.read.side_effect = [
        voice_replies(),
        voice_replies(stage=stage, identifier=VOICE_ID),
    ]
    with (
        patch(
            "custom_components.roomba_home.coordinator.voice_deployment_id", return_value=VOICE_ID
        ),
        pytest.raises(HomeAssistantError) as error,
    ):
        await coordinator.async_install_voice_language("fixture-0", "cs-cz")
    assert error.value.translation_key == key
    sender.install_voice_pack.assert_called_once()
    assert coordinator.command_status["fixture-0"] == "unconfirmed"


async def test_voice_cancellation_after_dispatch_records_unconfirmed(coordinator, mop_wire):
    sender, reader = mop_wire
    coordinator.client.voice_pack = AsyncMock(return_value=VOICE_PACK)
    reader.return_value.read.return_value = voice_replies()
    sender.install_voice_pack.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await coordinator.async_install_voice_language("fixture-0", "cs-cz")
    assert coordinator.command_status["fixture-0"] == "unconfirmed"


@pytest.mark.parametrize("exception", [AuthenticationError("private"), ProtocolError("private")])
async def test_voice_install_translates_provider_errors(coordinator, mop_wire, exception):
    sender, _ = mop_wire
    coordinator.client.ensure_session.side_effect = exception
    expected = (
        ConfigEntryAuthFailed if isinstance(exception, AuthenticationError) else HomeAssistantError
    )
    with pytest.raises(expected) as error:
        await coordinator.async_install_voice_language("fixture-0", "cs-cz")
    assert "private" not in str(error.value)
    sender.install_voice_pack.assert_not_called()


@pytest.mark.parametrize(
    ("setting", "target", "before", "after"),
    [
        (RobotSetting.VOICE_VOLUME, 0, {"audio": {"volume": 100}}, {"audio": {"volume": 0}}),
        (
            RobotSetting.VOICE_LANGUAGE,
            "en-GB",
            {"langs2": {"sLang": "es-ES", "dLangs": {"langs": ["es-ES", "en-GB"]}}},
            {"langs2": {"sLang": "en-GB", "dLangs": {"langs": ["es-ES", "en-GB"]}}},
        ),
        (RobotSetting.NAME, "Fixture robot", {"name": "Original"}, {"name": "Fixture robot"}),
        (RobotSetting.CHILD_PET_LOCK, True, {"childLock": False}, {"childLock": True}),
        (RobotSetting.PAD_WASH_TEMPERATURE, 0, {"pwHeat": 1}, {"pwHeat": 0}),
        (
            RobotSetting.PAD_WASH_FREQUENCY,
            102,
            {"pwReturn": 100, "pwAreaInterval": 10},
            {"pwReturn": 102, "pwAreaInterval": 10},
        ),
        (RobotSetting.AUTOMATIC_DETERGENT, False, {"detergent": 1}, {"detergent": 0}),
        (RobotSetting.PAD_DRY_DURATION, 3, {"padDryDur": 4}, {"padDryDur": 3}),
    ],
)
async def test_robot_setting_waits_for_reported_value_without_changing_the_mission(
    coordinator, mop_wire, setting, target, before, after
):
    sender, reader = mop_wire
    robot = coordinator.data["fixture-0"]
    coordinator.data["fixture-0"] = replace(
        robot,
        capabilities=replace(robot.capabilities, dock=DockCapabilities(True, wash=True, dry=True)),
    )
    reader.return_value.read.side_effect = [
        settings_reply(before),
        settings_reply(before),
        settings_reply(after),
    ]
    mission = coordinator.data["fixture-0"].cycle
    await coordinator.async_set_robot_setting("fixture-0", setting, target)
    sender.write_robot_setting.assert_called_once_with(setting, target)
    sender.send.assert_not_called()
    assert coordinator.data["fixture-0"].cycle == mission
    if setting is RobotSetting.NAME:
        assert coordinator.data["fixture-0"].name == target
        assert coordinator.data["fixture-0"].reported_name == target
        assert "robot_name" not in coordinator.data["fixture-0"].telemetry
    else:
        assert coordinator.data["fixture-0"].telemetry[setting.value] == target


async def test_voice_language_uses_the_fresh_installed_list_before_publishing(
    coordinator, mop_wire
):
    sender, reader = mop_wire
    reader.return_value.read.return_value = settings_reply(
        {"langs2": {"sLang": "es-ES", "dLangs": {"langs": ["es-ES"]}}}
    )
    with pytest.raises(HomeAssistantError) as error:
        await coordinator.async_set_robot_setting("fixture-0", RobotSetting.VOICE_LANGUAGE, "en-GB")
    assert error.value.translation_key == "voice_language_not_installed"
    sender.write_robot_setting.assert_not_called()


async def test_roomba_rename_preserves_local_device_alias_and_identity(
    hass, entry, coordinator, mop_wire
):
    robot_id = "fixture-0"
    robot = coordinator.data[robot_id]
    identifiers = {("roomba_home", f"{entry.unique_id}_{robot_id}")}
    registry = device_registry.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers=identifiers, name=robot.name
    )
    registry.async_update_device(device.id, name_by_user="My local alias")
    sender, reader = mop_wire
    reader.return_value.read.side_effect = [
        settings_reply({"name": robot.name}),
        settings_reply({"name": "Changed in Home Assistant"}),
    ]
    await coordinator.async_set_robot_setting(
        robot_id, RobotSetting.NAME, "Changed in Home Assistant"
    )
    sender.write_robot_setting.assert_called_once()
    updated = registry.async_get(device.id)
    assert updated.name == "Changed in Home Assistant" and updated.name_by_user == "My local alias"
    assert updated.identifiers == identifiers

    # An external rename arrives through normal polling, with the same registry identity.
    renamed = replace(robot, name="Changed in Roomba", reported_name="Changed in Roomba")
    coordinator._read_account_state = AsyncMock(return_value={robot_id: renamed})
    assert await coordinator._async_update_data() == {robot_id: renamed}
    assert registry.async_get(device.id).name == renamed.name
    assert registry.async_get(device.id).name_by_user == "My local alias"
    assert await coordinator._async_update_data() == {robot_id: renamed}


@pytest.mark.parametrize(
    "setting,value,dock",
    [
        (RobotSetting.PAD_WASH_TEMPERATURE, 2, DockCapabilities(wash=True)),
        (RobotSetting.PAD_WASH_FREQUENCY, 101, DockCapabilities(recognized=True, wash=False)),
        (RobotSetting.PAD_DRY_DURATION, 5, DockCapabilities(recognized=True, wash=True)),
        (RobotSetting.AUTOMATIC_DETERGENT, True, DockCapabilities(recognized=True, dry=True)),
    ],
)
async def test_dock_preference_requires_the_matching_live_dock(
    coordinator, mop_wire, setting, value, dock
):
    sender, _ = mop_wire
    robot = coordinator.data["fixture-0"]
    coordinator.data["fixture-0"] = replace(
        robot, capabilities=replace(robot.capabilities, dock=dock)
    )
    with pytest.raises(HomeAssistantError) as error:
        await coordinator.async_set_robot_setting("fixture-0", setting, value)
    assert error.value.translation_key == "unsupported_dock_action"
    coordinator.client.ensure_session.assert_not_awaited()
    sender.write_robot_setting.assert_not_called()


@pytest.mark.parametrize(
    "setting,value", [(RobotSetting.VOICE_VOLUME, 101), (RobotSetting.CHILD_PET_LOCK, 1)]
)
async def test_robot_setting_rejects_invalid_values_before_opening_a_session(
    coordinator, mop_wire, setting, value
):
    sender, _ = mop_wire
    with pytest.raises(HomeAssistantError) as error:
        await coordinator.async_set_robot_setting("fixture-0", setting, value)
    assert error.value.translation_key == "unsupported_robot_setting"
    coordinator.client.ensure_session.assert_not_awaited()
    sender.write_robot_setting.assert_not_called()


@pytest.mark.parametrize(
    "dock", [DockCapabilities(), DockCapabilities(recognized=True, evacuation=False)]
)
async def test_auto_evacuation_area_needs_matching_live_dock_capability(
    coordinator, mop_wire, dock
):
    sender, _ = mop_wire
    state = coordinator.data["fixture-0"]
    cleaning = replace(state.capabilities.cleaning, auto_evacuation_area=True)
    coordinator.data["fixture-0"] = replace(
        state, capabilities=replace(state.capabilities, cleaning=cleaning, dock=dock)
    )
    with pytest.raises(HomeAssistantError) as error:
        await coordinator.async_set_robot_setting(
            "fixture-0", RobotSetting.AUTO_EVACUATION_AREA, 50
        )
    assert error.value.translation_key == "unsupported_dock_action"
    coordinator.client.ensure_session.assert_not_awaited()
    sender.write_robot_setting.assert_not_called()


@pytest.mark.parametrize(
    ("observed", "requested", "allowed"),
    [(4, 50, False), (4, 0, False), (25, 50, True), (25, 0, True), (0, 50, True)],
)
async def test_auto_evacuation_updates_recognized_frequency_schemes(
    coordinator, mop_wire, observed, requested, allowed
):
    sender, reader = mop_wire
    state = coordinator.data["fixture-0"]
    cleaning = replace(state.capabilities.cleaning, auto_evacuation_area=True)
    coordinator.data["fixture-0"] = replace(
        state,
        capabilities=replace(
            state.capabilities,
            cleaning=cleaning,
            dock=DockCapabilities(recognized=True, evacuation=True),
        ),
    )
    sender.capabilities = cleaning
    reader.return_value.read.side_effect = [
        settings_reply({"autoevacFreq": observed}),
        settings_reply({"autoevacFreq": requested}),
    ]
    if not allowed:
        with pytest.raises(HomeAssistantError) as error:
            await coordinator.async_set_robot_setting(
                "fixture-0", RobotSetting.AUTO_EVACUATION_AREA, requested
            )
        assert error.value.translation_key == "robot_setting_unavailable"
        sender.write_robot_setting.assert_not_called()
    else:
        await coordinator.async_set_robot_setting(
            "fixture-0", RobotSetting.AUTO_EVACUATION_AREA, requested
        )
        sender.write_robot_setting.assert_called_once_with(
            RobotSetting.AUTO_EVACUATION_AREA, requested
        )
        assert coordinator.data["fixture-0"].telemetry["auto_evacuation_frequency"] == requested


async def test_default_suction_requires_matching_readback_from_the_robot(coordinator, mop_wire):
    sender, reader = mop_wire
    reader.return_value.read.side_effect = [
        settings_reply({"suctionLevel": 3, "swScrub": 0}),
        settings_reply({"suctionLevel": 3, "swScrub": 0}),
        settings_reply({"suctionLevel": 2, "swScrub": 0}),
    ]
    await coordinator.async_set_profile("fixture-0", suction_level=4)

    await coordinator.async_set_robot_setting("fixture-0", RobotSetting.SUCTION, 2)

    sender.write_robot_setting.assert_called_once_with(RobotSetting.SUCTION, 2)
    assert coordinator.data["fixture-0"].telemetry["suction_level"] == 2
    assert coordinator.profile("fixture-0").suction_level == 4


async def test_default_cleaning_setting_readback_is_scoped_and_updates_provider_state(
    coordinator, mop_wire
):
    sender, reader = mop_wire
    read = reader.return_value.read
    read.side_effect = [
        settings_reply({"padWetness": {"padPlate": 2}}),
        ProtocolError("fixture"),
        settings_reply({"padWetness": {"padPlate": 3}}),
    ]
    sender.write_robot_setting.side_effect = OSError()
    coordinator.command_status = {"fixture-0": "confirmed"}

    await coordinator.async_set_robot_setting("fixture-0", RobotSetting.WETNESS, 3)

    assert reader.call_args.args[0].devices == {"fixture-0": "a"}
    sender.write_robot_setting.assert_called_once_with(RobotSetting.WETNESS, 3)
    assert read.call_count == 3
    assert coordinator.data["fixture-0"].telemetry["pad_wetness"] == 3
    assert "pad_wetness" not in coordinator.data["fixture-1"].telemetry
    assert coordinator.command_status == {"fixture-0": "confirmed"}
    assert coordinator._details_due == 0


async def test_default_cleaning_setting_with_current_target_is_a_noop(coordinator, mop_wire):
    sender, reader = mop_wire
    reader.return_value.read.return_value = settings_reply({"swScrub": 0})

    await coordinator.async_set_robot_setting("fixture-0", RobotSetting.SMART_SCRUB, False)

    sender.write_robot_setting.assert_not_called()
    reader.return_value.read.assert_called_once_with(("rw-settings",))
    assert coordinator.data["fixture-0"].telemetry["scrub_setting"] == 0


async def test_setting_readback_does_not_restore_a_removed_device(coordinator, mop_wire):
    sender, reader = mop_wire
    reader.return_value.read.side_effect = [
        settings_reply({"swScrub": 0}),
        settings_reply({"swScrub": 0}),
        settings_reply({"swScrub": 1}),
    ]

    async def remove_robot(_delay):
        del coordinator.data["fixture-0"]

    coordinator._sleep.side_effect = remove_robot
    await coordinator.async_set_robot_setting("fixture-0", RobotSetting.SMART_SCRUB, True)

    sender.write_robot_setting.assert_called_once_with(RobotSetting.SMART_SCRUB, True)
    assert "fixture-0" not in coordinator.data


async def test_default_cleaning_setting_timeout_never_retries_write(coordinator, mop_wire):
    sender, reader = mop_wire
    reader.return_value.read.return_value = settings_reply({"swScrub": 0})

    with pytest.raises(HomeAssistantError) as failure:
        await coordinator.async_set_robot_setting("fixture-0", RobotSetting.SMART_SCRUB, True)

    assert failure.value.translation_key == "robot_setting_unconfirmed"
    sender.write_robot_setting.assert_called_once_with(RobotSetting.SMART_SCRUB, True)
    assert reader.return_value.read.call_count == 5
    assert coordinator._details_due == 0


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("absent", "robot_setting_unavailable"),
        ("failed_poll", "robot_setting_unavailable"),
        ("offline", "robot_setting_unavailable"),
        ("active", "robot_setting_active"),
        ("paused", "robot_setting_active"),
        ("invalid", "unsupported_profile"),
        ("session_capability_lost", "unsupported_profile"),
        ("shadow_rejected", "robot_setting_unavailable"),
    ],
)
async def test_default_cleaning_setting_preflight_blocks_unverified_writes(
    coordinator, mop_wire, case, error
):
    sender, reader = mop_wire
    state = coordinator.data["fixture-0"]
    setting, value = RobotSetting.SMART_SCRUB, True
    if case == "absent":
        del coordinator.data["fixture-0"]
    elif case == "failed_poll":
        coordinator.last_update_success = False
    elif case == "offline":
        coordinator.data["fixture-0"] = replace(state, connected=None)
    elif case in {"active", "paused"}:
        coordinator.data["fixture-0"] = replace(
            state, phase="run" if case == "active" else "stop", cycle="clean"
        )
    elif case == "invalid":
        setting, value = "unverified", True
    elif case == "session_capability_lost":
        sender.capabilities = CleaningCapabilities()
    elif case == "shadow_rejected":
        reader.return_value.read.return_value = []

    with pytest.raises(HomeAssistantError) as failure:
        await coordinator.async_set_robot_setting("fixture-0", setting, value)

    assert failure.value.translation_key == error
    sender.write_robot_setting.assert_not_called()


@pytest.mark.parametrize("failure", [AuthenticationError(), RateLimited(42), ProtocolError("x")])
async def test_default_cleaning_setting_translates_new_session_errors(
    coordinator, mop_wire, failure
):
    sender, _ = mop_wire
    coordinator.client.ensure_session.side_effect = failure
    coordinator._clock = lambda: 100
    expected = (
        ConfigEntryAuthFailed if isinstance(failure, AuthenticationError) else HomeAssistantError
    )

    with pytest.raises(expected):
        await coordinator.async_set_robot_setting("fixture-0", RobotSetting.SMART_SCRUB, True)

    assert coordinator._read_retry_until == (142 if isinstance(failure, RateLimited) else 0)
    sender.write_robot_setting.assert_not_called()


@pytest.mark.parametrize(
    "command,phase,cycle",
    [
        (Command.VACUUM, "run", "clean"),
        (Command.PAUSE, "stop", "clean"),
        (Command.CANCEL, "stop", "none"),
        (Command.DOCK, "charge", "none"),
    ],
)
async def test_confirmed_state_avoids_duplicate_publication(coordinator, command, phase, cycle):
    coordinator.data["fixture-0"] = replace(coordinator.data["fixture-0"], phase=phase, cycle=cycle)
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        await coordinator.async_command("fixture-0", command)
    sender.assert_not_called()
    assert coordinator.command_status["fixture-0"] == "confirmed"


async def test_command_requires_state_after_broker_acknowledgement(coordinator):
    coordinator._details_due = 999

    async def update_state(delay):
        coordinator.data["fixture-0"] = replace(
            coordinator.data["fixture-0"], phase="run", cycle="clean"
        )

    coordinator._sleep.side_effect = update_state
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        await coordinator.async_command("fixture-0", Command.VACUUM)
        sender.return_value.send.assert_called_once_with(Command.VACUUM, CleaningProfile())
    assert coordinator.command_status["fixture-0"] == "confirmed"
    assert coordinator._details_due == 0


@pytest.mark.parametrize("command", [Command.VACUUM, Command.DOCK])
async def test_timeout_retains_uncertainty_and_never_republishes(coordinator, command):
    coordinator.data["fixture-0"] = replace(
        coordinator.data["fixture-0"], phase="stop", cycle="none"
    )
    coordinator._clock = MagicMock(side_effect=[0, 121])
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        with pytest.raises(HomeAssistantError, match="unconfirmed"):
            await coordinator.async_command("fixture-0", command)
        sender.return_value.send.assert_called_once()
    assert coordinator.command_status["fixture-0"] == "unconfirmed"


async def test_disconnect_blocks_publication(coordinator):
    coordinator.data["fixture-0"] = replace(coordinator.data["fixture-0"], connected=False)
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        with pytest.raises(HomeAssistantError, match="unavailable"):
            await coordinator.async_command("fixture-0", Command.VACUUM)
        sender.assert_not_called()


async def test_unconfigured_robot_cannot_request_a_read_or_command(coordinator):
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        with pytest.raises(HomeAssistantError, match="Robot is not configured"):
            await coordinator.async_command("unassociated", Command.VACUUM)
        sender.assert_not_called()
    coordinator.async_refresh.assert_not_awaited()


@pytest.mark.parametrize(
    "command,phase,cycle",
    [(Command.VACUUM, "hmUsrDock", "dock"), (Command.PAUSE, "charge", "none")],
)
async def test_unvalidated_command_context_is_blocked(coordinator, command, phase, cycle):
    coordinator.data["fixture-0"] = replace(coordinator.data["fixture-0"], phase=phase, cycle=cycle)
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        with pytest.raises(HomeAssistantError):
            await coordinator.async_command("fixture-0", command)
        sender.assert_not_called()


@pytest.mark.parametrize("error", [ProtocolError("fixture"), OSError()])
async def test_publish_error_cannot_be_presented_as_physical_success(coordinator, error):
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        sender.return_value.send.side_effect = error
        with pytest.raises(HomeAssistantError, match="unconfirmed"):
            await coordinator.async_command("fixture-0", Command.VACUUM)
    assert coordinator.command_status["fixture-0"] == "unconfirmed"


async def test_authentication_failure_is_distinct_from_transport_failure(coordinator):
    coordinator.client.ensure_session.side_effect = AuthenticationError()
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    coordinator.client.ensure_session.side_effect = OSError()
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_executor_cancellation_waits_for_bounded_worker_cleanup(coordinator, hass):
    future = hass.loop.create_future()
    with patch.object(hass, "async_add_executor_job", return_value=future):
        task = asyncio.create_task(coordinator._executor(lambda: None))
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not future.cancelled()
        future.set_result(None)
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_unload_cancels_confirmation_and_prevents_more_commands(coordinator):
    waiting = asyncio.Event()

    async def wait(delay):
        waiting.set()
        await asyncio.Event().wait()

    coordinator._sleep.side_effect = wait
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender"):
        task = asyncio.create_task(coordinator.async_command("fixture-0", Command.VACUUM))
        await waiting.wait()
        await coordinator.async_close()
        assert task.cancelled()
    assert coordinator.command_status["fixture-0"] == "unconfirmed"
    with pytest.raises(HomeAssistantError):
        await coordinator.async_command("fixture-0", Command.VACUUM)


async def test_commands_wait_only_for_their_own_robot_confirmation(coordinator):
    waiting = asyncio.Event()
    release = asyncio.Event()

    async def finish_transition(delay):
        name = asyncio.current_task().get_name()
        robot_id = "fixture-1" if name == "other" else "fixture-0"
        if name == "first":
            waiting.set()
            await release.wait()
        phase = "stop" if name == "same" else "run"
        coordinator.data[robot_id] = replace(coordinator.data[robot_id], phase=phase, cycle="clean")

    coordinator._sleep.side_effect = finish_transition
    tasks = []
    try:
        with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
            tasks.append(
                asyncio.create_task(
                    coordinator.async_command("fixture-0", Command.VACUUM), name="first"
                )
            )
            await asyncio.wait_for(waiting.wait(), timeout=2)
            same = asyncio.create_task(
                coordinator.async_command("fixture-0", Command.PAUSE), name="same"
            )
            other = asyncio.create_task(
                coordinator.async_command("fixture-1", Command.VACUUM), name="other"
            )
            tasks.extend((same, other))
            await asyncio.wait_for(other, timeout=2)
            assert not same.done()
            assert coordinator.command_status == {"fixture-0": "pending", "fixture-1": "confirmed"}
            assert [call.args[1] for call in sender.call_args_list] == ["fixture-0", "fixture-1"]
            release.set()
            await asyncio.gather(*tasks)
            assert [call.args[1] for call in sender.call_args_list] == [
                "fixture-0",
                "fixture-1",
                "fixture-0",
            ]
            assert coordinator.command_status == {
                "fixture-0": "confirmed",
                "fixture-1": "confirmed",
            }
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_two_commands_share_an_inflight_read_even_if_one_caller_cancels(coordinator):
    started = asyncio.Event()
    release = asyncio.Event()

    async def refresh():
        started.set()
        await release.wait()

    coordinator.async_refresh.side_effect = refresh
    first = asyncio.create_task(coordinator.async_command("fixture-0", Command.DOCK))
    await asyncio.wait_for(started.wait(), timeout=2)
    second = asyncio.create_task(coordinator.async_command("fixture-1", Command.DOCK))
    try:
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        await asyncio.wait_for(second, timeout=2)
        assert coordinator.async_refresh.await_count == 1
        assert coordinator.command_status == {"fixture-1": "confirmed"}
    finally:
        await coordinator.async_close()


async def test_unload_cancels_a_pending_shared_read(coordinator):
    started = asyncio.Event()

    async def refresh():
        started.set()
        await asyncio.Event().wait()

    coordinator.async_refresh.side_effect = refresh
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        pending = asyncio.create_task(coordinator.async_command("fixture-0", Command.VACUUM))
        await asyncio.wait_for(started.wait(), timeout=2)
        await coordinator.async_close()
        sender.assert_not_called()
    assert pending.cancelled()
    assert coordinator._command_refresh_task.cancelled()


async def test_read_composition_keeps_robots_isolated_and_skips_old_models(
    coordinator, cloud_session
):
    from custom_components.roomba_home.core.mqtt import ShadowReply

    requested = []

    class Reader:
        def __init__(self, profile):
            self.profile = profile

        def read(self, shadows, *, allow_partial=False):
            assert allow_partial is True
            requested.extend(self.profile.devices)
            replies = []
            for key in self.profile.devices:
                battery = int(key.rsplit("-", 1)[1]) * 10
                for shadow in shadows:
                    reported = (
                        {"connected": True}
                        if shadow == "rw-constatus"
                        else {
                            "batPct": battery,
                            "cleanMissionStatus": {"phase": "charge", "cycle": "none"},
                        }
                    )
                    replies.append(
                        ShadowReply(key, shadow, True, {"state": {"reported": reported}})
                    )
            return replies

    with patch("custom_components.roomba_home.coordinator.MqttShadowReader", Reader):
        documents = coordinator._read(cloud_session)
    from custom_components.roomba_home.core.state import project_state

    result = {
        key: project_state(key, cloud_session.raw["robots"][key], shadows)
        for key, shadows in documents.items()
    }
    assert set(requested) == {"fixture-0", "fixture-1", "fixture-2"}
    assert [result[f"fixture-{i}"].battery for i in range(3)] == [0, 10, 20]


async def test_command_auth_error_requests_reauthentication_without_claiming_success(coordinator):
    coordinator.client.ensure_session.side_effect = AuthenticationError()
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator.async_command("fixture-0", Command.VACUUM)
    assert coordinator.command_status["fixture-0"] == "unconfirmed"


async def test_closed_coordinator_does_not_read_again(coordinator):
    await coordinator.async_close()
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_rate_limit_delay_is_passed_to_home_assistant(coordinator):
    coordinator.client.ensure_session.side_effect = RateLimited(300)
    with pytest.raises(UpdateFailed) as error:
        await coordinator._async_update_data()
    assert error.value.retry_after == 300


async def test_manual_refresh_and_commands_do_not_bypass_provider_retry_after(coordinator):
    coordinator.async_refresh = RoombaCoordinator.async_refresh.__get__(coordinator)
    coordinator._clock = lambda: 200
    coordinator.client.ensure_session.side_effect = RateLimited(300)
    with pytest.raises(UpdateFailed, match="rate limited"):
        await coordinator._async_update_data()
    coordinator._clock = lambda: 250
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        with pytest.raises(HomeAssistantError, match="unavailable"):
            await coordinator.async_command("fixture-1", Command.VACUUM)
        sender.assert_not_called()
    await coordinator.async_refresh()
    assert coordinator.client.ensure_session.await_count == 1
    assert coordinator.last_exception.retry_after == 250


async def test_failed_confirmation_read_does_not_hammer_the_service(coordinator):
    async def refresh():
        if coordinator.command_status.get("fixture-0") == "pending":
            coordinator.last_update_success = False

    coordinator.async_refresh.side_effect = refresh
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        with pytest.raises(HomeAssistantError, match="unconfirmed"):
            await coordinator.async_command("fixture-0", Command.VACUUM)
        sender.return_value.send.assert_called_once()
    assert coordinator.async_refresh.await_count == 2


async def test_command_confirms_after_a_refresh_with_missing_robot_connectivity(coordinator):
    original = coordinator.data["fixture-0"]

    async def refresh():
        if coordinator.async_refresh.await_count == 2:
            coordinator.data["fixture-0"] = replace(original, connected=None)
        elif coordinator.async_refresh.await_count == 3:
            coordinator.data["fixture-0"] = replace(original, phase="run", cycle="clean")

    coordinator.async_refresh.side_effect = refresh
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        await coordinator.async_command("fixture-0", Command.VACUUM)
        sender.return_value.send.assert_called_once_with(Command.VACUUM, CleaningProfile())
    assert coordinator.last_update_success
    assert coordinator.async_refresh.await_count == 3
    assert coordinator.command_status["fixture-0"] == "confirmed"


async def test_unselected_token_groups_and_rejected_shadows_are_not_projected(
    coordinator, cloud_session
):
    from custom_components.roomba_home.core.mqtt import ShadowReply

    coordinator.selected = frozenset({"fixture-0"})
    with patch("custom_components.roomba_home.coordinator.MqttShadowReader") as reader:
        reader.return_value.read.return_value = [
            ShadowReply("fixture-0", "ro-sensor", False, {"code": 404})
        ]
        assert coordinator._read(cloud_session) == {}
    assert reader.call_count == 1


async def test_invalid_token_group_does_not_hide_other_robot_updates(coordinator, cloud_session):
    from custom_components.roomba_home.core.mqtt import ShadowReply

    with patch("custom_components.roomba_home.coordinator.MqttShadowReader") as reader:
        reader.return_value.read.side_effect = [
            ProtocolError("unavailable group"),
            [ShadowReply("fixture-2", "rw-constatus", True, {"connected": True})],
        ]
        result = coordinator._read(cloud_session)
    assert result == {"fixture-2": {"rw-constatus": {"connected": True}}}


async def test_all_invalid_token_groups_surface_the_transport_failure(coordinator, cloud_session):
    with patch("custom_components.roomba_home.coordinator.MqttShadowReader") as reader:
        reader.return_value.read.side_effect = OSError("offline groups")
        with pytest.raises(OSError, match="offline groups"):
            coordinator._read(cloud_session)
