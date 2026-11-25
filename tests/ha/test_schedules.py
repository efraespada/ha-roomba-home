"""Native Home Assistant actions for cloud schedule time changes."""

from dataclasses import replace
from datetime import UTC, datetime
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
    RoutineNotEditable,
    RoutineUpdateUnconfirmed,
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
        result.client.list_cleaning_schedules = AsyncMock(return_value=[TEST_SCHEDULE])
        result.client.update_cleaning_schedule = AsyncMock(return_value=TEST_SCHEDULE)
        result.client.set_cleaning_schedule_enabled = AsyncMock(return_value=TEST_SCHEDULE)
        result.client.create_cleaning_schedule = AsyncMock(return_value=TEST_SCHEDULE)
        result.client.remove_cleaning_schedule = AsyncMock(
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
    account.client.list_cleaning_schedules.assert_awaited_once_with("fixture-0")
    result = await hass.services.async_call(
        DOMAIN, "update_cleaning_schedule", CHANGE, blocking=True, return_response=True
    )
    assert result == {"vacuum.robot_0": TEST_SCHEDULE}
    account.client.update_cleaning_schedule.assert_awaited_once_with(
        "fixture-0", TEST_SCHEDULE["id"], [5, 3], "08:30:00", frequency="weekly"
    )
    account.async_request_refresh.assert_awaited_once()


async def test_weekly_activation_is_a_native_action_without_rescheduling(hass, account):
    target = {"entity_id": "vacuum.robot_0", "schedule_id": TEST_SCHEDULE["id"], "enabled": False}
    result = await hass.services.async_call(
        DOMAIN, "set_cleaning_schedule_enabled", target, blocking=True, return_response=True
    )
    assert result == {"vacuum.robot_0": TEST_SCHEDULE}
    account.client.set_cleaning_schedule_enabled.assert_awaited_once_with(
        "fixture-0", TEST_SCHEDULE["id"], False
    )
    account.client.update_cleaning_schedule.assert_not_awaited()


async def test_creating_a_schedule_uses_current_rooms_and_typed_profiles(hass, account):
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        result = await hass.services.async_call(
            DOMAIN, "create_cleaning_schedule", CREATE, blocking=True, return_response=True
        )
        sender.assert_not_called()
    assert result == {"vacuum.robot_0": TEST_SCHEDULE}
    account.client.maps.assert_awaited_once_with("fixture-0")
    account.client.create_cleaning_schedule.assert_awaited_once_with(
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
        frequency="weekly",
    )


async def test_schedule_preferences_can_change_without_recomputing_start(hass, account):
    target = {"entity_id": "vacuum.robot_0", "schedule_id": TEST_SCHEDULE["id"]}
    selection = {"id": AREA.segment_id(MAP.map_id), "mode": "mop", "wetness_level": 1}
    floor = {"map_id": MAP.map_id, "version": MAP.version_id, "inventory_id": MAP.selection_id}
    with patch("custom_components.roomba_home.coordinator.MqttCommandSender") as sender:
        await hass.services.async_call(
            DOMAIN,
            "update_cleaning_schedule",
            target | {"name": "Mop at the same time", "regions": [selection], "floor": floor},
            blocking=True,
        )
        sender.assert_not_called()
    account.client.update_cleaning_schedule.assert_awaited_once_with(
        "fixture-0",
        TEST_SCHEDULE["id"],
        name="Mop at the same time",
        target=AreaTarget(
            MAP.map_id,
            MAP.version_id,
            (AREA,),
            (CleaningProfile(CleaningMode.MOP, wetness_level=1),),
        ),
    )
    account.client.update_cleaning_schedule.reset_mock()
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            DOMAIN,
            "update_cleaning_schedule",
            target | {"regions": [selection], "floor": floor | {"version": "stale"}},
            blocking=True,
        )
    assert error.value.translation_key == "map_changed"
    account.client.update_cleaning_schedule.assert_not_called()


@pytest.mark.parametrize("change", [{}, {"frequency": "once"}, {"weekdays": [3]}])
async def test_schedule_edit_without_time_requires_name_or_areas(hass, account, change):
    target = {"entity_id": "vacuum.robot_0", "schedule_id": TEST_SCHEDULE["id"]}
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            DOMAIN, "update_cleaning_schedule", target | change, blocking=True
        )
    assert error.value.translation_key == "schedule_not_editable"
    account.client.update_cleaning_schedule.assert_not_called()


async def test_schedule_create_checks_the_reviewed_floor_before_posting(hass, account):
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            DOMAIN,
            "create_cleaning_schedule",
            CREATE | {"floor": {"map_id": MAP.map_id, "version": "stale"}},
            blocking=True,
        )
    assert error.value.translation_key == "map_changed"
    account.client.create_cleaning_schedule.assert_not_called()


