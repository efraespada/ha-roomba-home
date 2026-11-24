from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.image import async_get_image
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry

from custom_components.roomba_home.const import CONF_SHOW_MAPS, DOMAIN
from custom_components.roomba_home.coordinator import RoombaCoordinator
from custom_components.roomba_home.core.history import RoomResult
from custom_components.roomba_home.core.live_maps import MissionTimeline, position_batch
from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind

MAP = PersistentMap(
    "map-a", "version.42", "Example floor", (CleaningRegion("room-a", RegionKind.ROOM, "Office"),)
)


async def test_live_floor_image_and_room_are_private_opt_in_and_expire(
    hass, entry, robot_states, make_point_bundle, cloud_session
):
    hass.config_entries.async_update_entry(entry, options={CONF_SHOW_MAPS: True})
    robot_id = "fixture-0"
    now = datetime.now(UTC)
    start = now - timedelta(minutes=1)
    robot = robot_states[robot_id]
    active = replace(
        robot,
        phase="run",
        cycle="clean",
        capabilities=replace(robot.capabilities, persistent_maps=True),
        telemetry={"mission_started": start, "maps_available": True},
    )
    topic = "fixture-irbt/things/fixture-0/livemap/update"
    cloud_session.discovery["deployments"]["fixture"]["irbtTopics"] = "fixture-irbt"

    async def first_refresh(account):
        account._maps = {robot_id: (MAP,)}
        account._maps_available = {robot_id: True}
        account.client.map_geometry = AsyncMock(return_value=make_point_bundle())
        account.client.live_map_topic = AsyncMock(return_value=topic)
        return {robot_id: active}

    with patch.object(RoombaCoordinator, "_async_update_data", first_refresh):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    account = entry.runtime_data
    reg = entity_registry.async_get(hass)
    key = f"{entry.unique_id}_{robot_id}_floor_plan_{sha256(MAP.map_id.encode()).hexdigest()}"
    image_id = reg.async_get_entity_id("image", DOMAIN, key)
    still = await async_get_image(hass, image_id)
    assert still.content_type == "image/png"
    assert still.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert (await async_get_image(hass, image_id)).content == still.content
    account.client.map_geometry.assert_awaited_once_with(MAP.map_id, MAP.version_id)
    assert await account._live_topics(cloud_session) == {robot_id: topic}
    assert await account._live_topics(cloud_session) == {robot_id: topic}
    account.client.live_map_topic.assert_awaited_once_with(robot_id)

    timestamp = int(now.timestamp())
    position = position_batch(
        {
            "timestamp": timestamp,
            "update_expire_ts": timestamp + 30,
            "pos_update": {"cur_path": [30, 2, 1, 0.0, 2, 3, 1, 1.0, 2, timestamp]},
        },
        timestamp,
    )
    active_states = {robot_id: active}
    await account._update_live_paths(active_states, {robot_id: [position]}, now)
    account.async_set_updated_data(active_states)
    await hass.async_block_till_done()

    room_id = reg.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.unique_id}_{robot_id}_current_room"
    )
    timestamp_id = reg.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.unique_id}_{robot_id}_position_updated"
    )
    assert hass.states.get(room_id).state == "Office"
    assert hass.states.get(timestamp_id).state == datetime.fromtimestamp(timestamp, UTC).isoformat()
    with_path = await async_get_image(hass, image_id)
    assert with_path.content != still.content
    assert hass.states.get(image_id).state != "unknown"

    idle = {robot_id: replace(active, phase="charge", cycle="none")}
    await account._update_live_paths(idle, {}, now)
    account.async_set_updated_data(idle)
    assert hass.states.get(room_id).state == "unknown"
    assert (await async_get_image(hass, image_id)).content == still.content

    await account._update_live_paths(active_states, {robot_id: [position]}, now)
    account.async_set_updated_data(active_states)
    account._cancel_live_expiration()
    account._expire_live_positions(now)
    assert hass.states.get(room_id).state == "Office"
    account._cancel_live_expiration()
    account._expire_live_positions(now + timedelta(seconds=40))
    assert hass.states.get(room_id).state == "unknown"
    assert hass.states.get(timestamp_id).state == "unknown"
    assert len(account.live_path(robot_id).points) == 2
    await hass.config_entries.async_unload(entry.entry_id)
    assert account.live_path(robot_id) is None


