"""Native Home Assistant actions for cloud schedule time changes."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
)
from probatio import Invalid

from custom_components.roomba_home.const import DOMAIN
from custom_components.roomba_home.coordinator import RoombaCoordinator
from custom_components.roomba_home.core.cleaning import CleaningMode, CleaningProfile
from custom_components.roomba_home.core.errors import (
    AuthenticationError,
    ProtocolError,
    RateLimited,
    ScheduleNotEditable,
    ScheduleUpdateUnconfirmed,
)
from custom_components.roomba_home.core.maps import (
    AreaTarget,
    CleaningRegion,
    PersistentMap,
    RegionKind,
)

TEST_SCHEDULE = {
    "id": "fixture.group:fixture.item",
    "time": "08:30",
    "weekdays": (3, 5),
    "enabled": False,
}
CHANGE = {
    "entity_id": "vacuum.robot_0",
    "schedule_id": TEST_SCHEDULE["id"],
    "weekdays": [5, 3],
    "time": "08:30:00",
}
AREA = CleaningRegion("fixture.room", RegionKind.ROOM, "Example room")
MAP = PersistentMap("fixture.map", "fixture.version", "Example map", (AREA,))
CREATE = {
    "entity_id": "vacuum.robot_0",
    "name": "Example schedule",
    "weekdays": [3, 5],
    "time": "08:30:00",
    "regions": [
        {
            "id": AREA.segment_id(MAP.map_id),
            "mode": "vacuum_then_mop",
            "suction_level": 1,
            "wetness_level": 2,
        }
    ],
}


@pytest.fixture
async def account(hass, entry, robot_states):
    state = robot_states["fixture-0"]
    robot_states["fixture-0"] = replace(
        state, capabilities=replace(state.capabilities, schedules=True, persistent_maps=True)
    )
    with patch.object(
        RoombaCoordinator, "_async_update_data", AsyncMock(return_value=robot_states)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        result = entry.runtime_data
        result.client.list_weekly_schedules = AsyncMock(return_value=[TEST_SCHEDULE])
        result.client.update_weekly_schedule = AsyncMock(return_value=TEST_SCHEDULE)
        result.client.set_weekly_schedule_enabled = AsyncMock(return_value=TEST_SCHEDULE)
        result.client.create_weekly_schedule = AsyncMock(return_value=TEST_SCHEDULE)
        result.client.remove_weekly_schedule = AsyncMock(
            return_value={"id": TEST_SCHEDULE["id"], "removed": True}
        )
        result.client.maps = AsyncMock(return_value=(MAP,))
        result._maps = {"fixture-0": (MAP,)}
        result.async_update_listeners()
        await hass.async_block_till_done()
        result.async_request_refresh = AsyncMock()
        yield result
        await hass.config_entries.async_unload(entry.entry_id)


async def test_schedule_actions_call_the_target_robot_and_return_readback(hass, account):
    result = await hass.services.async_call(
        DOMAIN,
        "list_cleaning_schedules",
        {"entity_id": "vacuum.robot_0"},
        blocking=True,
        return_response=True,
    )
    assert result == {"vacuum.robot_0": {"schedules": [TEST_SCHEDULE]}}
    account.client.list_weekly_schedules.assert_awaited_once_with("fixture-0")
    result = await hass.services.async_call(
        DOMAIN, "update_cleaning_schedule", CHANGE, blocking=True, return_response=True
    )
    assert result == {"vacuum.robot_0": TEST_SCHEDULE}
    account.client.update_weekly_schedule.assert_awaited_once_with(
        "fixture-0", TEST_SCHEDULE["id"], [5, 3], "08:30:00"
    )
    account.async_request_refresh.assert_awaited_once()


async def test_weekly_activation_is_a_native_action_without_rescheduling(hass, account):
    target = {"entity_id": "vacuum.robot_0", "schedule_id": TEST_SCHEDULE["id"], "enabled": False}
    result = await hass.services.async_call(
        DOMAIN, "set_cleaning_schedule_enabled", target, blocking=True, return_response=True
    )
    assert result == {"vacuum.robot_0": TEST_SCHEDULE}
    account.client.set_weekly_schedule_enabled.assert_awaited_once_with(
        "fixture-0", TEST_SCHEDULE["id"], False
    )
    account.client.update_weekly_schedule.assert_not_awaited()


async def test_creating_a_schedule_uses_current_rooms_and_typed_profiles(hass, account):
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        result = await hass.services.async_call(
            DOMAIN, "create_cleaning_schedule", CREATE, blocking=True, return_response=True
        )
        sender.assert_not_called()
    assert result == {"vacuum.robot_0": TEST_SCHEDULE}
    account.client.maps.assert_awaited_once_with("fixture-0")
    account.client.create_weekly_schedule.assert_awaited_once_with(
        "fixture-0",
        "Example schedule",
        [3, 5],
        "08:30:00",
        AreaTarget(
            MAP.map_id,
            MAP.version_id,
            (AREA,),
            (CleaningProfile(CleaningMode.VACUUM_THEN_MOP, suction_level=1, wetness_level=2),),
        ),
    )


@pytest.mark.parametrize(
    "region,reason",
    [
        ({"id": "unknown:rid:wrong"}, "unsupported_areas"),
        (
            {"id": AREA.segment_id(MAP.map_id), "mode": "mop", "wetness_level": 4},
            "unsupported_profile",
        ),
    ],
)
async def test_creating_a_schedule_rejects_stale_room_or_unsupported_preferences(
    hass, account, region, reason
):
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            DOMAIN, "create_cleaning_schedule", CREATE | {"regions": [region]}, blocking=True
        )
    assert error.value.translation_key == reason
    account.client.create_weekly_schedule.assert_not_awaited()


async def test_removal_uses_the_selected_robot_schedule(hass, account):
    data = {"entity_id": "vacuum.robot_0", "schedule_id": TEST_SCHEDULE["id"]}
    result = await hass.services.async_call(
        DOMAIN, "remove_cleaning_schedule", data, blocking=True, return_response=True
    )
    assert result == {"vacuum.robot_0": {"id": TEST_SCHEDULE["id"], "removed": True}}
    account.client.remove_weekly_schedule.assert_awaited_once_with("fixture-0", TEST_SCHEDULE["id"])


@pytest.mark.parametrize(
    "change", [{"weekdays": [5, 5]}, {"time": "08:30:01"}, {"schedule_id": "../../other"}]
)
async def test_schedule_actions_reject_invalid_calls_before_contacting_provider(
    hass, account, change
):
    with pytest.raises(Invalid):
        await hass.services.async_call(
            DOMAIN, "update_cleaning_schedule", CHANGE | change, blocking=True
        )
    account.client.update_weekly_schedule.assert_not_called()


async def test_schedule_action_is_unavailable_for_other_robots(hass, account):
    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            DOMAIN,
            "list_cleaning_schedules",
            {"entity_id": "vacuum.robot_1"},
            blocking=True,
            return_response=True,
        )
    assert caught.value.translation_key == "schedule_not_editable"
    assert not account.client.list_weekly_schedules.called
    with pytest.raises(HomeAssistantError) as caught:
        await account.async_schedule_action("not-configured")
    assert caught.value.translation_key == "not_configured"


@pytest.mark.parametrize(
    "failure,key",
    [
        (RateLimited(35), "schedule_rate_limited"),
        (ScheduleNotEditable(), "schedule_not_editable"),
        (ScheduleUpdateUnconfirmed(), "schedule_unconfirmed"),
        (ProtocolError(), "schedule_unavailable"),
    ],
)
async def test_schedule_failures_are_safe_and_do_not_change_the_ui_snapshot(
    hass, account, failure, key
):
    account._clock = lambda: 100
    account.client.update_weekly_schedule.side_effect = failure
    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(DOMAIN, "update_cleaning_schedule", CHANGE, blocking=True)
    assert caught.value.translation_key == key
    account.async_request_refresh.assert_not_awaited()
    if isinstance(failure, RateLimited):
        assert account._schedules_due == account._schedules_retry_until == 135
        with pytest.raises(HomeAssistantError) as caught:
            await account.async_schedule_action("fixture-0")
        assert caught.value.translation_key == "schedule_rate_limited"
        assert not account.client.list_weekly_schedules.called


async def test_expired_login_flows_to_ha_reauth(account):
    account.client.list_weekly_schedules.side_effect = AuthenticationError()
    with pytest.raises(ConfigEntryAuthFailed):
        await account.async_schedule_action("fixture-0")