@pytest.mark.parametrize(
    ("service", "details", "days"),
    [
        ("create_cleaning_schedule", CREATE, [4]),
        ("update_cleaning_schedule", CHANGE, [4]),
    ],
)
async def test_once_schedule_uses_the_robot_local_date(hass, account, service, details, days):
    robot = account.data["fixture-0"]
    account.data["fixture-0"] = replace(
        robot, telemetry=robot.telemetry | {"robot_timezone": "Europe/Madrid"}
    )
    payload = {key: value for key, value in details.items() if key != "weekdays"}
    payload["frequency"] = "once"
    now = datetime(2026, 11, 25, 8, tzinfo=UTC)
    with patch("custom_components.roomba_home.coordinator.dt_util.utcnow", return_value=now):
        await hass.services.async_call(
            DOMAIN, service, payload, blocking=True, return_response=True
        )
    if service == "create_cleaning_schedule":
        call = account.client.create_cleaning_schedule.await_args
        assert call.args[:4] == ("fixture-0", "Example schedule", days, details["time"])
        assert call.args[-1].regions == (AREA,)
    else:
        call = account.client.update_cleaning_schedule.await_args
        assert call.args == ("fixture-0", TEST_SCHEDULE["id"], days, details["time"])
    assert call.kwargs == {"frequency": "once"}


@pytest.mark.parametrize(
    ("frequency", "day_input", "time_zone", "error"),
    [
        ("weekly", False, None, "schedule_not_editable"),
        ("once", True, None, "schedule_not_editable"),
        ("once", False, None, "schedule_timezone_unavailable"),
        ("once", False, "Invalid/TimeZone", "schedule_timezone_unavailable"),
    ],
)
async def test_invalid_schedule_dates_do_not_modify_the_provider(
    hass, account, frequency, day_input, time_zone, error
):
    robot = account.data["fixture-0"]
    account.data["fixture-0"] = replace(
        robot, telemetry=robot.telemetry | {"robot_timezone": time_zone}
    )
    payload = dict(CHANGE, frequency=frequency)
    if not day_input:
        del payload["weekdays"]
    with pytest.raises(HomeAssistantError) as failure:
        await hass.services.async_call(DOMAIN, "update_cleaning_schedule", payload, blocking=True)
    assert failure.value.translation_key == error
    account.client.update_cleaning_schedule.assert_not_awaited()


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
    account.client.create_cleaning_schedule.assert_not_awaited()


async def test_removal_uses_the_selected_robot_schedule(hass, account):
    data = {"entity_id": "vacuum.robot_0", "schedule_id": TEST_SCHEDULE["id"]}
    result = await hass.services.async_call(
        DOMAIN, "remove_cleaning_schedule", data, blocking=True, return_response=True
    )
    assert result == {"vacuum.robot_0": {"id": TEST_SCHEDULE["id"], "removed": True}}
    account.client.remove_cleaning_schedule.assert_awaited_once_with(
        "fixture-0", TEST_SCHEDULE["id"]
    )


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
    account.client.update_cleaning_schedule.assert_not_called()


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
    assert not account.client.list_cleaning_schedules.called
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
    account.client.update_cleaning_schedule.side_effect = failure
    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(DOMAIN, "update_cleaning_schedule", CHANGE, blocking=True)
    assert caught.value.translation_key == key
    account.async_request_refresh.assert_not_awaited()
    if isinstance(failure, RateLimited):
        assert account._schedules_due == account._schedules_retry_until == 135
        with pytest.raises(HomeAssistantError) as caught:
            await account.async_schedule_action("fixture-0")
        assert caught.value.translation_key == "schedule_rate_limited"
        assert not account.client.list_cleaning_schedules.called


async def test_expired_login_flows_to_ha_reauth(account):
    account.client.list_cleaning_schedules.side_effect = AuthenticationError()
    with pytest.raises(ConfigEntryAuthFailed):
        await account.async_schedule_action("fixture-0")


@pytest.mark.parametrize("reviewed", [True, False])
async def test_draft_estimate_action_reads_reported_defaults_and_never_starts_robot(
    hass, account, reviewed
):
    robot = "fixture-0"
    state = account.data[robot]
    account.async_set_updated_data(
        {
            **account.data,
            robot: replace(
                state, telemetry={**state.telemetry, "suction_level": 3, "two_pass": False}
            ),
        }
    )
    account._maps_available[robot] = True
    area = AREA.segment_id(MAP.map_id)
    account.client.cleaning_time_estimates = AsyncMock(
        return_value={
            "regions": [
                {
                    "id": area,
                    "estimates": [
                        {
                            "mode": "vacuum",
                            "suction_level": 3,
                            "two_pass": False,
                            "duration_seconds": 360,
                        },
                        {
                            "mode": "vacuum",
                            "suction_level": 3,
                            "two_pass": True,
                            "duration_seconds": 720,
                        },
                        {
                            "mode": "vacuum",
                            "suction_level": 1,
                            "two_pass": False,
                            "duration_seconds": 380,
                        },
                    ],
                }
            ]
        }
    )
    data = {"entity_id": "vacuum.robot_0", "regions": [{"id": area, "suction_level": None}]}
    if reviewed:
        data["floor"] = {
            "map_id": MAP.map_id,
            "version": MAP.version_id,
            "inventory_id": MAP.inventory_id,
        }
    with patch.object(account, "async_command", AsyncMock()) as command:
        response = await hass.services.async_call(
            DOMAIN, "estimate_cleaning_routine", data, blocking=True, return_response=True
        )
        command.assert_not_awaited()
    assert response["vacuum.robot_0"] == {
        "map_id": MAP.map_id,
        "version": MAP.version_id,
        "duration_seconds": 360,
        "partial_duration_seconds": None,
        "areas": [{"id": area, "duration_seconds": 360, "ambiguous": False}],
    }
    assert account.client.maps.await_count == 2