async def test_live_map_only_uses_the_matching_topic_and_respects_retry_after(
    hass, entry, robot_states, cloud_session
):
    from custom_components.roomba_home.core.errors import ProtocolError, RateLimited

    account = RoombaCoordinator(hass, entry)
    robot = robot_states["fixture-0"]
    now = 0.0
    account._clock = lambda: now
    account.data = {
        **robot_states,
        robot.robot_id: replace(
            robot, phase="run", cycle="clean", telemetry={"mission_started": datetime.now(UTC)}
        ),
    }
    account._maps = {robot.robot_id: (MAP,)}
    discovery = cloud_session.discovery["deployments"]["fixture"]

    assert await account._live_topics(cloud_session) == {}
    discovery["irbtTopics"] = "fixture-irbt"
    account.client.live_map_topic = AsyncMock(
        side_effect=[
            RateLimited(90),
            ProtocolError("unavailable"),
            "foreign/topic",
            "fixture-irbt/things/fixture-0/livemap/update",
        ]
    )
    for clock_value, expected_count in ((0, 1), (89, 1), (90, 2), (150, 3), (200, 3)):
        now = clock_value
        assert await account._live_topics(cloud_session) == {}
        assert account.client.live_map_topic.await_count == expected_count
    now = 210
    assert await account._live_topics(cloud_session) == {
        robot.robot_id: "fixture-irbt/things/fixture-0/livemap/update"
    }


async def test_live_frames_flow_through_normal_account_refresh(
    hass, entry, robot_states, cloud_session, make_point_bundle
):
    from unittest.mock import Mock

    from custom_components.roomba_home.core.mqtt import ShadowReply

    hass.config_entries.async_update_entry(entry, options={CONF_SHOW_MAPS: True})
    account = RoombaCoordinator(hass, entry)
    now = datetime.now(UTC)
    start = int(now.timestamp()) - 60
    robot_id = "fixture-0"
    robot = replace(
        robot_states[robot_id],
        phase="run",
        cycle="clean",
        telemetry={"mission_started": datetime.fromtimestamp(start, UTC), "mission_number": 19},
    )
    account.data = {robot_id: robot}
    account._maps = {robot_id: (MAP,)}
    account._maps_available = {robot_id: True}
    cloud_session.raw["robots"][robot_id]["digiCap"] = {"timeline": 1}
    room = RoomResult((MAP.map_id, MAP.version_id, "room-a"), start, 0, 9, 10, 2)
    account._history[robot_id] = {"last_mission_room_results": (room,)}
    cloud_session.discovery["deployments"]["fixture"]["irbtTopics"] = "fixture-irbt"
    topic = "fixture-irbt/things/fixture-0/livemap/update"
    account.client.ensure_session = AsyncMock(return_value=cloud_session)
    account.client.live_map_topic = AsyncMock(return_value=topic)
    account.client.map_geometry = AsyncMock(return_value=make_point_bundle())
    account._optional_sources = AsyncMock()
    account._refresh_maps = AsyncMock()
    account._refresh_history = AsyncMock()
    account._refresh_schedules = AsyncMock()
    position = position_batch(
        {
            "timestamp": int(now.timestamp()),
            "update_expire_ts": int(now.timestamp()) + 40,
            "pos_update": {"cur_path": [3, 2, 1, 0, 2, int(now.timestamp())]},
        },
        int(now.timestamp()),
    )
    valid_documents = [
        ShadowReply(robot_id, "rw-constatus", True, {"state": {"reported": {"connectedv2": 1}}}),
        ShadowReply(
            robot_id,
            "ro-currentstate",
            True,
            {
                "state": {
                    "reported": {
                        "cleanMissionStatus": {
                            "phase": "run",
                            "cycle": "clean",
                            "mssnStrtTm": start,
                            "nMssn": 19,
                        }
                    }
                }
            },
        ),
    ]

    def read(
        shadows,
        *,
        allow_partial,
        live_topics=None,
        positions=None,
        timeline_requests=None,
        timelines=None,
    ):
        if live_topics:
            assert live_topics == {topic: robot_id}
            positions[robot_id] = [position]
            assert timeline_requests == {robot_id: 19}
            timelines[robot_id] = MissionTimeline(19, now, "start", (room,), (room,))
            return valid_documents
        return []

    with patch(
        "custom_components.roomba_home.coordinator.MqttShadowReader",
        return_value=Mock(read=read),
    ):
        state = (await account._read_account_state())[robot_id]
    assert state.telemetry["current_room"] == "Office"
    assert state.telemetry["live_timeline_rooms"][0]["room"] == "Office"
    assert state.telemetry["live_timeline_active_rooms"][0]["area"] == 9
    assert state.telemetry["last_mission_rooms"][0]["pass_count"] == 2
    assert account._timeline_requests((robot_id,), account._clock()) == {}
    assert account._timeline_metrics(state, None, now)["live_timeline_stage"] == "start"
    assert (
        account._timeline_metrics(state, MissionTimeline(18, now, "pause", ()), now)[
            "live_timeline_stage"
        ]
        == "start"
    )
    assert account._timeline_metrics(state, None, now + timedelta(seconds=101)) == {}
    assert account._timeline_metrics(replace(state, cycle="none"), None, now) == {}
    assert robot_id not in account._timeline_due
    await account.async_close()
    assert account._cancel_live_expiration is None


