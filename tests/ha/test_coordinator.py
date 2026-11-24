import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.roomba_home.coordinator import RoombaCoordinator
from custom_components.roomba_home.core.capabilities import DockCapabilities
from custom_components.roomba_home.core.cleaning import CleaningCapabilities, CleaningProfile
from custom_components.roomba_home.core.cleaning_protocol import CleaningSetting
from custom_components.roomba_home.core.commands import Command
from custom_components.roomba_home.core.errors import (
    AuthenticationError,
    ProtocolError,
    RateLimited,
)
from custom_components.roomba_home.core.mqtt import MqttProfile, ShadowReply


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
        await coordinator.async_set_cleaning_setting(
            "fixture-0", CleaningSetting.AUTO_EVACUATION_AREA, 50
        )
    assert error.value.translation_key == "unsupported_dock_action"
    coordinator.client.ensure_session.assert_not_awaited()
    sender.write_cleaning_setting.assert_not_called()


@pytest.mark.parametrize("observed", [4, 25])
async def test_auto_evacuation_area_never_changes_a_different_frequency_scheme(
    coordinator, mop_wire, observed
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
        settings_reply({"autoevacFreq": 50}),
    ]
    if observed == 4:
        with pytest.raises(HomeAssistantError) as error:
            await coordinator.async_set_cleaning_setting(
                "fixture-0", CleaningSetting.AUTO_EVACUATION_AREA, 50
            )
        assert error.value.translation_key == "robot_setting_unavailable"
        sender.write_cleaning_setting.assert_not_called()
    else:
        await coordinator.async_set_cleaning_setting(
            "fixture-0", CleaningSetting.AUTO_EVACUATION_AREA, 50
        )
        sender.write_cleaning_setting.assert_called_once_with(
            CleaningSetting.AUTO_EVACUATION_AREA, 50
        )
        assert coordinator.data["fixture-0"].telemetry["auto_evacuation_frequency"] == 50


async def test_default_suction_requires_matching_readback_from_the_robot(coordinator, mop_wire):
    sender, reader = mop_wire
    reader.return_value.read.side_effect = [
        settings_reply({"suctionLevel": 3, "swScrub": 0}),
        settings_reply({"suctionLevel": 3, "swScrub": 0}),
        settings_reply({"suctionLevel": 2, "swScrub": 0}),
    ]
    await coordinator.async_set_profile("fixture-0", suction_level=4)

    await coordinator.async_set_cleaning_setting("fixture-0", CleaningSetting.SUCTION, 2)

    sender.write_cleaning_setting.assert_called_once_with(CleaningSetting.SUCTION, 2)
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
    sender.write_cleaning_setting.side_effect = OSError()
    coordinator.command_status = {"fixture-0": "confirmed"}

    await coordinator.async_set_cleaning_setting("fixture-0", CleaningSetting.WETNESS, 3)

    assert reader.call_args.args[0].devices == {"fixture-0": "a"}
    sender.write_cleaning_setting.assert_called_once_with(CleaningSetting.WETNESS, 3)
    assert read.call_count == 3
    assert coordinator.data["fixture-0"].telemetry["pad_wetness"] == 3
    assert "pad_wetness" not in coordinator.data["fixture-1"].telemetry
    assert coordinator.command_status == {"fixture-0": "confirmed"}
    assert coordinator._details_due == 0


async def test_default_cleaning_setting_with_current_target_is_a_noop(coordinator, mop_wire):
    sender, reader = mop_wire
    reader.return_value.read.return_value = settings_reply({"swScrub": 0})

    await coordinator.async_set_cleaning_setting("fixture-0", CleaningSetting.SMART_SCRUB, False)

    sender.write_cleaning_setting.assert_not_called()
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
    await coordinator.async_set_cleaning_setting("fixture-0", CleaningSetting.SMART_SCRUB, True)

    sender.write_cleaning_setting.assert_called_once_with(CleaningSetting.SMART_SCRUB, True)
    assert "fixture-0" not in coordinator.data


async def test_default_cleaning_setting_timeout_never_retries_write(coordinator, mop_wire):
    sender, reader = mop_wire
    reader.return_value.read.return_value = settings_reply({"swScrub": 0})

    with pytest.raises(HomeAssistantError) as failure:
        await coordinator.async_set_cleaning_setting("fixture-0", CleaningSetting.SMART_SCRUB, True)

    assert failure.value.translation_key == "robot_setting_unconfirmed"
    sender.write_cleaning_setting.assert_called_once_with(CleaningSetting.SMART_SCRUB, True)
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
    setting, value = CleaningSetting.SMART_SCRUB, True
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
        await coordinator.async_set_cleaning_setting("fixture-0", setting, value)

    assert failure.value.translation_key == error
    sender.write_cleaning_setting.assert_not_called()


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
        await coordinator.async_set_cleaning_setting("fixture-0", CleaningSetting.SMART_SCRUB, True)

    assert coordinator._read_retry_until == (142 if isinstance(failure, RateLimited) else 0)
    sender.write_cleaning_setting.assert_not_called()


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