async def test_routine_actions_use_the_same_associated_robot_and_never_start_it(hass, account):
    robot = "fixture-0"
    routine = {"id": "1" * 32, "name": "Example routine", "regions": [], "editable": True}
    account.client.list_cleaning_routines = AsyncMock(return_value=[routine])
    account.client.create_cleaning_routine = AsyncMock(return_value=routine)
    account.client.update_cleaning_routine = AsyncMock(return_value=routine)
    account.client.remove_cleaning_routine = AsyncMock(return_value={"removed": True})
    account.async_command = AsyncMock()

    async def action(service, **data):
        return await hass.services.async_call(
            DOMAIN,
            service,
            {"entity_id": "vacuum.robot_0", **data},
            blocking=True,
            return_response=True,
        )

    assert (await action("list_cleaning_routines"))["vacuum.robot_0"] == {"routines": [routine]}
    assert (
        await action("create_cleaning_routine", name=routine["name"], regions=CREATE["regions"])
    )["vacuum.robot_0"] == routine
    expected = AreaTarget(
        MAP.map_id,
        MAP.version_id,
        (AREA,),
        (CleaningProfile(CleaningMode.VACUUM_THEN_MOP, suction_level=1, wetness_level=2),),
    )
    account.client.create_cleaning_routine.assert_awaited_once_with(
        robot, routine["name"], expected
    )
    await action("update_cleaning_routine", routine_id=routine["id"], name="Renamed")
    account.client.update_cleaning_routine.assert_awaited_once_with(
        robot, routine["id"], "Renamed", None
    )
    await action("update_cleaning_routine", routine_id=routine["id"], regions=CREATE["regions"])
    account.client.update_cleaning_routine.assert_awaited_with(robot, routine["id"], None, expected)
    await action(
        "update_cleaning_routine",
        routine_id=routine["id"],
        regions=[{"id": AREA.segment_id(MAP.map_id), "mode": "vacuum", "suction_level": None}],
    )
    assert (
        account.client.update_cleaning_routine.await_args.args[-1].profiles[0].suction_level is None
    )
    assert (await action("remove_cleaning_routine", routine_id=routine["id"]))[
        "vacuum.robot_0"
    ] == {"removed": True}
    account.client.remove_cleaning_routine.assert_awaited_once_with(robot, routine["id"])
    account.async_command.assert_not_awaited()

    with pytest.raises(HomeAssistantError) as error:
        await action("update_cleaning_routine", routine_id=routine["id"])
    assert error.value.translation_key == "routine_not_editable"
    with pytest.raises(HomeAssistantError) as error:
        await action(
            "create_cleaning_routine",
            name="Invalid",
            regions=[CREATE["regions"][0] | {"wetness_level": 99}],
        )
    assert error.value.translation_key == "unsupported_profile"


@pytest.mark.parametrize(
    ("failure", "exception", "key"),
    [
        (AuthenticationError(), ConfigEntryAuthFailed, None),
        (RateLimited(40), HomeAssistantError, "routine_rate_limited"),
        (RoutineNotEditable(), HomeAssistantError, "routine_not_editable"),
        (RoutineUpdateUnconfirmed(), HomeAssistantError, "routine_unconfirmed"),
        (ProtocolError(), HomeAssistantError, "routine_unavailable"),
    ],
)
async def test_routine_service_reports_classified_failures(account, failure, exception, key):
    account._clock = lambda: 100
    account.client.list_cleaning_routines = AsyncMock(side_effect=failure)
    with pytest.raises(exception) as caught:
        await account.async_list_cleaning_routines("fixture-0")
    if key:
        assert caught.value.translation_key == key
    if isinstance(failure, RateLimited):
        assert account._routines_retry_until == 140
        with pytest.raises(HomeAssistantError) as caught:
            await account.async_list_cleaning_routines("fixture-0")
        assert caught.value.translation_key == key
        account.client.list_cleaning_routines.assert_awaited_once()


async def test_unconfigured_robot_cannot_list_routines(account):
    with pytest.raises(HomeAssistantError) as caught:
        await account.async_list_cleaning_routines("foreign")
    assert caught.value.translation_key == "not_configured"