async def test_stale_path_is_not_reassigned_to_a_new_mission_or_floor(
    hass, entry, robot_states, make_point_bundle
):
    account = RoombaCoordinator(hass, entry)
    robot = robot_states["fixture-0"]
    robot_id = robot.robot_id
    now = datetime.now(UTC).replace(microsecond=0)
    start = now - timedelta(seconds=20)
    state = replace(robot, phase="run", cycle="clean", telemetry={"mission_started": start})
    account._maps = {robot_id: (MAP,)}
    account._maps_available = {robot_id: True}
    account.client.map_geometry = AsyncMock(return_value=make_point_bundle())
    account.data = {robot_id: state}

    timestamp = int(now.timestamp())
    position = position_batch(
        {
            "timestamp": timestamp,
            "update_expire_ts": timestamp + 30,
            "pos_update": {"cur_path": [1, 3, 2, 0, 2, timestamp]},
        },
        timestamp,
    )
    assert await account.async_floor_plan(robot_id, MAP)
    account.client.maps = AsyncMock(return_value=(MAP,))
    await account._read_maps(robot_id)
    assert account._floor_plans
    assert await account.async_floor_plan(robot_id, replace(MAP, map_id="not-associated")) is None
    await account._update_live_paths({robot_id: state}, {robot_id: [position]}, now)
    await account._update_live_paths({robot_id: state}, {}, now + timedelta(seconds=31))
    assert account.live_path(robot_id) is not None

    new_start = now + timedelta(seconds=10)
    new_mission = replace(state, telemetry={"mission_started": new_start})
    await account._update_live_paths({robot_id: new_mission}, {robot_id: [position]}, new_start)
    assert account.live_path(robot_id) is None

    other_version = replace(MAP, version_id="different")
    account.client.maps = AsyncMock(return_value=(other_version,))
    await account._read_maps(robot_id)
    assert account._floor_plans == {}
    assert await account.async_floor_plan(robot_id, other_version) is None
    await account._update_live_paths({robot_id: state}, {robot_id: [position]}, now)
    assert account.live_path(robot_id) is None
    await account.async_close()


async def test_image_failure_and_concurrent_version_change_keep_geometry_private(
    hass, entry, robot_states, make_point_bundle
):
    from custom_components.roomba_home.core.errors import ProtocolError

    hass.config_entries.async_update_entry(entry, options={CONF_SHOW_MAPS: True})
    robot = robot_states["fixture-0"]
    state = replace(robot, telemetry={"maps_available": True})

    async def first_refresh(account):
        account._maps = {robot.robot_id: (MAP,)}
        account._maps_available = {robot.robot_id: True}
        account.client.map_geometry = AsyncMock(side_effect=ProtocolError("Failed"))
        return {robot.robot_id: state}

    with patch.object(RoombaCoordinator, "_async_update_data", first_refresh):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    account = entry.runtime_data
    image_id = next(entity_id for entity_id in hass.states.async_entity_ids("image"))

    with pytest.raises(HomeAssistantError) as error:
        await async_get_image(hass, image_id)
    assert error.value.translation_key == "image_unavailable"

    original = account.async_floor_plan
    account.client.map_geometry.side_effect = None
    account.client.map_geometry.return_value = make_point_bundle()

    async def replace_map_during_image_request(robot_id, floor):
        geometry = await original(robot_id, floor)
        account._maps[robot_id] = (replace(floor, version_id="newest"),)
        return geometry

    account.async_floor_plan = replace_map_during_image_request
    with pytest.raises(HomeAssistantError) as error:
        await async_get_image(hass, image_id)
    assert error.value.translation_key == "image_unavailable"
    account._maps.clear()
    account.async_set_updated_data({robot.robot_id: replace(state)})
    assert hass.states.get(image_id).state == "unavailable"
    with pytest.raises(HomeAssistantError) as error:
        await async_get_image(hass, image_id)
    assert error.value.translation_key == "image_unavailable"


def test_floor_rendering_preserves_path_gaps_and_removes_expired_marker(make_point_bundle):
    from custom_components.roomba_home.core.live_maps import MissionPath
    from custom_components.roomba_home.core.point_maps import read_floor_plan
    from custom_components.roomba_home.image import render_floor_plan

    now = int(datetime.now(UTC).timestamp())
    timestamp = datetime.fromtimestamp(now, UTC)
    plan = read_floor_plan(make_point_bundle(), replace(MAP, regions=()))
    before = position_batch(
        {
            "timestamp": now,
            "update_expire_ts": now + 20,
            "pos_update": {"cur_path": [5, 1, 2, 0, 2, now]},
        },
        now,
    )
    after = replace(before, index=7)
    path = MissionPath((MAP.map_id, MAP.version_id), timestamp, after, ())
    path = path.append(before).append(after)
    still = render_floor_plan(plan, None, False)
    assert render_floor_plan(plan, path, False) == still
    assert render_floor_plan(plan, path, True) != still


def test_floor_image_renders_accents_and_normalizes_combining_marks(make_point_bundle):
    from unicodedata import normalize

    from custom_components.roomba_home.core.point_maps import read_floor_plan
    from custom_components.roomba_home.image import render_floor_plan

    plan = read_floor_plan(make_point_bundle(), MAP)

    def render(name):
        return render_floor_plan(
            replace(plan, rooms=(replace(plan.rooms[0], name=name),)), None, False
        )

    assert len({render(char) for char in "aeinouáéíñóúü"}) == 13
    assert render("Habitación de Núñez") == render(normalize("NFD", "Habitación de Núñez"))


def test_floor_names_fit_narrow_rooms_without_covering_a_hole():
    from io import BytesIO

    from PIL import Image, ImageChops

    from custom_components.roomba_home.core.point_maps import FloorPlan, FloorRoom
    from custom_components.roomba_home.image import MARGIN, render_floor_plan

    narrow = (((0, 0), (1, 0), (1, 4), (0, 4), (0, 0)),)
    tiny = (((2, 0), (2.1, 0), (2.1, 0.1), (2, 0.1), (2, 0)),)
    main = (
        ((4, 0), (14, 0), (14, 10), (4, 10), (4, 0)),
        ((7, 3), (11, 3), (11, 7), (7, 7), (7, 3)),
    )
    rooms = (FloorRoom(None, (narrow,)), FloorRoom(None, (tiny,)), FloorRoom(None, (main,)))

    def render(labels):
        plan = FloorPlan(
            tuple(replace(room, name=label) for room, label in zip(rooms, labels, strict=True))
        )
        return Image.open(BytesIO(render_floor_plan(plan, None, False)))

    baseline = render((None, None, None))
    with_names = render(("Pasillo estrechísimo y muy largo", "Tiny", "Distribución"))
    changes = ImageChops.difference(baseline, with_names)
    # 14 map units span the 704 px interior from left to right.
    unit = (baseline.width - 2 * MARGIN) / 14
    assert changes.crop((MARGIN, 0, MARGIN + round(unit), baseline.height)).getbbox() is not None
    assert (
        changes.crop(
            (MARGIN + round(2 * unit), 0, MARGIN + round(2.1 * unit), baseline.height)
        ).getbbox()
        is None
    )
    left, right = (MARGIN + round(x * unit) for x in (7, 11))
    top, bottom = (MARGIN + round(y * unit) for y in (3, 7))
    assert changes.crop((left, top, right, bottom)).getbbox() is None
    assert (
        changes.crop((MARGIN + round(4 * unit), 0, baseline.width, baseline.height)).getbbox()
        is not None
    )


def test_room_names_do_not_cover_an_existing_label():
    from PIL import Image, ImageFont

    from custom_components.roomba_home.image import (
        ROOM_LABEL_FONT,
        ROOM_LABEL_SIZE,
        _place_room_name,
    )

    font = ImageFont.truetype(ROOM_LABEL_FONT, ROOM_LABEL_SIZE)
    polygon = ([(10, 10), (150, 10), (150, 100), (10, 100), (10, 10)],)
    used = Image.new("1", (160, 110), 1)
    assert _place_room_name("Sala", polygon, font, used) is None


def test_robot_marker_stays_clear_of_the_room_label():
    from io import BytesIO

    from PIL import Image, ImageChops

    from custom_components.roomba_home.core.live_maps import MissionPath, Position, PositionBatch
    from custom_components.roomba_home.core.point_maps import FloorPlan, FloorRoom
    from custom_components.roomba_home.image import CANVAS_SIZE, render_floor_plan

    room = FloorRoom("Salón", ((((0, 0), (10, 0), (10, 10), (0, 10), (0, 0)),),))
    batch = PositionBatch(1, 10, 20, (Position(5, 5, 0, 2),))
    path = MissionPath(("fixture-map", "fixture-version"), datetime.now(UTC), batch, ())

    def render(item):
        return Image.open(BytesIO(render_floor_plan(FloorPlan((item,)), path, True)))

    changes = ImageChops.difference(render(room), render(replace(room, name=None)))
    middle = CANVAS_SIZE // 2
    marker_area = (middle - 17, middle - 17, middle + 18, middle + 18)
    assert changes.getbbox() is not None
    assert changes.crop(marker_area).getbbox() is None
